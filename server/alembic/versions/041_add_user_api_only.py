"""Add api_only to users.

API-only accounts are for scripts and agents. They can use API
authentication but can't sign in to the web UI (#715).

Revision ID: 041
Revises: 040
Create Date: 2026-11-23

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '041'
down_revision = '040'
branch_labels = None
depends_on = None


def upgrade():
    """Add users.api_only, false for every existing account."""
    op.add_column(
        'users',
        sa.Column('api_only', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    """Remove users.api_only."""
    op.drop_column('users', 'api_only')
