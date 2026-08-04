"""add oauth_accounts table + nullable password

Revision ID: e2b9d47a1c05
Revises: b3c7e9d1f2a4
Create Date: 2026-08-03

Adds:
- oauth_accounts — a social sign-in identity (Google/Microsoft) linked to a
  user. Unique on (provider, provider_account_id) so one provider identity maps
  to at most one Mintly account; the returning-user lookup keys on the same
  pair. Account merging (linking to an existing account by provider-verified
  email) lives in the app, not the schema.
- users.hashed_password made nullable — a social-only account has no password
  until it sets one via the forgot-password flow. (SQLite can't ALTER a column
  to drop NOT NULL in place; the column was already effectively nullable there,
  so the change is a no-op on SQLite and only formalizes it on Postgres.)

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2b9d47a1c05'
down_revision: Union[str, Sequence[str], None] = 'b3c7e9d1f2a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'oauth_accounts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(), nullable=False),
        sa.Column('provider_account_id', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider', 'provider_account_id',
                            name='uq_oauth_provider_account'),
    )
    op.create_index(op.f('ix_oauth_accounts_user_id'),
                    'oauth_accounts', ['user_id'], unique=False)

    # Social-only accounts have no password. Postgres needs the NOT NULL dropped;
    # SQLite (tests) doesn't support the ALTER, but its column was already
    # nullable, so skip it there.
    if op.get_context().dialect.name != 'sqlite':
        op.alter_column('users', 'hashed_password',
                        existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    if op.get_context().dialect.name != 'sqlite':
        op.alter_column('users', 'hashed_password',
                        existing_type=sa.String(), nullable=False)
    op.drop_index(op.f('ix_oauth_accounts_user_id'), table_name='oauth_accounts')
    op.drop_table('oauth_accounts')
