"""Add 'backfill' value to playlist_snapshot_source enum

Revision ID: 008_add_backfill_snapshot_source
Revises: 007_playlist_ledger
Create Date: 2026-03-05

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "008_add_backfill_snapshot_source"
down_revision = "007_playlist_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE playlist_snapshot_source ADD VALUE IF NOT EXISTS 'backfill'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; no-op.
    pass
