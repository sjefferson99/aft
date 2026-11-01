from flask import Blueprint, jsonify, request, g
from database import SessionLocal
from models import Setting, Board, BoardSetting
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
import json
import logging
from utils import (
    get_user_scoped_query,
    get_user_permissions,
    require_permission,
    require_board_access,
    create_error_response,
)
from settings_schema import (
    SETTINGS_SCHEMA,
    WORKING_STYLE_ALLOWED_VALUES,
    get_board_working_style,
    get_user_default_working_style,
    normalize_working_style,
    validate_setting,
)

logger = logging.getLogger(__name__)

settings_bp = Blueprint("settings", __name__)


@settings_bp.route("/api/settings/schema", methods=["GET"])
@require_permission('setting.view')
def get_settings_schema():
    """Get the settings schema showing all allowed settings and their validation rules.
    ---
    tags:
      - Settings
    responses:
      200:
        description: Settings schema
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            schema:
              type: object
              description: Map of setting keys to their schema definitions
      500:
        description: Server error
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            message:
              type: string
    """
    try:
        # Build schema response without the validate functions (not JSON serializable)
        schema_response = {}
        for key, schema in SETTINGS_SCHEMA.items():
            schema_response[key] = {
                "type": schema["type"],
                "nullable": schema.get("nullable", False),
                "description": schema.get("description", ""),
            }

        return jsonify({"success": True, "schema": schema_response})
    except Exception as e:
        logger.error(f"Error getting settings schema: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500


@settings_bp.route("/api/settings/<key>", methods=["GET"])
@require_permission('setting.view')
def get_setting(key):
    """Get a setting value by key (user-specific or global) with validation.
    ---
    tags:
      - Settings
    parameters:
      - name: key
        in: path
        type: string
        required: true
        description: The setting key to retrieve
    responses:
      200:
        description: Setting value (validated)
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            key:
              type: string
              example: "default_board"
            value:
              description: JSON parsed value
              example: null
      401:
        description: Authentication required
      403:
        description: Permission denied
      404:
        description: Setting not found
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            message:
              type: string
      500:
        description: Server error
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            message:
              type: string
    """
    db = SessionLocal()
    try:
        user_id = g.user.id
        # Use user-scoped query which gets user's settings + global settings (where user_id IS NULL)
        setting = get_user_scoped_query(db, Setting, user_id).filter(Setting.key == key).first()

        if not setting:
            return (
                jsonify({"success": False, "message": f"Setting '{key}' not found"}),
                404,
            )

        # Parse JSON value
        try:
            value = json.loads(setting.value) if setting.value else None
        except json.JSONDecodeError:
            value = setting.value

        # Special validation for default_board
        if key == "default_board" and value is not None:
            # Check if board exists AND is still accessible to this user
            board = get_user_scoped_query(db, Board, user_id).filter(Board.id == value).first()
            if not board:
                # Board doesn't exist or is no longer accessible — auto-correct to null
                logger.warning(f"Default board {value} not found or inaccessible for user {user_id}, resetting to null")
                setting.value = "null"
                db.commit()
                value = None

        return jsonify({"success": True, "key": key, "value": value})
    except Exception as e:
        db.rollback()
        logger.error(f"Error getting setting: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        db.close()


@settings_bp.route("/api/settings/<key>", methods=["PUT"])
@require_permission('setting.edit')
def set_setting(key):
    """Create or update a user-specific setting (upsert).
    ---
    tags:
      - Settings
    parameters:
      - name: key
        in: path
        type: string
        required: true
        description: The setting key to set
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - value
          properties:
            value:
              description: The value to store (will be JSON stringified)
              example: 123
    responses:
      200:
        description: Setting updated successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            message:
              type: string
              example: "Setting updated successfully"
            key:
              type: string
            value:
              description: The stored value
      400:
        description: Bad request
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            message:
              type: string
      401:
        description: Authentication required
      403:
        description: Permission denied
      500:
        description: Server error
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            message:
              type: string
    """
    try:
        # Handle case where get_json() might raise an exception for empty body
        try:
            data = request.get_json()
        except Exception:
            data = None
            
        if data is None or "value" not in data:
            return jsonify({"success": False, "message": "Value is required"}), 400

        # Validate setting key and value against schema
        is_valid, error_message = validate_setting(key, data["value"])
        if not is_valid:
            return jsonify({"success": False, "message": error_message}), 400

        user_id = g.user.id
        
        # Additional validation for default_board: verify board exists and user owns it
        if key == "default_board" and data["value"] is not None:
            db_check = SessionLocal()
            try:
                board_exists = (
                    get_user_scoped_query(db_check, Board, user_id).filter(Board.id == data["value"]).first()
                )
                if not board_exists:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "message": f"Board with ID {data['value']} does not exist or you don't have access",
                            }
                        ),
                        400,
                    )
            finally:
                db_check.close()

        # Convert value to JSON string
        value = json.dumps(data["value"])

        db = SessionLocal()
        try:
            # Query user-specific setting
            setting = db.query(Setting).filter(Setting.key == key, Setting.user_id == user_id).first()

            if setting:
                # Update existing user setting
                setting.value = value
                message = "Setting updated successfully"
            else:
                # Create new user-specific setting
                setting = Setting(key=key, value=value, user_id=user_id)
                db.add(setting)
                message = "Setting created successfully"

            db.commit()
            db.refresh(setting)

            # Parse back for response
            try:
                parsed_value = json.loads(value)
            except json.JSONDecodeError:
                parsed_value = value

            return jsonify(
                {"success": True, "message": message, "key": key, "value": parsed_value}
            )
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error setting setting: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500


