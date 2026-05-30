"""Add instance config table.

Revision ID: 028
Revises: 027
Create Date: 2026-05-28

"""
import json

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '028'
down_revision = '027'
branch_labels = None
depends_on = None


def _sync_branding_permission_on_administrator(add_permission=True):
    """Ensure administrator role permissions include/exclude branding.edit."""
    bind = op.get_bind()
    row = bind.execute(
        sa.text("SELECT id, permissions FROM roles WHERE name = :name LIMIT 1"),
        {"name": "administrator"}
    ).fetchone()

    if not row:
        return

    role_id = row[0]
    raw_permissions = row[1]

    try:
        permissions = json.loads(raw_permissions) if raw_permissions else []
    except Exception:
        # Leave untouched if existing permissions payload is malformed.
        return

    if not isinstance(permissions, list):
        return

    changed = False
    if add_permission and 'branding.edit' not in permissions:
        permissions.append('branding.edit')
        changed = True
    elif not add_permission and 'branding.edit' in permissions:
        permissions = [perm for perm in permissions if perm != 'branding.edit']
        changed = True

    if not changed:
        return

    bind.execute(
        sa.text("UPDATE roles SET permissions = :permissions WHERE id = :id"),
        {"permissions": json.dumps(permissions), "id": role_id}
    )


def upgrade():
    op.create_table(
        'instance_config',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('key', sa.String(length=255), nullable=False),
        sa.Column('value', sa.String(length=1024), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_instance_config_id'), 'instance_config', ['id'], unique=False)
    op.create_index(op.f('ix_instance_config_key'), 'instance_config', ['key'], unique=True)
    _sync_branding_permission_on_administrator(add_permission=True)


def downgrade():
    _sync_branding_permission_on_administrator(add_permission=False)
    op.drop_index(op.f('ix_instance_config_key'), table_name='instance_config')
    op.drop_index(op.f('ix_instance_config_id'), table_name='instance_config')
    op.drop_table('instance_config')
