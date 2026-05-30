"""Theme and theme-image routes extracted from app.py."""

import json
import logging
import os
import time
import uuid
from pathlib import Path

from flask import Blueprint, g, jsonify, request, send_file
from werkzeug.exceptions import BadRequest

from database import SessionLocal
from models import Setting, Theme
from theme_defaults import (
    DEFAULT_THEME_SETTING_KEY,
    get_instance_default_theme,
    upsert_instance_default_theme,
)
from utils import (
    create_error_response,
    create_success_response,
    get_user_permissions,
    get_user_scoped_query,
    require_authentication,
    require_permission,
)

logger = logging.getLogger(__name__)

theme_bp = Blueprint("theme_routes", __name__)

_broadcast_theme_event = None


def configure_theme_routes(broadcast_theme_event):
    """Inject runtime callbacks owned by the main app module."""
    global _broadcast_theme_event
    _broadcast_theme_event = broadcast_theme_event


def _emit_theme_event(event_name, data, user_id=None):
    if _broadcast_theme_event is not None:
        _broadcast_theme_event(event_name, data, user_id=user_id)


def _get_user_accessible_theme(session, user_id, theme_id):
    """Return a theme only if it is visible to the current user."""
    return get_user_scoped_query(session, Theme, user_id).filter(Theme.id == theme_id).first()


def _get_globally_visible_theme(session, theme_id):
  """Return a theme only if it is globally visible to all users."""
  return session.query(Theme).filter(
    Theme.id == theme_id,
    (Theme.system_theme.is_(True) | Theme.global_theme.is_(True)),
  ).first()


def _get_default_theme_candidates(session):
  """Return themes eligible to be the instance default theme."""
  return session.query(Theme).filter(
    (Theme.system_theme.is_(True) | Theme.global_theme.is_(True)),
  ).order_by(Theme.name.asc()).all()


def _get_promotable_themes(session):
  """Return user themes that can be promoted to global visibility."""
  return session.query(Theme).filter(
    Theme.system_theme.is_(False),
    Theme.global_theme.is_(False),
    Theme.user_id.is_not(None),
  ).order_by(Theme.name.asc()).all()


def _get_demotable_themes(session):
  """Return global themes that can be demoted back to user scope."""
  return session.query(Theme).filter(
    Theme.system_theme.is_(False),
    Theme.global_theme.is_(True),
    Theme.user_id.is_not(None),
  ).order_by(Theme.name.asc()).all()


def _reset_demoted_theme_users(session, theme):
  """Move non-owner users off a theme that is losing global visibility."""
  replacement_theme = get_instance_default_theme(session)
  replacement_theme_id = str(replacement_theme.id) if replacement_theme else None
  if not replacement_theme_id:
    return

  affected_settings = session.query(Setting).filter(
    Setting.key == 'selected_theme',
    Setting.value == str(theme.id),
    Setting.user_id.is_not(None),
    Setting.user_id != theme.user_id,
  ).all()

  for setting in affected_settings:
    setting.value = replacement_theme_id


@theme_bp.route("/api/themes", methods=["GET"])
@require_permission('theme.view')
def get_themes():
    """List all themes accessible to the current user.
    ---
    tags:
      - Themes
    security:
      - session: []
    responses:
      200:
        description: Array of theme objects
      403:
        description: Insufficient permissions
      500:
        description: Server error
    """
    session = SessionLocal()
    try:
        user_id = g.user.id
        themes = get_user_scoped_query(session, Theme, user_id).all()
        return jsonify([theme.to_dict() for theme in themes]), 200
    except Exception as e:
        logger.error(f"Error getting themes: {str(e)}")
        return create_error_response(f"Error getting themes: {str(e)}", 500)
    finally:
        session.close()


