"""Add instance config table.

Revision ID: 028
Revises: 027
Create Date: 2026-05-28

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '028'
down_revision = '027'
branch_labels = None
depends_on = None


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


def downgrade():
    op.drop_index(op.f('ix_instance_config_key'), table_name='instance_config')
    op.drop_index(op.f('ix_instance_config_id'), table_name='instance_config')
    op.drop_table('instance_config')
