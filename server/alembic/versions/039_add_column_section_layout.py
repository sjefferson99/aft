"""Add section layout positions to columns.

Boards in the sections layout (#297) show columns as sections stacked in
lanes. Each column keeps its own lane and position there, separate from its
column order, so switching layouts never reorders the columns. Both stay null
until the layout is first arranged, and null sections are placed
automatically.

Revision ID: 039
Revises: 038
Create Date: 2026-11-12

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '039'
down_revision = '038'
branch_labels = None
depends_on = None


def upgrade():
    """Add columns.section_lane and columns.section_order."""
    op.add_column('columns', sa.Column('section_lane', sa.Integer(), nullable=True))
    op.add_column('columns', sa.Column('section_order', sa.Integer(), nullable=True))


def downgrade():
    """Remove columns.section_lane and columns.section_order."""
    op.drop_column('columns', 'section_order')
    op.drop_column('columns', 'section_lane')