@theme_bp.route("/api/themes/<int:theme_id>", methods=["GET"])
@require_permission('theme.view')
def get_theme(theme_id):
    """Get a single theme by ID.
    ---
    tags:
      - Themes
    security:
      - session: []
    parameters:
      - name: theme_id
        in: path
        required: true
        type: integer
    responses:
      200:
        description: Theme object
      403:
        description: Insufficient permissions
      404:
        description: Theme not found
      500:
        description: Server error
    """
    session = SessionLocal()
    try:
        user_id = g.user.id
        theme = get_user_scoped_query(session, Theme, user_id).filter(Theme.id == theme_id).first()
        if not theme:
            return create_error_response("Theme not found", 404)
        return jsonify(theme.to_dict()), 200
    except Exception as e:
        logger.error(f"Error getting theme {theme_id}: {str(e)}")
        return create_error_response(f"Error getting theme: {str(e)}", 500)
    finally:
        session.close()


@theme_bp.route("/api/themes/<int:theme_id>", methods=["PUT"])
@require_permission('theme.edit')
def update_theme(theme_id):
    """Update a theme's name, settings or background image.
    ---
    tags:
      - Themes
    security:
      - session: []
    parameters:
      - name: theme_id
        in: path
        required: true
        type: integer
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            name:
              type: string
            settings:
              type: object
            background_image:
              type: string
    responses:
      200:
        description: Updated theme object
      400:
        description: Invalid data or system theme
      403:
        description: Insufficient permissions
      404:
        description: Theme not found
      500:
        description: Server error
    """
    session = SessionLocal()
    try:
        user_id = g.user.id
        theme = _get_user_accessible_theme(session, user_id, theme_id)
        if not theme:
            return create_error_response("Theme not found", 404)

        if theme.system_theme or theme.global_theme:
          return create_error_response("Cannot update system or global themes", 400)

        try:
            data = request.get_json(silent=True)
        except BadRequest:
            data = None

        if not data or not isinstance(data, dict):
            return create_error_response("Request body must contain valid JSON object", 400)

        if 'name' in data:
            existing = session.query(Theme).filter(Theme.name == data['name'], Theme.id != theme_id).first()
            if existing:
                return create_error_response("Theme name already exists", 400)
            theme.name = data['name']

        if 'settings' in data:
            theme.settings = json.dumps(data['settings'])

        if 'background_image' in data:
            theme.background_image = data['background_image']

        session.commit()

        _emit_theme_event('theme_updated', {
            'theme_id': theme_id,
            'theme_name': theme.name,
        }, user_id=user_id)

        return jsonify(theme.to_dict()), 200
    except Exception as e:
        session.rollback()
        logger.error(f"Error updating theme {theme_id}: {str(e)}")
        return create_error_response(f"Error updating theme: {str(e)}", 500)
    finally:
        session.close()


@theme_bp.route("/api/themes/<int:theme_id>/rename", methods=["PUT"])
@require_permission('theme.edit')
def rename_theme(theme_id):
    """Rename a theme.
    ---
    tags:
      - Themes
    security:
      - session: []
    parameters:
      - name: theme_id
        in: path
        required: true
        type: integer
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - name
          properties:
            name:
              type: string
    responses:
      200:
        description: Renamed theme object
      400:
        description: Name missing, taken, or system theme
      403:
        description: Insufficient permissions
      404:
        description: Theme not found
      500:
        description: Server error
    """
    session = SessionLocal()
    try:
        user_id = g.user.id
        theme = _get_user_accessible_theme(session, user_id, theme_id)
        if not theme:
            return create_error_response("Theme not found", 404)

        if theme.system_theme or theme.global_theme:
          return create_error_response("Cannot rename system or global themes", 400)

        data = request.get_json()
        new_name = data.get('name')

        if not new_name:
            return create_error_response("name is required", 400)

        existing = session.query(Theme).filter(Theme.name == new_name, Theme.id != theme_id).first()
        if existing:
            return create_error_response("Theme name already exists", 400)

        theme.name = new_name
        session.commit()

        return jsonify(theme.to_dict()), 200
    except Exception as e:
        session.rollback()
        logger.error(f"Error renaming theme {theme_id}: {str(e)}")
        return create_error_response(f"Error renaming theme: {str(e)}", 500)
    finally:
        session.close()


