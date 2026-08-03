"""add portfolio_cards.user_id index

Revision ID: f1a2b3c4d5e6
Revises: c8e4f1a2b7d3
Create Date: 2026-08-03

Every portfolio operation filters portfolio_cards by user_id (load, history,
add, update, delete), so it does a sequential scan without this index.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'c8e4f1a2b7d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(op.f('ix_portfolio_cards_user_id'), 'portfolio_cards', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_portfolio_cards_user_id'), table_name='portfolio_cards')
