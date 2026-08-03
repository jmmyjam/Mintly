"""email verification + token_version

Revision ID: a7d2f5c9b3e1
Revises: f1a2b3c4d5e6
Create Date: 2026-08-03

Adds:
- users.email_verified_at (nullable) — NULL = unverified. Existing accounts are
  grandfathered as verified (backfilled to created_at) so nobody is treated as
  unverified retroactively; verification is soft anyway.
- users.token_version (int, default 0) — bumped to invalidate outstanding JWTs.
- email_verification_tokens — the pending-verification-link table, mirroring
  password_reset_tokens.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7d2f5c9b3e1'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('email_verified_at', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('token_version', sa.Integer(),
                                     nullable=False, server_default='0'))
    # Grandfather every existing account as verified — they predate the feature,
    # and we don't want a mass "unverified" flag on a live user base.
    op.execute("UPDATE users SET email_verified_at = created_at WHERE email_verified_at IS NULL")

    op.create_table(
        'email_verification_tokens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('token_hash', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('used_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash'),
    )
    op.create_index(op.f('ix_email_verification_tokens_user_id'),
                    'email_verification_tokens', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_email_verification_tokens_user_id'),
                  table_name='email_verification_tokens')
    op.drop_table('email_verification_tokens')
    op.drop_column('users', 'token_version')
    op.drop_column('users', 'email_verified_at')