@settings_bp.route("/api/settings/backup/config", methods=["GET"])
@require_permission('setting.view')
def get_backup_config():
    """Get all backup configuration settings.
    ---
    tags:
      - Settings
    responses:
      200:
        description: Backup configuration retrieved successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            config:
              type: object
              properties:
                enabled:
                  type: boolean
                frequency_value:
                  type: integer
                frequency_unit:
                  type: string
                start_time:
                  type: string
                retention_count:
                  type: integer
                last_run:
                  type: string
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        keys = [
            "backup_enabled",
            "backup_frequency_value",
            "backup_frequency_unit",
            "backup_start_time",
            "backup_retention_count",
            "backup_minimum_free_space_mb",
            "backup_last_run"
        ]
        
        config = {}
        # Backup settings are global (user_id = NULL)
        for key in keys:
            setting = db.query(Setting).filter(Setting.key == key, Setting.user_id.is_(None)).first()
            if setting:
                # Try to parse JSON, otherwise use raw value
                try:
                    config[key.replace("backup_", "")] = json.loads(setting.value)
                except (json.JSONDecodeError, TypeError):
                    config[key.replace("backup_", "")] = setting.value
            else:
                # No default - return None if setting doesn't exist
                config[key.replace("backup_", "")] = None
        
        return jsonify({"success": True, "config": config})
    except Exception as e:
        logger.error(f"Error getting backup config: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        db.close()


@settings_bp.route("/api/settings/backup/config", methods=["PUT"])
@require_permission('setting.edit')
def update_backup_config():
    """Update backup configuration settings.
    ---
    tags:
      - Settings
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            enabled:
              type: boolean
              example: true
            frequency_value:
              type: integer
              example: 1
              minimum: 1
              maximum: 99
            frequency_unit:
              type: string
              example: "daily"
              enum: ["minutes", "hours", "daily"]
            start_time:
              type: string
              example: "02:00"
              pattern: "^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$"
            retention_count:
              type: integer
              example: 7
              minimum: 1
              maximum: 100
    responses:
      200:
        description: Backup configuration updated successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            message:
              type: string
      400:
        description: Invalid input
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            message:
              type: string
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        data = request.get_json(silent=True)
        if data is None:
            return jsonify({"success": False, "message": "Request body is required"}), 400
        
        # Allow empty body - just return success without updating anything
        if not data:
            return jsonify({"success": True, "message": "No settings to update"})
        
        # Map frontend field names to setting keys
        mapping = {
            "enabled": "backup_enabled",
            "frequency_value": "backup_frequency_value",
            "frequency_unit": "backup_frequency_unit",
            "start_time": "backup_start_time",
            "retention_count": "backup_retention_count",
            "minimum_free_space_mb": "backup_minimum_free_space_mb"
        }
        
        # Validate all provided fields using the settings schema
        errors = []
        for field, key in mapping.items():
            if field in data:
                is_valid, error_msg = validate_setting(key, data[field])
                if not is_valid:
                    errors.append(error_msg)
        
        # Additional validation: If frequency_unit is "daily", frequency_value must be 1
        if "frequency_unit" in data and data.get("frequency_unit") == "daily":
            freq_value = data.get("frequency_value")
            # If frequency_value not in request, check the existing database value
            if freq_value is None:
                # Backup settings are global (user_id = NULL)
                setting = db.query(Setting).filter(Setting.key == "backup_frequency_value", Setting.user_id.is_(None)).first()
                if setting:
                    try:
                        freq_value = json.loads(setting.value)
                    except (json.JSONDecodeError, TypeError):
                        freq_value = None
            
            # Now validate that frequency_value is 1 if daily
            if freq_value is not None and freq_value != 1:
                errors.append("Daily backups must have frequency_value of 1 (not configurable)")
        
        if errors:
            return jsonify({"success": False, "message": "; ".join(errors)}), 400
        
        # Additional validation: Cannot enable backups if required settings are invalid or missing
        if data.get("enabled") is True:
            # Get current settings for fields not being updated
            current_settings = {}
            for field, key in mapping.items():
                if field not in data:
                    # Backup settings are global (user_id = NULL)
                    setting = db.query(Setting).filter(Setting.key == key, Setting.user_id.is_(None)).first()
                    if setting:
                        try:
                            current_settings[field] = json.loads(setting.value)
                        except (json.JSONDecodeError, TypeError):
                            current_settings[field] = None
                    else:
                        current_settings[field] = None
            
            # Merge with new data
            final_settings = {**current_settings, **data}
            
            # Validate all required settings are present and valid
            required_errors = []
            for field in ["frequency_value", "frequency_unit", "start_time", "retention_count", "minimum_free_space_mb"]:
                key = mapping[field]
                value = final_settings.get(field)
                if value is None:
                    required_errors.append(f"{field} must be set before enabling backups")
                else:
                    is_valid, error_msg = validate_setting(key, value)
                    if not is_valid:
                        required_errors.append(error_msg)
            
            # Additional validation: If frequency_unit is daily, frequency_value must be 1
            if final_settings.get("frequency_unit") == "daily" and final_settings.get("frequency_value") != 1:
                required_errors.append("Daily backups require frequency_value of 1")
            
            if required_errors:
                return jsonify({
                    "success": False,
                    "message": "Cannot enable backups with invalid settings: " + "; ".join(required_errors)
                }), 400
        
        # Update global backup settings (user_id = NULL)
        for field, key in mapping.items():
            if field in data:
                value = json.dumps(data[field])
                setting = db.query(Setting).filter(Setting.key == key, Setting.user_id.is_(None)).first()
                
                if setting:
                    setting.value = value
                else:
                    # Create as global setting (user_id = NULL)
                    setting = Setting(key=key, value=value, user_id=None)
                    db.add(setting)
        
        db.commit()
        
        return jsonify({"success": True, "message": "Backup configuration updated successfully"})
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating backup config: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        db.close()


