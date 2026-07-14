"""rename portfolio_snapshot to card_price_snapshot

The snapshot table holds daily prices for any browsed card, not just portfolio
holdings, so it's renamed to reflect that. Portfolio value history is derived
from it. Renamed in place (table + indexes) to preserve existing rows.

Revision ID: b7e1c4d9f2a3
Revises: a520ca9cee08
Create Date: 2026-07-15

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b7e1c4d9f2a3'
down_revision: Union[str, Sequence[str], None] = 'a520ca9cee08'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.rename_table('portfolio_snapshot', 'card_price_snapshot')
    op.execute('ALTER INDEX ix_portfolio_snapshot_card_id RENAME TO ix_card_price_snapshot_card_id')
    op.execute('ALTER INDEX ix_snapshot_card_date RENAME TO ix_card_price_snapshot_card_date')


def downgrade() -> None:
    op.execute('ALTER INDEX ix_card_price_snapshot_card_date RENAME TO ix_snapshot_card_date')
    op.execute('ALTER INDEX ix_card_price_snapshot_card_id RENAME TO ix_portfolio_snapshot_card_id')
    op.rename_table('card_price_snapshot', 'portfolio_snapshot')
