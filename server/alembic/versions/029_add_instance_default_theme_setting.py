"""Add instance default theme setting.

Revision ID: 029
Revises: 028
Create Date: 2026-05-30

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '029'
down_revision = '028'
branch_labels = None
depends_on = None


DEFAULT_THEME_NAME = 'Fresh Green'
DEFAULT_THEME_SETTING_KEY = 'default_theme'


def upgrade():
    conn = op.get_bind()

    row = conn.execute(sa.text("""
        SELECT id
        FROM themes
        WHERE name = :name
          AND system_theme = 1
          AND user_id IS NULL
        LIMIT 1
    """), {'name': DEFAULT_THEME_NAME}).fetchone()

    if row is None:
        return

    theme_id = str(row[0])

    existing = conn.execute(sa.text("""
        SELECT id
        FROM settings
        WHERE `key` = :key
          AND user_id IS NULL
        LIMIT 1
    """), {'key': DEFAULT_THEME_SETTING_KEY}).fetchone()

    if existing is None:
        conn.execute(sa.text("""
            INSERT INTO settings (`key`, `value`, user_id)
            VALUES (:key, :value, NULL)
        """), {'key': DEFAULT_THEME_SETTING_KEY, 'value': theme_id})
    else:
        conn.execute(sa.text("""
            UPDATE settings
            SET `value` = :value
            WHERE id = :id
        """), {'value': theme_id, 'id': existing[0]})


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text("""
        DELETE FROM settings
        WHERE `key` = :key
          AND user_id IS NULL
    """), {'key': DEFAULT_THEME_SETTING_KEY})
