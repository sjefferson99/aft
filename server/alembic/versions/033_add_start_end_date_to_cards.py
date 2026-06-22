"""Add start_date and end_date to cards.

Revision ID: 033
Revises: 032
Create Date: 2026-06-20

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '033'
down_revision = '032'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('cards') as batch_op:
        batch_op.add_column(sa.Column('start_date', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('end_date', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('cards') as batch_op:
        batch_op.drop_column('end_date')
        batch_op.drop_column('start_date')