@theme_bp.route("/api/themes/<int:theme_id>", methods=["DELETE"])
@require_permission('theme.delete')
def delete_theme(theme_id):
    """Delete a user-owned theme.
    ---
    tags:
      - Themes
    security:
      - session: []
    parameters:
      - name: theme_id
        in: path
        required: true
        type: integer
    responses:
      200:
        description: Theme deleted
      400:
        description: Cannot delete system themes
      403:
        description: Insufficient permissions
      404:
        description: Theme not found
      500:
        description: Server error
    """
    session = SessionLocal()
    try:
        user_id = g.user.id
        theme = _get_user_accessible_theme(session, user_id, theme_id)
        if not theme:
            return create_error_response("Theme not found", 404)

        if theme.system_theme:
          return create_error_response("Cannot delete system themes", 400)

        if theme.global_theme:
          return create_error_response("Demote global themes before deleting them", 400)

        session.delete(theme)
        session.commit()

        return create_success_response(message="Theme deleted successfully")
    except Exception as e:
        session.rollback()
        logger.error(f"Error deleting theme {theme_id}: {str(e)}")
        return create_error_response(f"Error deleting theme: {str(e)}", 500)
    finally:
        session.close()


@theme_bp.route("/api/themes/copy", methods=["POST"])
@require_permission('theme.create')
def copy_theme():
    """Copy a system theme into a new user-owned theme.
    ---
    tags:
      - Themes
    security:
      - session: []
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - source_theme_id
            - new_name
          properties:
            source_theme_id:
              type: integer
            new_name:
              type: string
    responses:
      201:
        description: New theme object
      400:
        description: Missing fields, name taken, or source is not a system theme
      403:
        description: Insufficient permissions
      404:
        description: Source theme not found
      500:
        description: Server error
    """
    session = SessionLocal()
    try:
        user_id = g.user.id
        data = request.get_json()
        source_id = data.get('source_theme_id')
        new_name = data.get('new_name')

        if not source_id or not new_name:
            return create_error_response("source_theme_id and new_name are required", 400)

        source_theme = _get_user_accessible_theme(session, user_id, source_id)
        if not source_theme:
            return create_error_response("Source theme not found", 404)

        if not (source_theme.system_theme or source_theme.global_theme):
          return create_error_response("Only system or global themes can be copied", 400)

        existing = session.query(Theme).filter(Theme.name == new_name).first()
        if existing:
            return create_error_response("Theme name already exists", 400)

        new_theme = Theme(
            name=new_name,
            settings=source_theme.settings,
            background_image=source_theme.background_image,
            system_theme=False,
            user_id=user_id,
        )
        session.add(new_theme)
        session.commit()

        return jsonify(new_theme.to_dict()), 201
    except Exception as e:
        session.rollback()
        logger.error(f"Error copying theme: {str(e)}")
        return create_error_response(f"Error copying theme: {str(e)}", 500)
    finally:
        session.close()


