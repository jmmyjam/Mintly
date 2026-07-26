"""add card_catalog.embedding

Revision ID: c8e4f1a2b7d3
Revises: f3a9c15e8d72
Create Date: 2026-07-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8e4f1a2b7d3'
down_revision: Union[str, Sequence[str], None] = 'f3a9c15e8d72'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Nullable so the daily crawl keeps inserting/updating rows without it;
    # scripts/embed_catalog.py backfills the vectors.
    op.add_column('card_catalog', sa.Column('embedding', sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('card_catalog', 'embedding')
