"""add scan_feedback table

Revision ID: a1c5f7e2d9b4
Revises: e2b9d47a1c05
Create Date: 2026-08-11

Adds:
- scan_feedback — anonymous accuracy telemetry for the camera scanner (roadmap
  #10). One row per confirmed pick or explicit miss: the chosen candidate's rank
  + CLIP score, the top candidate's score, the candidate count, and both card
  ids (for confusion analysis). No user linkage by design — it's aggregate
  measurement, not per-account data. The scanned photo is never stored.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c5f7e2d9b4'
down_revision: Union[str, Sequence[str], None] = 'e2b9d47a1c05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'scan_feedback',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('outcome', sa.String(), nullable=False),
        sa.Column('picked_rank', sa.Integer(), nullable=True),
        sa.Column('picked_score', sa.Float(), nullable=True),
        sa.Column('top_score', sa.Float(), nullable=True),
        sa.Column('candidate_count', sa.Integer(), nullable=False),
        sa.Column('top_card_id', sa.String(), nullable=True),
        sa.Column('picked_card_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('scan_feedback')