@theme_bp.route("/api/themes/import", methods=["POST"])
@require_permission('theme.create')
def import_theme():
    """Create a theme from raw settings JSON.
    ---
    tags:
      - Themes
    security:
      - session: []
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - name
            - settings
          properties:
            name:
              type: string
            settings:
              type: object
            background_image:
              type: string
    responses:
      201:
        description: Created theme object
      400:
        description: Missing fields, invalid settings, or name taken
      403:
        description: Insufficient permissions
      500:
        description: Server error
    """
    session = SessionLocal()
    try:
        user_id = g.user.id
        data = request.get_json()
        name = data.get('name')
        settings = data.get('settings')

        if not name or not settings:
            return create_error_response("name and settings are required", 400)

        required_keys = ['primary-color', 'text-color', 'background-light', 'card-bg-color']
        if not all(key in settings for key in required_keys):
            return create_error_response("Invalid theme settings structure", 400)

        existing = session.query(Theme).filter(Theme.name == name).first()
        if existing:
            return create_error_response("Theme name already exists", 400)

        new_theme = Theme(
            name=name,
            settings=json.dumps(settings),
            background_image=data.get('background_image'),
            system_theme=False,
            user_id=user_id,
        )
        session.add(new_theme)
        session.commit()

        return jsonify(new_theme.to_dict()), 201
    except Exception as e:
        session.rollback()
        logger.error(f"Error importing theme: {str(e)}")
        return create_error_response(f"Error importing theme: {str(e)}", 500)
    finally:
        session.close()


@theme_bp.route("/api/themes/<int:theme_id>/export", methods=["GET"])
@require_permission('theme.view')
def export_theme(theme_id):
    """Export a theme's settings as JSON.
    ---
    tags:
      - Themes
    security:
      - session: []
    parameters:
      - name: theme_id
        in: path
        required: true
        type: integer
    responses:
      200:
        description: Theme settings JSON
      403:
        description: Insufficient permissions
      404:
        description: Theme not found
      500:
        description: Server error
    """
    session = SessionLocal()
    try:
        user_id = g.user.id
        theme = _get_user_accessible_theme(session, user_id, theme_id)
        if not theme:
            return create_error_response("Theme not found", 404)

        export_data = {
            'name': theme.name,
            'settings': json.loads(theme.settings) if isinstance(theme.settings, str) else theme.settings,
            'background_image': theme.background_image,
        }

        return jsonify(export_data), 200
    except Exception as e:
        logger.error(f"Error exporting theme {theme_id}: {str(e)}")
        return create_error_response(f"Error exporting theme: {str(e)}", 500)
    finally:
        session.close()


@theme_bp.route("/api/themes/upload-image", methods=["POST"])
@require_permission('theme.edit')
def upload_theme_image():
    """Upload a background image for use in themes.
    ---
    tags:
      - Themes
    security:
      - session: []
    consumes:
      - multipart/form-data
    parameters:
      - name: image
        in: formData
        required: true
        type: file
        description: Image file (jpg, jpeg, png, gif, webp)
    responses:
      200:
        description: Uploaded filename
      400:
        description: No file, no selection, or invalid type
      403:
        description: Insufficient permissions
      500:
        description: Server error
    """
    try:
        if 'image' not in request.files:
            return create_error_response("No image file provided", 400)

        file = request.files['image']
        if file.filename == '':
            return create_error_response("No file selected", 400)

        allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
        file_ext = Path(file.filename).suffix.lower()
        if file_ext not in allowed_extensions:
            return create_error_response(f"Invalid file type. Allowed: {', '.join(allowed_extensions)}", 400)

        backgrounds_dir = Path('/var/www/images/backgrounds')
        backgrounds_dir.mkdir(parents=True, exist_ok=True)

        timestamp = int(time.time())
        unique_id = str(uuid.uuid4())[:8]
        filename = f"theme_bg_{timestamp}_{unique_id}{file_ext}"
        filepath = backgrounds_dir / filename

        file.save(str(filepath))

        return jsonify({'filename': filename}), 200
    except Exception as e:
        logger.error(f"Error uploading theme image: {str(e)}")
        return create_error_response(f"Error uploading image: {str(e)}", 500)


