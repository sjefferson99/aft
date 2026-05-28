"""Add public visibility fields to boards.

Revision ID: 027
Revises: 026
Create Date: 2026-05-21

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '027'
down_revision = '026'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('boards') as batch_op:
        batch_op.add_column(
            sa.Column('is_public', sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(sa.Column('public_slug', sa.String(length=64), nullable=True))
        batch_op.create_unique_constraint('uq_boards_public_slug', ['public_slug'])


def downgrade():
    with op.batch_alter_table('boards') as batch_op:
        batch_op.drop_constraint('uq_boards_public_slug', type_='unique')
        batch_op.drop_column('public_slug')
        batch_op.drop_column('is_public')