@settings_bp.route("/api/settings/backup/status", methods=["GET"])
@require_permission('setting.view')
def get_backup_status():
    """Get backup scheduler status.
    ---
    tags:
      - Settings
    responses:
      200:
        description: Backup scheduler status
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            status:
              type: object
    """
    try:
        from backup_scheduler import get_scheduler
        scheduler = get_scheduler()
        
        # Attempt to restart scheduler if it failed due to permissions that were fixed
        scheduler.retry_start_if_permission_fixed()
        
        status = scheduler.get_status()
        return jsonify({"success": True, "status": status})
    except Exception as e:
        logger.error(f"Error getting backup status: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500


@settings_bp.route("/api/settings/housekeeping/status", methods=["GET"])
@require_permission('setting.view')
def get_housekeeping_status():
    """Get housekeeping scheduler status.
    ---
    tags:
      - Settings
    responses:
      200:
        description: Housekeeping scheduler status
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            status:
              type: object
    """
    try:
        # Get APP_VERSION from the app module
        from flask import current_app
        APP_VERSION = current_app.config.get('APP_VERSION', '2026.3.3')
        
        from housekeeping_scheduler import get_housekeeping_scheduler
        scheduler = get_housekeeping_scheduler(APP_VERSION)
        status = scheduler.get_status()
        return jsonify({"success": True, "status": status})
    except Exception as e:
        logger.error(f"Error getting housekeeping status: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500


@settings_bp.route("/api/settings/housekeeping/config", methods=["PUT"])
@require_permission('setting.edit')
def update_housekeeping_config():
    """Update housekeeping scheduler configuration.
    ---
    tags:
      - Settings
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            enabled:
              type: boolean
    responses:
      200:
        description: Configuration updated successfully
      400:
        description: Bad request
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        data = request.get_json(silent=True)
        if data is None or "enabled" not in data:
            return jsonify({"success": False, "message": "enabled field is required"}), 400
        
        enabled = data["enabled"]
        if not isinstance(enabled, bool):
            return jsonify({"success": False, "message": "enabled must be a boolean"}), 400
        
        # Update global housekeeping setting (user_id = NULL)
        setting = db.query(Setting).filter(Setting.key == "housekeeping_enabled", Setting.user_id.is_(None)).first()
        value = json.dumps(enabled)
        
        if setting:
            setting.value = value
        else:
            # Create as global setting (user_id = NULL)
            setting = Setting(key="housekeeping_enabled", value=value, user_id=None)
            db.add(setting)
        
        db.commit()
        
        return jsonify({"success": True, "message": "Housekeeping configuration updated successfully"})
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating housekeeping config: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        db.close()


@settings_bp.route("/api/settings/card-scheduler/status", methods=["GET"])
@require_permission('setting.view')
def get_card_scheduler_status():
    """Get card scheduler status.
    ---
    tags:
      - Settings
    responses:
      200:
        description: Card scheduler status
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            status:
              type: object
    """
    try:
        from card_scheduler import get_scheduler as get_card_scheduler
        scheduler = get_card_scheduler()
        
        # Get global card scheduler enabled setting (user_id = NULL)
        db = SessionLocal()
        try:
            setting = db.query(Setting).filter(Setting.key == "card_scheduler_enabled", Setting.user_id.is_(None)).first()
            if setting is not None and setting.value is not None:
                enabled = json.loads(str(setting.value))
            else:
                enabled = True  # Default to enabled
        finally:
            db.close()
        
        status = {
            "running": scheduler.running,
            "enabled": enabled
        }
        
        return jsonify({"success": True, "status": status})
    except Exception as e:
        logger.error(f"Error getting card scheduler status: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500


@settings_bp.route("/api/settings/card-scheduler/config", methods=["PUT"])
@require_permission('setting.edit')
def update_card_scheduler_config():
    """Update card scheduler configuration.
    ---
    tags:
      - Settings
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            enabled:
              type: boolean
    responses:
      200:
        description: Configuration updated successfully
      400:
        description: Bad request
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        data = request.get_json(silent=True)
        if data is None or "enabled" not in data:
            return jsonify({"success": False, "message": "enabled field is required"}), 400
        
        enabled = data["enabled"]
        if not isinstance(enabled, bool):
            return jsonify({"success": False, "message": "enabled must be a boolean"}), 400
        
        # Update global card scheduler setting (user_id = NULL)
        setting = db.query(Setting).filter(Setting.key == "card_scheduler_enabled", Setting.user_id.is_(None)).first()
        value = json.dumps(enabled)
        
        if setting:
            setting.value = value
            db.commit()
            return jsonify({"success": True, "message": "Card scheduler configuration updated successfully"})

        # Create as global setting (user_id = NULL). Handle duplicate-key races by retrying as update.
        setting = Setting(key="card_scheduler_enabled", value=value, user_id=None)
        db.add(setting)
        try:
            db.commit()
            return jsonify({"success": True, "message": "Card scheduler configuration updated successfully"})
        except IntegrityError:
            db.rollback()
            existing_setting = db.query(Setting).filter(Setting.key == "card_scheduler_enabled", Setting.user_id.is_(None)).first()
            if not existing_setting:
                raise
            existing_setting.value = value
            db.commit()
            return jsonify({"success": True, "message": "Card scheduler configuration updated successfully"})
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating card scheduler config: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        db.close()


@settings_bp.route("/api/boards/<int:board_id>/settings/working-style", methods=["GET"])
@require_board_access()
@require_permission('board.view')
def get_board_working_style_setting(board_id):
    """Get the working style setting for a specific board.
    ---
    tags:
      - Settings
    security:
      - session: []
    parameters:
      - name: board_id
        in: path
        required: true
        type: integer
    responses:
      200:
        description: Working style value and edit permission flag
      403:
        description: Insufficient permissions
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        value = get_board_working_style(db, board_id)
        board_permissions = get_user_permissions(g.user.id, board_id)

        from permissions import has_permission
        can_edit = has_permission(board_permissions, 'board.edit')

        return jsonify(
            {
                "success": True,
                "board_id": board_id,
                "key": "working_style",
                "value": value,
                "can_edit": can_edit,
            }
        ), 200
    except Exception as e:
        logger.error(f"Error getting board working style for board {board_id}: {str(e)}")
        return create_error_response("Failed to get board working style", 500)
    finally:
        db.close()


@settings_bp.route("/api/boards/<int:board_id>/settings/working-style", methods=["PUT"])
@require_board_access()
@require_permission('board.edit')
def set_board_working_style_setting(board_id):
    """Set the working style setting for a specific board.
    ---
    tags:
      - Settings
    security:
      - session: []
    parameters:
      - name: board_id
        in: path
        required: true
        type: integer
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - value
          properties:
            value:
              type: string
              enum: [kanban, agile]
    responses:
      200:
        description: Working style updated
      400:
        description: Invalid value
      403:
        description: Insufficient permissions
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        data = request.get_json(silent=True)
        if data is None or "value" not in data:
            return create_error_response("value is required", 400)

        working_style = normalize_working_style(data.get("value"))
        if working_style not in WORKING_STYLE_ALLOWED_VALUES:
            return create_error_response(
                f"Invalid working_style. Must be one of: {', '.join(WORKING_STYLE_ALLOWED_VALUES)}",
                400,
            )

        setting = db.query(BoardSetting).filter(
            BoardSetting.board_id == board_id,
            BoardSetting.key == 'working_style'
        ).first()

        value = json.dumps(working_style)
        if setting:
            setting.value = value
            message = "Board working style updated"
        else:
            db.add(
                BoardSetting(
                    board_id=board_id,
                    key='working_style',
                    value=value,
                )
            )
            message = "Board working style created"

        db.commit()

        return jsonify(
            {
                "success": True,
                "message": message,
                "board_id": board_id,
                "key": "working_style",
                "value": working_style,
            }
        ), 200
    except Exception as e:
        db.rollback()
        logger.error(f"Error setting board working style for board {board_id}: {str(e)}")
        return create_error_response("Failed to set board working style", 500)
    finally:
        db.close()


@settings_bp.route("/api/settings/working-style", methods=["GET"])
@require_permission('setting.view')
def get_working_style():
    """Get the current user's default working style preference.
    ---
    tags:
      - Settings
    security:
      - session: []
    responses:
      200:
        description: Working style value (kanban or agile)
      403:
        description: Insufficient permissions
      500:
        description: Server error
    """
    session = SessionLocal()
    try:
        user_id = g.user.id
        
        value = get_user_default_working_style(session, user_id)
        
        return jsonify({
            "success": True,
            "value": value
        }), 200
    except Exception as e:
        logger.error(f"Error getting working style: {str(e)}")
        return create_error_response(f"Error getting working style: {str(e)}", 500)
    finally:
        session.close()


@settings_bp.route("/api/settings/working-style", methods=["PUT"])
@require_permission('setting.edit')
def set_working_style():
    """Set the current user's default working style preference.
    ---
    tags:
      - Settings
    security:
      - session: []
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - value
          properties:
            value:
              type: string
              enum: [kanban, agile]
    responses:
      200:
        description: Working style updated
      400:
        description: Missing or invalid value
      403:
        description: Insufficient permissions
      500:
        description: Server error
    """
    session = SessionLocal()
    try:
        user_id = g.user.id
        data = request.get_json()
        
        if not data or "value" not in data:
            return create_error_response("value is required", 400)
        
        working_style = normalize_working_style(data.get("value"))
        
        # Validate working_style value
        if working_style not in WORKING_STYLE_ALLOWED_VALUES:
            return create_error_response(
            f"Invalid working_style. Must be one of: {', '.join(WORKING_STYLE_ALLOWED_VALUES)}",
                400
            )
        
        # Update or create user's working_style setting
        setting = session.query(Setting).filter(Setting.key == 'working_style', Setting.user_id == user_id).first()

        if setting:
            setting.value = json.dumps(working_style)
        else:
            setting = Setting(
                key='working_style',
              value=json.dumps(working_style),
                user_id=user_id
            )
            session.add(setting)
        
        session.commit()
        
        return jsonify({
            "success": True,
            "message": "Working style updated",
            "value": working_style
        }), 200
    except Exception as e:
        session.rollback()
        logger.error(f"Error setting working style: {str(e)}")
        return create_error_response(f"Error setting working style: {str(e)}", 500)
    finally:
        session.close()


@settings_bp.route("/api/settings/timezone", methods=["GET"])
@require_permission('setting.view')
def get_timezone_setting():
    """Get the current user's timezone preference.
    ---
    tags:
      - Settings
    security:
      - session: []
    responses:
      200:
        description: IANA timezone string (defaults to UTC when unset)
      403:
        description: Insufficient permissions
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        user_id = g.user.id
        setting = db.query(Setting).filter(Setting.key == 'timezone', Setting.user_id == user_id).first()

        timezone_value = "UTC"
        if setting and setting.value is not None:
            try:
                parsed_value = json.loads(setting.value)
            except (TypeError, json.JSONDecodeError):
                parsed_value = setting.value

            is_valid, _ = validate_setting('timezone', parsed_value)
            if is_valid:
                timezone_value = parsed_value

        return jsonify({
            "success": True,
            "key": "timezone",
            "value": timezone_value,
        }), 200
    except Exception as e:
        logger.error(f"Error getting timezone setting: {str(e)}")
        return create_error_response("Failed to get timezone setting", 500)
    finally:
        db.close()


@settings_bp.route("/api/settings/timezone", methods=["PUT"])
@require_permission('setting.edit')
def set_timezone_setting():
    """Set the current user's timezone preference.
    ---
    tags:
      - Settings
    security:
      - session: []
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - value
          properties:
            value:
              type: string
              description: Valid IANA timezone string e.g. 'Europe/London'
    responses:
      200:
        description: Timezone updated
      400:
        description: Missing or invalid timezone value
      403:
        description: Insufficient permissions
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        data = request.get_json(silent=True)
        if data is None or "value" not in data:
            return create_error_response("value is required", 400)

        timezone_value = data.get("value")
        is_valid, error = validate_setting('timezone', timezone_value)
        if not is_valid:
            return create_error_response(error, 400)

        user_id = g.user.id
        setting = db.query(Setting).filter(Setting.key == 'timezone', Setting.user_id == user_id).first()

        value_json = json.dumps(timezone_value)
        if setting:
            setting.value = value_json
            message = "Timezone updated"
        else:
            db.add(Setting(key='timezone', value=value_json, user_id=user_id))
            message = "Timezone created"

        db.commit()

        return jsonify({
            "success": True,
            "message": message,
            "key": "timezone",
            "value": timezone_value,
        }), 200
    except Exception as e:
        db.rollback()
        logger.error(f"Error setting timezone setting: {str(e)}")
        return create_error_response("Failed to set timezone setting", 500)
    finally:
        db.close()


def configure_settings_routes(app, APP_VERSION):
    """Configure the settings routes by storing APP_VERSION for use by settings routes.
    
    Args:
        app: Flask application instance
        APP_VERSION: Application version string for housekeeping scheduler
    """
    # Store APP_VERSION in app config for use by settings routes
    app.config['APP_VERSION'] = APP_VERSION