@theme_bp.route("/api/themes/images", methods=["GET"])
@require_permission('theme.view')
def list_theme_images():
    """List available background images for themes.
    ---
    tags:
      - Themes
    security:
      - session: []
    responses:
      200:
        description: Sorted list of image filenames
      403:
        description: Insufficient permissions
      500:
        description: Server error
    """
    try:
        backgrounds_dir = Path('/var/www/images/backgrounds')
        backgrounds_dir.mkdir(parents=True, exist_ok=True)

        allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
        images = []
        for file in backgrounds_dir.iterdir():
            if file.is_file() and file.suffix.lower() in allowed_extensions:
                images.append(file.name)

        images.sort()
        return jsonify({'images': images}), 200
    except Exception as e:
        logger.error(f"Error listing theme images: {str(e)}")
        return create_error_response(f"Error listing images: {str(e)}", 500)


@theme_bp.route("/api/themes/images/<safe_filename:filename>", methods=["GET"])
@require_permission('theme.view')
def get_theme_image(filename):
    """Serve a background image file.
    ---
    tags:
      - Themes
    security:
      - session: []
    parameters:
      - name: filename
        in: path
        required: true
        type: string
    responses:
      200:
        description: Image file
      400:
        description: Invalid path or file type
      403:
        description: Insufficient permissions
      404:
        description: Image not found
      500:
        description: Server error
    """
    try:
        logger.info(f"get_theme_image called with filename: {repr(filename)}")

        if '..' in filename:
            logger.warning(f"Path traversal attempt blocked: {repr(filename)}")
            return create_error_response("Invalid file path", 400)

        backgrounds_dir = Path('/var/www/images/backgrounds')
        filepath = backgrounds_dir / filename

        try:
            common = os.path.commonpath([str(filepath.resolve()), str(backgrounds_dir.resolve())])
            if common != str(backgrounds_dir.resolve()):
                logger.warning(f"Path outside backgrounds directory: {filepath.resolve()}")
                return create_error_response("Invalid file path", 400)
        except ValueError:
            logger.warning(f"Paths on different drives: {filepath.resolve()}")
            return create_error_response("Invalid file path", 400)

        allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
        if filepath.suffix.lower() not in allowed_extensions:
            logger.warning(f"Blocked request for non-image file: {filepath}")
            return create_error_response("Invalid file type", 400)

        if not filepath.exists():
            logger.info(f"Image file not found: {filepath}")
            return create_error_response("Image not found", 404)

        if not filepath.is_file():
            logger.warning(f"Path is not a file: {filepath}")
            return create_error_response("Invalid file path", 400)

        logger.info(f"Serving image file: {filepath}")
        return send_file(str(filepath))
    except Exception as e:
        logger.error(f"Error getting theme image {filename}: {str(e)}")
        return create_error_response(f"Error getting image: {str(e)}", 500)


@theme_bp.route("/api/settings/theme", methods=["GET"])
@require_permission('setting.view')
def get_current_theme():
    """Get the current user's selected theme.
    ---
    tags:
      - Themes
    security:
      - session: []
    responses:
      200:
        description: Current theme object
      403:
        description: Insufficient permissions
      404:
        description: No theme selected or selected theme not found
      500:
        description: Server error
    """
    session = SessionLocal()
    try:
        user_id = g.user.id
        setting = get_user_scoped_query(session, Setting, user_id).filter(Setting.key == 'selected_theme').first()
        if not setting:
            return create_error_response("No theme selected", 404)

        try:
            theme_id = int(setting.value)
            if theme_id <= 0:
                raise ValueError("theme_id must be a positive integer")
        except (ValueError, TypeError):
            logger.warning(f"Corrupted selected_theme value for user {user_id}: {setting.value!r}, resetting")
            setting.value = None
            session.commit()
            return create_error_response("No theme selected", 404)

        theme = _get_user_accessible_theme(session, user_id, theme_id)
        if not theme:
            return create_error_response("Selected theme not found", 404)

        return jsonify(theme.to_dict()), 200
    except Exception as e:
        logger.error(f"Error getting current theme: {str(e)}")
        return create_error_response(f"Error getting current theme: {str(e)}", 500)
    finally:
        session.close()


