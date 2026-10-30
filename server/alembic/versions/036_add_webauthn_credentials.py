"""Add passkey (WebAuthn) credentials table and user handle.

Revision ID: 036
Revises: 035
Create Date: 2026-10-30

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '036'
down_revision = '035'
branch_labels = None
depends_on = None


def upgrade():
    """Create webauthn_credentials and add users.webauthn_user_handle."""
    op.add_column(
        'users',
        sa.Column(
            'webauthn_user_handle',
            sa.String(length=100, collation='ascii_bin'),
            nullable=True,
        ),
    )
    op.create_unique_constraint(
        'uq_users_webauthn_user_handle', 'users', ['webauthn_user_handle']
    )

    op.create_table(
        'webauthn_credentials',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('credential_id', sa.String(length=1400, collation='ascii_bin'), nullable=False),
        sa.Column('public_key', sa.Text(), nullable=False),
        sa.Column('sign_count', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('transports', sa.String(length=255), nullable=True),
        sa.Column('aaguid', sa.String(length=36), nullable=True),
        sa.Column('backed_up', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.current_timestamp()),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('credential_id', name='uq_webauthn_credentials_credential_id'),
    )
    op.create_index(op.f('ix_webauthn_credentials_id'), 'webauthn_credentials', ['id'])
    op.create_index(
        op.f('ix_webauthn_credentials_user_id'), 'webauthn_credentials', ['user_id']
    )


def downgrade():
    """Drop webauthn_credentials and users.webauthn_user_handle."""
    op.drop_index(op.f('ix_webauthn_credentials_user_id'), table_name='webauthn_credentials')
    op.drop_index(op.f('ix_webauthn_credentials_id'), table_name='webauthn_credentials')
    op.drop_table('webauthn_credentials')
    op.drop_constraint('uq_users_webauthn_user_handle', 'users', type_='unique')
    op.drop_column('users', 'webauthn_user_handle')
