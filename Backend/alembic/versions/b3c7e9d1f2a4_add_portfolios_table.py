"""add portfolios table + portfolio_cards.portfolio_id

Revision ID: b3c7e9d1f2a4
Revises: a7d2f5c9b3e1
Create Date: 2026-08-03

Introduces multiple named portfolios per user. Until now a "portfolio" was
implicit — every portfolio_cards row keyed only on user_id. This adds:
- portfolios — one row per named collection (the auto-created "My Portfolio" is
  is_default=True; a user always keeps at least one).
- portfolio_cards.portfolio_id — which portfolio a lot lives in, NOT NULL.

The backfill (hand-written; autogenerate can't produce it) creates one default
portfolio per existing card-holder and assigns all their lots to it, so every
current lot has a home before the column goes NOT NULL. Users with no cards get
their default lazily at first access (ensure_default_portfolio).

"""
from typing import Sequence, Union
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3c7e9d1f2a4'
down_revision: Union[str, Sequence[str], None] = 'a7d2f5c9b3e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'portfolios',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_portfolios_user_id'), 'portfolios', ['user_id'], unique=False)

    # Add the FK column nullable so the backfill can populate it before it goes
    # NOT NULL.
    op.add_column('portfolio_cards', sa.Column('portfolio_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_portfolio_cards_portfolio_id'), 'portfolio_cards', ['portfolio_id'], unique=False)
    op.create_foreign_key(
        'fk_portfolio_cards_portfolio_id', 'portfolio_cards', 'portfolios',
        ['portfolio_id'], ['id'],
    )

    # Backfill: one default portfolio per existing card-holder, then assign all
    # their lots to it. RETURNING is Postgres (the only place migrations run).
    conn = op.get_bind()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    user_ids = [row[0] for row in conn.execute(
        sa.text("SELECT DISTINCT user_id FROM portfolio_cards WHERE user_id IS NOT NULL")
    )]
    for uid in user_ids:
        pid = conn.execute(
            sa.text(
                "INSERT INTO portfolios (user_id, name, is_default, created_at) "
                "VALUES (:uid, :name, true, :created) RETURNING id"
            ),
            {"uid": uid, "name": "My Portfolio", "created": now},
        ).scalar()
        conn.execute(
            sa.text("UPDATE portfolio_cards SET portfolio_id = :pid WHERE user_id = :uid"),
            {"pid": pid, "uid": uid},
        )

    op.alter_column('portfolio_cards', 'portfolio_id', existing_type=sa.Integer(), nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_portfolio_cards_portfolio_id', 'portfolio_cards', type_='foreignkey')
    op.drop_index(op.f('ix_portfolio_cards_portfolio_id'), table_name='portfolio_cards')
    op.drop_column('portfolio_cards', 'portfolio_id')
    op.drop_index(op.f('ix_portfolios_user_id'), table_name='portfolios')
    op.drop_table('portfolios')
