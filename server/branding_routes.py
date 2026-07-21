"""Branding routes for instance-wide logo management."""

import logging
import os
import time
import uuid
from pathlib import Path

from flask import Blueprint, jsonify, request

from database import SessionLocal
from models import InstanceConfig
from utils import create_error_response, create_success_response, require_permission

logger = logging.getLogger(__name__)

branding_bp = Blueprint("branding_routes", __name__)

ALLOWED_LOGO_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
MAX_LOGO_UPLOAD_BYTES = 100 * 1024  # 100KB
CUSTOM_LOGO_CONFIG_KEY = 'custom_logo_filename'
LOGOS_DIR = Path('/var/www/images/backgrounds/logos')

APP_NAME_CONFIG_KEY = 'pwa_app_name'
DEFAULT_APP_NAME = 'AFT Tasks'
DEFAULT_APP_SHORT_NAME = 'AFT'
MAX_APP_NAME_LENGTH = 45  # Android's install UI truncates well before this; keeps things sane.
MAX_APP_SHORT_NAME_LENGTH = 12  # Home-screen label space is tight, especially on iOS.


@branding_bp.route('/api/branding/logo', methods=['GET'])
def get_branding_logo():
    """Get the active instance logo filename.
    ---
    tags:
      - Branding
    responses:
      200:
        description: Active logo filename (or null when default logo is active)
        schema:
          type: object
          properties:
            filename:
              type: string
              nullable: true
      500:
        description: Server error
    """
    session = SessionLocal()
    try:
        config = session.query(InstanceConfig).filter(
            InstanceConfig.key == CUSTOM_LOGO_CONFIG_KEY
        ).first()
        return jsonify({'filename': config.value if config and config.value else None}), 200
    except Exception as e:
        logger.error(f"Error getting branding logo: {str(e)}")
        return create_error_response('Error getting branding logo', 500)
    finally:
        session.close()


@branding_bp.route('/api/branding/logo', methods=['POST'])
@require_permission('branding.edit')
def upload_branding_logo():
    """Upload a new instance-wide logo.
    ---
    tags:
      - Branding
    security:
      - session: []
    consumes:
      - multipart/form-data
    parameters:
      - name: image
        in: formData
        required: true
        type: file
        description: Logo image file (recommended WebP/PNG, max 100KB)
    responses:
      200:
        description: Uploaded logo filename
        schema:
          type: object
          properties:
            filename:
              type: string
      400:
        description: Missing file, invalid type, or size limit exceeded
      403:
        description: Insufficient permissions
      500:
        description: Server error
    """
    session = SessionLocal()
    try:
        if 'image' not in request.files:
            return create_error_response('No image file provided', 400)

        file = request.files['image']
        if file.filename == '':
            return create_error_response('No file selected', 400)

        file_ext = Path(file.filename).suffix.lower()
        if file_ext not in ALLOWED_LOGO_EXTENSIONS:
            allowed = ', '.join(sorted(ALLOWED_LOGO_EXTENSIONS))
            return create_error_response(f'Invalid file type. Allowed: {allowed}', 400)

        # Validate file size before saving to disk.
        file.stream.seek(0, os.SEEK_END)
        file_size = file.stream.tell()
        file.stream.seek(0)
        if file_size > MAX_LOGO_UPLOAD_BYTES:
            return create_error_response('File too large. Maximum allowed size is 100KB', 400)

        LOGOS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = int(time.time())
        unique_id = str(uuid.uuid4())[:8]
        filename = f'logo_{timestamp}_{unique_id}{file_ext}'
        file_path = LOGOS_DIR / filename
        file.save(str(file_path))

        config = session.query(InstanceConfig).filter(
            InstanceConfig.key == CUSTOM_LOGO_CONFIG_KEY
        ).first()
        if not config:
            config = InstanceConfig(key=CUSTOM_LOGO_CONFIG_KEY, value=filename)
            session.add(config)
        else:
            config.value = filename

        session.commit()
        return jsonify({'filename': filename}), 200
    except Exception as e:
        session.rollback()
        logger.error(f"Error uploading branding logo: {str(e)}")
        return create_error_response('Error uploading branding logo', 500)
    finally:
        session.close()


@branding_bp.route('/api/branding/logo', methods=['DELETE'])
@require_permission('branding.edit')
def clear_branding_logo():
    """Reset instance logo to the default built-in logo.
    ---
    tags:
      - Branding
    security:
      - session: []
    responses:
      200:
        description: Logo reset successfully
      403:
        description: Insufficient permissions
      500:
        description: Server error
    """
    session = SessionLocal()
    try:
        config = session.query(InstanceConfig).filter(
            InstanceConfig.key == CUSTOM_LOGO_CONFIG_KEY
        ).first()
        if config:
            session.delete(config)
            session.commit()

        return create_success_response(message='Custom logo reset to default')
    except Exception as e:
        session.rollback()
        logger.error(f"Error clearing branding logo: {str(e)}")
        return create_error_response('Error clearing branding logo', 500)
    finally:
        session.close()


