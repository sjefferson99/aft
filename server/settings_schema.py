"""Shared settings schema and working-style helpers."""

import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from models import BoardSetting, Setting
from utils import get_user_scoped_query


WORKING_STYLE_KANBAN = "kanban"
WORKING_STYLE_AGILE = "agile"
WORKING_STYLE_LEGACY_BOARD_TASK_CATEGORY = "board_task_category"
WORKING_STYLE_ALLOWED_VALUES = [WORKING_STYLE_KANBAN, WORKING_STYLE_AGILE]

CARD_ACTIONS_ALLOWED_VALUES = ["done", "archive", "move", "delete"]
CARD_ACTIONS_MAX_PER_SCREEN = 3


def _validate_time_format(time_str):
    """Validate HH:MM time format."""
    try:
        parts = time_str.split(":")
        if len(parts) != 2:
            return False
        hours_str, minutes_str = parts[0], parts[1]

        if len(minutes_str) != 2:
            return False

        hours, minutes = int(hours_str), int(minutes_str)
        return 0 <= hours <= 23 and 0 <= minutes <= 59
    except (ValueError, AttributeError):
        return False


def _validate_timezone(timezone_name):
    """Validate an IANA timezone name supported by Python zoneinfo."""
    if not isinstance(timezone_name, str):
        return False

    candidate = timezone_name.strip()
    if not candidate:
        return False

    if candidate == "UTC":
        return True

    try:
        ZoneInfo(candidate)
        return True
    except ZoneInfoNotFoundError:
        return False


def _validate_card_actions(value):
    """Validate the card actions chosen for desktop and mobile."""
    if not isinstance(value, dict) or set(value) != {"desktop", "mobile"}:
        return False

    for actions in value.values():
        if not isinstance(actions, list) or len(actions) > CARD_ACTIONS_MAX_PER_SCREEN:
            return False
        if any(not isinstance(action, str) or action not in CARD_ACTIONS_ALLOWED_VALUES for action in actions):
            return False
        if len(set(actions)) != len(actions):
            return False

    return True


SETTINGS_SCHEMA = {
    "default_board": {
        "type": "integer",
        "nullable": True,
        "description": "ID of the board to load by default on application startup",
        "validate": lambda value: value is None
        or (isinstance(value, int) and not isinstance(value, bool) and value > 0),
    },
    "backup_enabled": {
        "type": "boolean",
        "nullable": False,
        "description": "Enable or disable automatic database backups",
        "validate": lambda value: isinstance(value, bool),
    },
    "backup_frequency_value": {
        "type": "integer",
        "nullable": False,
        "description": "Numeric value for backup frequency (1-99)",
        "validate": lambda value: isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 99,
    },
    "backup_frequency_unit": {
        "type": "string",
        "nullable": False,
        "description": "Unit for backup frequency (minutes, hours, daily)",
        "validate": lambda value: isinstance(value, str) and value in ["minutes", "hours", "daily"],
    },
    "backup_start_time": {
        "type": "string",
        "nullable": False,
        "description": "Time when daily backups should run (HH:MM format)",
        "validate": lambda value: isinstance(value, str) and _validate_time_format(value),
    },
    "backup_retention_count": {
        "type": "integer",
        "nullable": False,
        "description": "Number of backup files to retain (1-100)",
        "validate": lambda value: isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 100,
    },
    "backup_minimum_free_space_mb": {
        "type": "integer",
        "nullable": False,
        "description": "Minimum free disk space in MB required before creating a backup (1-10485760)",
        "validate": lambda value: isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 10485760,
    },
    "backup_last_run": {
        "type": "string",
        "nullable": True,
        "description": "ISO timestamp of the last backup run",
        "validate": lambda value: value is None or isinstance(value, str),
    },
    "housekeeping_enabled": {
        "type": "boolean",
        "nullable": False,
        "description": "Enable or disable housekeeping scheduler for version checks",
        "validate": lambda value: isinstance(value, bool),
    },
    "time_format": {
        "type": "string",
        "nullable": False,
        "description": "Time format preference: '12' for 12-hour or '24' for 24-hour",
        "validate": lambda value: isinstance(value, str) and value in ["12", "24"],
    },
    "timezone": {
        "type": "string",
        "nullable": False,
        "description": "IANA timezone name used when rendering UTC timestamps (for example 'UTC' or 'Europe/London')",
        "validate": _validate_timezone,
    },
    "card_actions": {
        "type": "object",
        "nullable": True,
        "description": "Actions shown on board cards: 'desktop' and 'mobile' lists of up to 3 of done, archive, move and delete. Null uses the defaults",
        "validate": _validate_card_actions,
    },
    "touchscreen_mode": {
        "type": "boolean",
        "nullable": False,
        "description": "Use touch gestures and larger controls at any screen width",
        "validate": lambda value: isinstance(value, bool),
    },
    "working_style": {
        "type": "string",
        "nullable": False,
        "description": "Working style preference: 'kanban' for traditional kanban board or 'agile' for board-level done tracking",
        "validate": lambda value: isinstance(value, str) and value in WORKING_STYLE_ALLOWED_VALUES,
    },
}


def validate_setting(key, value):
    """Validate a setting key and value against the schema."""
    if key not in SETTINGS_SCHEMA:
        return (
            False,
            f"Setting '{key}' is not allowed. Allowed settings: {', '.join(SETTINGS_SCHEMA.keys())}",
        )

    schema = SETTINGS_SCHEMA[key]

    if value is None:
        if not schema.get("nullable", False):
            return False, f"Setting '{key}' cannot be null"
        return True, None

    if "validate" in schema and not schema["validate"](value):
        return (
            False,
            f"Invalid value for setting '{key}'. {schema.get('description', '')}",
        )

    return True, None


def normalize_working_style(value):
    """Normalize legacy working style value names to current values."""
    if value == WORKING_STYLE_LEGACY_BOARD_TASK_CATEGORY:
        return WORKING_STYLE_AGILE
    return value


def parse_json_setting_value(raw_value):
    """Parse a JSON-encoded setting value with safe fallback."""
    try:
        return json.loads(raw_value) if raw_value is not None else None
    except (TypeError, json.JSONDecodeError):
        return raw_value


def get_user_default_working_style(db, user_id):
    """Resolve the user's default working style, normalized and validated."""
    setting = get_user_scoped_query(db, Setting, user_id).filter(Setting.key == 'working_style').first()
    if not setting:
        return WORKING_STYLE_KANBAN

    value = normalize_working_style(parse_json_setting_value(setting.value))
    if value not in WORKING_STYLE_ALLOWED_VALUES:
        return WORKING_STYLE_KANBAN
    return value


def get_board_working_style(db, board_id, fallback_user_id=None):
    """Resolve board working style from board-level setting only."""
    board_setting = db.query(BoardSetting).filter(
        BoardSetting.board_id == board_id,
        BoardSetting.key == 'working_style'
    ).first()
    if board_setting:
        value = normalize_working_style(parse_json_setting_value(board_setting.value))
        if value in WORKING_STYLE_ALLOWED_VALUES:
            return value

    return WORKING_STYLE_KANBAN
