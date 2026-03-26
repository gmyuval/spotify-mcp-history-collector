"""Add playlist_cache_synced_at to sync_checkpoints

Revision ID: 012_playlist_freshness
Revises: 011_api_tokens
Create Date: 2026-03-26

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "012_playlist_freshness"
down_revision = "011_api_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sync_checkpoints",
        sa.Column("playlist_cache_synced_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sync_checkpoints", "playlist_cache_synced_at")
