"""Add text-search fulltext indexes.

Revision ID: 032
Revises: 031
Create Date: 2026-05-31

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '032'
down_revision = '031'
branch_labels = None
depends_on = None


def upgrade():
    """Add fulltext indexes used by board text-search phase 2."""
    op.execute(
        "CREATE FULLTEXT INDEX idx_cards_fulltext_title_description "
        "ON cards (title, description)"
    )
    op.execute(
        "CREATE FULLTEXT INDEX idx_checklist_items_fulltext_name "
        "ON checklist_items (name)"
    )


def downgrade():
    """Drop fulltext indexes added for board text-search."""
    op.execute("DROP INDEX idx_cards_fulltext_title_description ON cards")
    op.execute("DROP INDEX idx_checklist_items_fulltext_name ON checklist_items")
