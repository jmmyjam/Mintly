"""add variant to card_price_snapshot

Revision ID: d4f8a21c7e56
Revises: 24baa574b69d
Create Date: 2026-07-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4f8a21c7e56'
down_revision: Union[str, Sequence[str], None] = '24baa574b69d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # "" marks the headline series — every pre-existing row is one, so the
    # server default doubles as the backfill
    op.add_column(
        'card_price_snapshot',
        sa.Column('variant', sa.String(), nullable=False, server_default=''),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('card_price_snapshot', 'variant')
