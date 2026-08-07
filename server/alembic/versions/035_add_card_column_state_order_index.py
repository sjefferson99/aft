"""Add composite index for the board card query.

get_board_cards (card_routes.py) and the public/scheduled board views filter
cards by column_id + archived + scheduled and order by `order`. Each column
had separate single-column indexes on these (see models.py) but no
composite, so the query planner picks one index and filters/sorts the rest
in memory. Matters more as boards grow past ~100 cards per column.

Revision ID: 035
Revises: 034
Create Date: 2026-08-07

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '035'
down_revision = '034'
branch_labels = None
depends_on = None


def upgrade():
    """Add composite index on cards(column_id, archived, scheduled, order)."""
    op.execute(
        "CREATE INDEX idx_card_column_state_order "
        "ON cards (column_id, archived, scheduled, `order`)"
    )


def downgrade():
    """Drop the composite card query index."""
    op.execute("DROP INDEX idx_card_column_state_order ON cards")
