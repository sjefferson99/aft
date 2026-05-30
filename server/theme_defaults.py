"""Helpers for resolving and storing the instance default theme."""

from models import Setting, Theme


DEFAULT_INSTANCE_THEME_NAME = "Fresh Green"
DEFAULT_THEME_SETTING_KEY = "default_theme"


def _get_instance_default_theme_settings(session):
    """Return all global default-theme settings in a deterministic order."""
    return session.query(Setting).filter(
        Setting.key == DEFAULT_THEME_SETTING_KEY,
        Setting.user_id.is_(None),
    ).order_by(Setting.id.desc()).all()


def _parse_positive_int(value):
    try:
        parsed = int(value)
        return parsed if parsed > 0 else None
    except (TypeError, ValueError):
        return None


def get_fresh_green_theme(session):
    """Return the canonical Fresh Green system theme if it exists."""
    return session.query(Theme).filter(
        Theme.name == DEFAULT_INSTANCE_THEME_NAME,
        Theme.system_theme.is_(True),
        Theme.user_id.is_(None),
    ).first()


def get_instance_default_theme(session):
    """Resolve the instance default theme from settings with hard fallback."""
    for setting in _get_instance_default_theme_settings(session):
        theme_id = _parse_positive_int(setting.value)
        if theme_id is not None:
            selected = session.query(Theme).filter(
                Theme.id == theme_id,
                (Theme.system_theme.is_(True) | Theme.global_theme.is_(True)),
            ).first()
            if selected:
                return selected

    return get_fresh_green_theme(session)


def get_instance_default_theme_id(session):
    """Resolve the instance default theme ID with hard fallback."""
    theme = get_instance_default_theme(session)
    return theme.id if theme else None


def upsert_instance_default_theme(session, theme_id):
    """Create or update the global instance default theme setting."""
    settings = session.query(Setting).filter(
        Setting.key == DEFAULT_THEME_SETTING_KEY,
        Setting.user_id.is_(None),
    ).order_by(Setting.id.asc()).all()

    setting = settings[0] if settings else None

    if setting:
        setting.value = str(theme_id)
        for duplicate in settings[1:]:
            session.delete(duplicate)
    else:
        session.add(
            Setting(
                key=DEFAULT_THEME_SETTING_KEY,
                value=str(theme_id),
                user_id=None,
            )
        )
