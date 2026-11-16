"""Stop board editors deleting boards.

Board owners can now share their boards themselves (#285). Sharing as Editor
gives the board_editor role, which should let people edit the board but not
delete it. Only the owner and administrators can delete a board. People who
need more can be given a custom board role by an administrator.

Revision ID: 040
Revises: 039
Create Date: 2026-11-16

"""
import json

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '040'
down_revision = '039'
branch_labels = None
depends_on = None

ROLE_NAME = 'board_editor'
PERMISSION = 'board.delete'
OLD_DESCRIPTION = (
    '[BOARD-SPECIFIC] Full control of the assigned board - can manage everything on it'
)
NEW_DESCRIPTION = (
    '[BOARD-SPECIFIC] Edit the assigned board - everything except deleting it, '
    'sharing it or changing its owner'
)


def _sync_board_editor(remove_delete=True):
    """Remove or restore board.delete on board_editor, and its description."""
    bind = op.get_bind()
    row = bind.execute(
        sa.text("SELECT id, permissions FROM roles WHERE name = :name LIMIT 1"),
        {"name": ROLE_NAME}
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

    if remove_delete:
        permissions = [perm for perm in permissions if perm != PERMISSION]
        description = NEW_DESCRIPTION
    else:
        if PERMISSION not in permissions:
            permissions.append(PERMISSION)
        description = OLD_DESCRIPTION

    bind.execute(
        sa.text(
            "UPDATE roles SET permissions = :permissions, description = :description "
            "WHERE id = :id"
        ),
        {"permissions": json.dumps(permissions), "description": description, "id": row[0]}
    )


def upgrade():
    """Remove board.delete from board_editor."""
    _sync_board_editor(remove_delete=True)


def downgrade():
    """Give board_editor board.delete again."""
    _sync_board_editor(remove_delete=False)