@theme_bp.route("/api/settings/default-theme", methods=["GET"])
@require_authentication
def get_default_theme():
    """Get the instance default theme used for new users and public boards.
    ---
    tags:
      - Themes
    security:
      - session: []
    responses:
      200:
        description: Current instance default theme
      401:
        description: Authentication required
      500:
        description: Server error
    """
    session = SessionLocal()
    try:
        user_id = g.user.id
        theme = get_instance_default_theme(session)
        if not theme:
            return create_error_response("Default theme not found", 404)

        response_payload = {
            "success": True,
            "key": DEFAULT_THEME_SETTING_KEY,
            "value": theme.id,
            "theme": theme.to_dict(),
        }

        user_permissions = get_user_permissions(user_id)
        if 'branding.edit' in user_permissions:
          response_payload["available_themes"] = [
            t.to_dict() for t in _get_default_theme_candidates(session)
          ]
          response_payload["promotable_themes"] = [
            t.to_dict() for t in _get_promotable_themes(session)
          ]
          response_payload["demotable_themes"] = [
            t.to_dict() for t in _get_demotable_themes(session)
          ]

        return jsonify(response_payload), 200
    except Exception as e:
        logger.error(f"Error getting default theme: {str(e)}")
        return create_error_response(f"Error getting default theme: {str(e)}", 500)
    finally:
        session.close()


@theme_bp.route("/api/settings/default-theme", methods=["PUT"])
@require_permission('branding.edit')
def set_default_theme():
    """Set the instance default theme used for new users and public boards.
    ---
    tags:
      - Themes
    security:
      - session: []
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - theme_id
          properties:
            theme_id:
              type: integer
    responses:
      200:
        description: Instance default theme updated
      400:
        description: Invalid payload
      404:
        description: Theme not found
      500:
        description: Server error
    """
    session = SessionLocal()
    try:
        try:
            data = request.get_json(silent=True)
        except BadRequest:
            data = None

        if not data or not isinstance(data, dict):
            return create_error_response("Request body must contain valid JSON object", 400)

        raw_theme_id = data.get('theme_id')
        try:
            theme_id = int(raw_theme_id)
            if theme_id <= 0:
                raise ValueError("theme_id must be a positive integer")
        except (TypeError, ValueError):
            return create_error_response("theme_id must be a valid positive integer", 400)

        theme = session.query(Theme).filter(Theme.id == theme_id).first()
        if not theme:
            return create_error_response("Theme not found", 404)

        if not (theme.system_theme or theme.global_theme):
          return create_error_response("Instance default theme must be a system or global theme", 400)

        upsert_instance_default_theme(session, theme_id)
        session.commit()

        return jsonify({
            "success": True,
            "message": "Default theme updated",
            "key": DEFAULT_THEME_SETTING_KEY,
            "value": theme_id,
            "theme": theme.to_dict(),
        }), 200
    except Exception as e:
        session.rollback()
        logger.error(f"Error setting default theme: {str(e)}")
        return create_error_response(f"Error setting default theme: {str(e)}", 500)
    finally:
        session.close()


@theme_bp.route("/api/themes/<int:theme_id>/promote-global", methods=["POST"])
@require_permission('branding.edit')
def promote_theme_to_global(theme_id):
    """Promote a user theme to global visibility.
    ---
    tags:
      - Themes
    security:
      - session: []
    parameters:
      - name: theme_id
        in: path
        required: true
        type: integer
    responses:
      200:
        description: Theme promoted to global visibility
      400:
        description: Theme cannot be promoted
      404:
        description: Theme not found
      500:
        description: Server error
    """
    session = SessionLocal()
    try:
        theme = session.query(Theme).filter(Theme.id == theme_id).first()
        if not theme:
            return create_error_response("Theme not found", 404)

        if theme.system_theme:
            return create_error_response("System themes are already globally available", 400)

        if theme.user_id is None:
            return create_error_response("Only user themes can be promoted", 400)

        if theme.global_theme:
            return create_error_response("Theme is already global", 400)

        theme.global_theme = True
        session.commit()

        return jsonify({
            "success": True,
            "message": "Theme promoted to global visibility",
            "theme": theme.to_dict(),
        }), 200
    except Exception as e:
        session.rollback()
        logger.error(f"Error promoting theme {theme_id} to global: {str(e)}")
        return create_error_response(f"Error promoting theme: {str(e)}", 500)
    finally:
        session.close()


