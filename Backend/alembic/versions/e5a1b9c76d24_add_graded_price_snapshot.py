"""add graded_price_snapshot

Revision ID: e5a1b9c76d24
Revises: c1d2e3f4a5b6
Create Date: 2026-09-14

Adds the slab price series (roadmap #11 — phase 2 of condition/grade): one row
per (card_id, grader, grade) per UTC day, sourced from eBay sold comps for that
exact slab and filled only for combos users actually hold.

A sibling table rather than a `grade` column on card_price_snapshot on purpose:
`variant` there means TCGplayer finish, and every existing reader of that table
queries by card_id alone, so graded rows sitting beside the raw series would
leak into card history, portfolio value-over-time, and day-change baselines.

`sale_count` records how many comps backed the median — a 3-sale median and a
25-sale median are different claims and the UI needs to distinguish them.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5a1b9c76d24'
down_revision: Union[str, Sequence[str], None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'graded_price_snapshot',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('card_id', sa.String(), nullable=True),
        sa.Column('grader', sa.String(), nullable=False),
        sa.Column('grade', sa.String(), nullable=False),
        sa.Column('price', sa.Float(), nullable=True),
        sa.Column('sale_count', sa.Integer(), nullable=True),
        sa.Column('snapshot_date', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_graded_price_snapshot_card_id'),
                    'graded_price_snapshot', ['card_id'], unique=False)
    op.create_index('ix_graded_snapshot_holding_date', 'graded_price_snapshot',
                    ['card_id', 'grader', 'grade', 'snapshot_date'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_graded_snapshot_holding_date', table_name='graded_price_snapshot')
    op.drop_index(op.f('ix_graded_price_snapshot_card_id'), table_name='graded_price_snapshot')
    op.drop_table('graded_price_snapshot')
