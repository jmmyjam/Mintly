"""add grading + grade to portfolio_cards

Revision ID: c1d2e3f4a5b6
Revises: b9f2d3a6c481
Create Date: 2026-08-14

Adds (roadmap #7 — condition/grade on a lot):
- portfolio_cards.grading — the case type ("Raw" | "PSA" | "BGS" | "CGC" |
  "SGC" | "Other"); NULL = unset (pre-feature lots, adds that skip the picker).
- portfolio_cards.grade — the raw condition ("Near Mint"…"Damaged") when Raw,
  else the slab grade ("10", "9.5", "Authentic"); NULL = unset.

Both nullable with no backfill: existing lots stay honestly "unknown" rather
than being asserted Near Mint. Two lots of one card with different grading are
separate holdings (the Portfolio grid groups by card_id + grading + grade).

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, Sequence[str], None] = 'b9f2d3a6c481'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('portfolio_cards', sa.Column('grading', sa.String(), nullable=True))
    op.add_column('portfolio_cards', sa.Column('grade', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('portfolio_cards', 'grade')
    op.drop_column('portfolio_cards', 'grading')
