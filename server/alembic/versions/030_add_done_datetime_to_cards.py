"""Add done_datetime to cards.

Revision ID: 030
Revises: 029
Create Date: 2026-05-30

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '030'
down_revision = '029'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('cards') as batch_op:
        batch_op.add_column(sa.Column('done_datetime', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('cards') as batch_op:
        batch_op.drop_column('done_datetime')
