"""Add mobile/desktop app install notification.

Revision ID: 034
Revises: 033
Create Date: 2026-08-05

"""
from alembic import op
from sqlalchemy import text as sa_text


# revision identifiers, used by Alembic.
revision = '034'
down_revision = '033'
branch_labels = None
depends_on = None

SUBJECT = 'Install AFT as an app'

MESSAGE = (
    "AFT can be installed as an app on your phone, tablet, Mac or PC for a "
    "full-screen, home-screen experience with no browser address bar. "
    "Mac/PC (Chrome or Edge): open AFT, then click the install icon in the "
    "address bar, or the browser menu > Install AFT. "
    "Android (Chrome): open AFT, tap the menu (three dots) > Install app, "
    "or use the Install App button in AFT Settings. "
    "iPhone/iPad (Safari): open AFT, tap the Share icon, then Add to Home "
    "Screen. See AFT Settings for step-by-step help."
)

ACTION_TITLE = 'Open Settings'
ACTION_URL = '/settings.html'


def upgrade():
    """Notify all active, approved users about the installable app."""
    conn = op.get_bind()
    conn.execute(
        sa_text("""
            INSERT INTO notifications (subject, message, unread, created_at, action_title, action_url, user_id)
            SELECT :subject, :message, 1, NOW(), :action_title, :action_url, u.id
            FROM users u
            WHERE u.is_active = 1
              AND u.is_approved = 1
              AND NOT EXISTS (
                  SELECT 1 FROM notifications n
                  WHERE n.user_id = u.id AND n.subject = :subject
              )
        """),
        {
            'subject': SUBJECT,
            'message': MESSAGE,
            'action_title': ACTION_TITLE,
            'action_url': ACTION_URL,
        },
    )


def downgrade():
    """Remove the mobile/desktop app install notification."""
    conn = op.get_bind()
    conn.execute(
        sa_text("DELETE FROM notifications WHERE subject = :subject"),
        {'subject': SUBJECT},
    )
