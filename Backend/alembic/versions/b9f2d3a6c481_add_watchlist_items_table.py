"""add watchlist_items table

Revision ID: b9f2d3a6c481
Revises: a1c5f7e2d9b4
Create Date: 2026-08-13

Adds:
- watchlist_items — cards a user tracks without owning (roadmap: watchlist +
  price alerts). One row per (user, card) (unique constraint), holding the
  denormalized card name plus the alert config: target_price (NULL = watch-only),
  direction ("below"/"above"), and last_alerted_at (the re-arm latch the daily
  job's alert pass sets/clears so a card past its target isn't re-alerted daily).
  No FK cascade — account deletion clears these rows explicitly, like the token
  tables.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b9f2d3a6c481'
down_revision: Union[str, Sequence[str], None] = 'a1c5f7e2d9b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'watchlist_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('card_id', sa.String(), nullable=False),
        sa.Column('card_name', sa.String(), nullable=True),
        sa.Column('target_price', sa.Float(), nullable=True),
        sa.Column('direction', sa.String(), server_default='below', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('last_alerted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'card_id', name='uq_watchlist_user_card'),
    )
    op.create_index(op.f('ix_watchlist_items_user_id'), 'watchlist_items', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_watchlist_items_user_id'), table_name='watchlist_items')
    op.drop_table('watchlist_items')
