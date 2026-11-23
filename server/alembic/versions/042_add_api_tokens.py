"""Add personal API tokens.

Scripts and agents send these as `Authorization: Bearer <token>` instead of a
password (#714). Only a SHA-256 of each token is stored.

Revision ID: 042
Revises: 041
Create Date: 2026-11-23

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '042'
down_revision = '041'
branch_labels = None
depends_on = None


def upgrade():
    """Create api_tokens."""
    op.create_table(
        'api_tokens',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('token_hash', sa.String(length=64, collation='ascii_bin'), nullable=False),
        sa.Column('token_prefix', sa.String(length=16), nullable=False),
        sa.Column('read_only', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.current_timestamp()),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash', name='uq_api_tokens_token_hash'),
    )
    op.create_index(op.f('ix_api_tokens_id'), 'api_tokens', ['id'])
    op.create_index(op.f('ix_api_tokens_user_id'), 'api_tokens', ['user_id'])


def downgrade():
    """Drop api_tokens."""
    op.drop_index(op.f('ix_api_tokens_user_id'), table_name='api_tokens')
    op.drop_index(op.f('ix_api_tokens_id'), table_name='api_tokens')
    op.drop_table('api_tokens')