def get_configured_app_name():
    """Read the instance's configured PWA app name, falling back to the default.

    Used by both the branding API and the dynamic manifest route, so a name
    change takes effect immediately without a rebuild - unlike a static
    manifest.webmanifest, which would bake one name in for every deployment.
    """
    session = SessionLocal()
    try:
        config = session.query(InstanceConfig).filter(
            InstanceConfig.key == APP_NAME_CONFIG_KEY
        ).first()
        if config and config.value:
            return config.value
        return DEFAULT_APP_NAME
    finally:
        session.close()


@branding_bp.route('/api/branding/app-name', methods=['GET'])
def get_branding_app_name():
    """Get the active instance PWA app name.
    ---
    tags:
      - Branding
    responses:
      200:
        description: Active app name (default when not customized)
        schema:
          type: object
          properties:
            name:
              type: string
      500:
        description: Server error
    """
    try:
        return jsonify({'name': get_configured_app_name()}), 200
    except Exception as e:
        logger.error(f"Error getting branding app name: {str(e)}")
        return create_error_response('Error getting branding app name', 500)


@branding_bp.route('/api/branding/app-name', methods=['PUT'])
@require_permission('branding.edit')
def set_branding_app_name():
    """Set the instance PWA app name shown on the home-screen install.

    Distinguishes multiple self-hosted AFT instances installed on the same
    device (which would otherwise all show an identical "AFT Tasks" icon
    and name with no way to tell them apart).
    ---
    tags:
      - Branding
    security:
      - session: []
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            name:
              type: string
              example: AFT - Work
    responses:
      200:
        description: App name updated
        schema:
          type: object
          properties:
            name:
              type: string
      400:
        description: Missing or invalid name
      403:
        description: Insufficient permissions
      500:
        description: Server error
    """
    session = SessionLocal()
    try:
        data = request.get_json(silent=True) or {}
        name = (data.get('name') or '').strip()

        if not name:
            return create_error_response('name is required', 400)
        if len(name) > MAX_APP_NAME_LENGTH:
            return create_error_response(f'name must be {MAX_APP_NAME_LENGTH} characters or fewer', 400)

        config = session.query(InstanceConfig).filter(
            InstanceConfig.key == APP_NAME_CONFIG_KEY
        ).first()
        if not config:
            config = InstanceConfig(key=APP_NAME_CONFIG_KEY, value=name)
            session.add(config)
        else:
            config.value = name

        session.commit()
        return jsonify({'name': name}), 200
    except Exception as e:
        session.rollback()
        logger.error(f"Error setting branding app name: {str(e)}")
        return create_error_response('Error setting branding app name', 500)
    finally:
        session.close()


@branding_bp.route('/api/branding/app-name', methods=['DELETE'])
@require_permission('branding.edit')
def clear_branding_app_name():
    """Reset the PWA app name to the default ("AFT Tasks").
    ---
    tags:
      - Branding
    security:
      - session: []
    responses:
      200:
        description: App name reset successfully
      403:
        description: Insufficient permissions
      500:
        description: Server error
    """
    session = SessionLocal()
    try:
        config = session.query(InstanceConfig).filter(
            InstanceConfig.key == APP_NAME_CONFIG_KEY
        ).first()
        if config:
            session.delete(config)
            session.commit()

        return create_success_response(message='App name reset to default')
    except Exception as e:
        session.rollback()
        logger.error(f"Error clearing branding app name: {str(e)}")
        return create_error_response('Error clearing branding app name', 500)
    finally:
        session.close()


@branding_bp.route('/manifest.webmanifest', methods=['GET'])
def get_pwa_manifest():
    """Serve the PWA web app manifest with the instance's configured app name.

    Served dynamically (rather than as a static file) so a self-hosted
    instance can be renamed without a rebuild, and so multiple instances
    installed on the same device show distinct names/icons instead of an
    identical "AFT Tasks" for every deployment.
    ---
    tags:
      - Branding
    produces:
      - application/manifest+json
    responses:
      200:
        description: Web app manifest
    """
    app_name = get_configured_app_name()
    # Short name mirrors the full name when custom (space is tight on the
    # home screen, but showing *something* distinct beats the generic "AFT"
    # default when a name has been explicitly set); truncated to fit.
    short_name = app_name[:MAX_APP_SHORT_NAME_LENGTH] if app_name != DEFAULT_APP_NAME else DEFAULT_APP_SHORT_NAME

    manifest = {
        'id': '/',
        'name': app_name,
        'short_name': short_name,
        'description': 'Aim, Focus, Track - self-hosted task and board management.',
        'start_url': '/',
        'scope': '/',
        'display': 'standalone',
        'background_color': '#ffffff',
        'theme_color': '#2C3E50',
        'icons': [
            {'src': '/icons/icon-192.png', 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any'},
            {'src': '/icons/icon-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any'},
            {'src': '/icons/icon-512-maskable.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'},
        ],
    }

    response = jsonify(manifest)
    response.headers['Content-Type'] = 'application/manifest+json'
    return response, 200
