"""add feedback table

Revision ID: f7c3a9e1b2d4
Revises: e5a1b9c76d24
Create Date: 2026-11-11

Adds:
- feedback — messages from the public /feedback form: the message, an optional
  reply email, and the page it was sent from. No user linkage by design, so the
  form behaves the same signed in or out and account deletion has nothing to
  clear. created_at is indexed for the 24h global cap + duplicate check.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7c3a9e1b2d4'
down_revision: Union[str, Sequence[str], None] = 'e5a1b9c76d24'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'feedback',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('email', sa.String(), nullable=True),
        sa.Column('page', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_feedback_created_at'), 'feedback', ['created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_feedback_created_at'), table_name='feedback')
    op.drop_table('feedback')