@theme_bp.route("/api/themes/<int:theme_id>/demote-global", methods=["POST"])
@require_permission('branding.edit')
def demote_theme_from_global(theme_id):
    """Demote a global theme back to user-only visibility.
    ---
    tags:
      - Themes
    security:
      - session: []
    parameters:
      - name: theme_id
        in: path
        required: true
        type: integer
    responses:
      200:
        description: Theme demoted from global visibility
      400:
        description: Theme cannot be demoted
      404:
        description: Theme not found
      500:
        description: Server error
    """
    session = SessionLocal()
    try:
        theme = session.query(Theme).filter(Theme.id == theme_id).first()
        if not theme:
            return create_error_response("Theme not found", 404)

        if theme.system_theme:
            return create_error_response("System themes cannot be demoted", 400)

        if not theme.global_theme:
            return create_error_response("Theme is not global", 400)

        current_default_theme = get_instance_default_theme(session)
        if current_default_theme and current_default_theme.id == theme.id:
            return create_error_response(
                "Change the instance default theme before demoting this global theme",
                400,
            )

        theme.global_theme = False
        _reset_demoted_theme_users(session, theme)
        session.commit()

        return jsonify({
            "success": True,
            "message": "Theme demoted from global visibility",
            "theme": theme.to_dict(),
        }), 200
    except Exception as e:
        session.rollback()
        logger.error(f"Error demoting theme {theme_id} from global: {str(e)}")
        return create_error_response(f"Error demoting theme: {str(e)}", 500)
    finally:
        session.close()


@theme_bp.route("/api/settings/theme", methods=["PUT"])
@require_permission('setting.edit')
def update_current_theme():
    """Set the current user's selected theme.
    ---
    tags:
      - Themes
    security:
      - session: []
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - theme_id
          properties:
            theme_id:
              type: integer
    responses:
      200:
        description: Theme selection updated
      400:
        description: Invalid theme_id
      403:
        description: Insufficient permissions
      404:
        description: Theme not found
      500:
        description: Server error
    """
    session = SessionLocal()
    try:
        user_id = g.user.id
        try:
            data = request.get_json(silent=True)
        except BadRequest:
            data = None

        if not data or not isinstance(data, dict):
            return create_error_response("Request body must contain valid JSON object", 400)

        raw_theme_id = data.get('theme_id')
        try:
            theme_id = int(raw_theme_id)
            if theme_id <= 0:
                raise ValueError("theme_id must be a positive integer")
        except (ValueError, TypeError):
            return create_error_response("theme_id must be a valid positive integer", 400)

        theme = _get_user_accessible_theme(session, user_id, theme_id)
        if not theme:
            return create_error_response("Theme not found", 404)

        setting = get_user_scoped_query(session, Setting, user_id).filter(Setting.key == 'selected_theme').first()
        if setting:
            setting.value = str(theme_id)
        else:
            setting = Setting(
                key='selected_theme',
                value=str(theme_id),
                user_id=user_id,
            )
            session.add(setting)

        session.commit()

        _emit_theme_event('theme_changed', {
            'theme_id': theme_id,
            'theme_name': theme.name,
        }, user_id=user_id)

        return create_success_response(message="Theme selection updated")
    except Exception as e:
        session.rollback()
        logger.error(f"Error updating current theme: {str(e)}")
        return create_error_response(f"Error updating theme selection: {str(e)}", 500)
    finally:
        session.close()