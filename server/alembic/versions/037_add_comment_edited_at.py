"""Add edited_at to comments.

Revision ID: 037
Revises: 036
Create Date: 2026-10-31

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '037'
down_revision = '036'
branch_labels = None
depends_on = None


def upgrade():
    """Add comments.edited_at, which stays null until a comment is edited."""
    op.add_column('comments', sa.Column('edited_at', sa.DateTime(), nullable=True))


def downgrade():
    """Remove comments.edited_at."""
    op.drop_column('comments', 'edited_at')
