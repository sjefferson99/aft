"""Instance policy for HTTP Basic auth (#716).

Basic auth sends a password with every request and skips anything that only
guards the sign-in form, so an instance can turn it off or keep it for
API-only accounts. The mode is a global row in the settings table.
"""

import json
import logging

from sqlalchemy.exc import IntegrityError

from models import Setting

logger = logging.getLogger(__name__)

BASIC_AUTH_SETTING_KEY = "basic_auth"
BASIC_AUTH_ALL = "all"
BASIC_AUTH_API_ONLY_USERS = "api_only_users"
BASIC_AUTH_OFF = "off"
BASIC_AUTH_MODES = (BASIC_AUTH_ALL, BASIC_AUTH_API_ONLY_USERS, BASIC_AUTH_OFF)
# Existing installs keep working until an administrator chooses otherwise.
BASIC_AUTH_DEFAULT = BASIC_AUTH_ALL


def _global_setting(db):
    return db.query(Setting).filter(
        Setting.key == BASIC_AUTH_SETTING_KEY,
        Setting.user_id.is_(None),
    ).first()


def get_basic_auth_mode(db):
    """Return the instance's Basic auth mode, falling back to the default."""
    setting = _global_setting(db)
    if setting is None or setting.value is None:
        return BASIC_AUTH_DEFAULT
    try:
        mode = json.loads(str(setting.value))
    except (TypeError, ValueError):
        mode = None
    if mode not in BASIC_AUTH_MODES:
        logger.warning("Ignoring invalid basic_auth setting; using the default")
        return BASIC_AUTH_DEFAULT
    return mode


def set_basic_auth_mode(db, mode):
    """Store the instance's Basic auth mode. The caller validates the mode."""
    value = json.dumps(mode)
    setting = _global_setting(db)
    if setting is not None:
        setting.value = value
        db.commit()
        return
    db.add(Setting(key=BASIC_AUTH_SETTING_KEY, value=value, user_id=None))
    try:
        db.commit()
    except IntegrityError:
        # Another request created the row first.
        db.rollback()
        setting = _global_setting(db)
        if setting is None:
            raise
        setting.value = value
        db.commit()


def basic_auth_allowed_for(mode, user):
    """Whether this mode lets the user sign a request with Basic auth.

    Decided before the password is checked, so refused accounts can't use
    Basic auth to guess passwords. A missing user is allowed through here
    so unknown names still take the normal failed-password path.
    """
    if mode == BASIC_AUTH_OFF:
        return False
    if mode == BASIC_AUTH_API_ONLY_USERS:
        return user is None or bool(user.api_only)
    return True
