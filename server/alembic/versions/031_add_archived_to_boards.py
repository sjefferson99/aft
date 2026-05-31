"""Add archived flag to boards.

Revision ID: 031
Revises: 030
Create Date: 2026-05-30

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '031'
down_revision = '030'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('boards') as batch_op:
        batch_op.add_column(sa.Column('archived', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.create_index('ix_boards_archived', ['archived'], unique=False)

    with op.batch_alter_table('boards') as batch_op:
        batch_op.alter_column('archived', server_default=None)


def downgrade():
    with op.batch_alter_table('boards') as batch_op:
        batch_op.drop_index('ix_boards_archived')
        batch_op.drop_column('archived')
