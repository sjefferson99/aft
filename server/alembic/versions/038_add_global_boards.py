"""Add global boards and promoted cards.

A global board shows cards promoted from agile boards by state. The MVP has one
instance-wide global board, seeded here.

Revision ID: 038
Revises: 037
Create Date: 2026-11-04

"""
import json

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '038'
down_revision = '037'
branch_labels = None
depends_on = None

MANAGE_PERMISSION = 'global_board.manage'


def _sync_manage_permission_on_administrator(add_permission=True):
    """Add or remove global_board.manage on the administrator role."""
    bind = op.get_bind()
    row = bind.execute(
        sa.text("SELECT id, permissions FROM roles WHERE name = :name LIMIT 1"),
        {"name": "administrator"}
    ).fetchone()

    if not row:
        return

    try:
        permissions = json.loads(row[1]) if row[1] else []
    except Exception:
        # Leave a malformed permissions payload untouched.
        return

    if not isinstance(permissions, list):
        return

    if add_permission and MANAGE_PERMISSION not in permissions:
        permissions.append(MANAGE_PERMISSION)
    elif not add_permission and MANAGE_PERMISSION in permissions:
        permissions = [perm for perm in permissions if perm != MANAGE_PERMISSION]
    else:
        return

    bind.execute(
        sa.text("UPDATE roles SET permissions = :permissions WHERE id = :id"),
        {"permissions": json.dumps(permissions), "id": row[0]}
    )


def upgrade():
    """Create global_boards and global_board_cards, and seed the instance board."""
    global_boards = op.create_table(
        'global_boards',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('visibility', sa.String(length=20), nullable=False, server_default='everyone'),
        sa.Column('owner_id', sa.Integer(), nullable=True),
        sa.Column('done_visible_days', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.current_timestamp()),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_global_boards_id'), 'global_boards', ['id'])
    op.create_index(op.f('ix_global_boards_owner_id'), 'global_boards', ['owner_id'])

    op.create_table(
        'global_board_cards',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('global_board_id', sa.Integer(), nullable=False),
        sa.Column('card_id', sa.Integer(), nullable=False),
        sa.Column('state', sa.String(length=20), nullable=False, server_default='new'),
        sa.Column('order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('promoted_by_id', sa.Integer(), nullable=True),
        sa.Column('promoted_at', sa.DateTime(), server_default=sa.func.current_timestamp()),
        sa.ForeignKeyConstraint(['global_board_id'], ['global_boards.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['card_id'], ['cards.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['promoted_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('card_id', name='uq_global_board_cards_card_id'),
    )
    op.create_index(op.f('ix_global_board_cards_id'), 'global_board_cards', ['id'])
    op.create_index(
        op.f('ix_global_board_cards_promoted_by_id'), 'global_board_cards', ['promoted_by_id']
    )
    # Lists filter by global board and sort by state and order.
    op.create_index(
        'idx_global_board_cards_board_state_order',
        'global_board_cards',
        ['global_board_id', 'state', 'order'],
    )

    op.bulk_insert(global_boards, [{
        'name': 'Global',
        'visibility': 'everyone',
        'owner_id': None,
        'done_visible_days': 14,
    }])

    _sync_manage_permission_on_administrator(add_permission=True)


def downgrade():
    """Drop the global board tables and the manage permission."""
    _sync_manage_permission_on_administrator(add_permission=False)
    op.drop_index('idx_global_board_cards_board_state_order', table_name='global_board_cards')
    op.drop_index(op.f('ix_global_board_cards_promoted_by_id'), table_name='global_board_cards')
    op.drop_index(op.f('ix_global_board_cards_id'), table_name='global_board_cards')
    op.drop_table('global_board_cards')
    op.drop_index(op.f('ix_global_boards_owner_id'), table_name='global_boards')
    op.drop_index(op.f('ix_global_boards_id'), table_name='global_boards')
    op.drop_table('global_boards')
