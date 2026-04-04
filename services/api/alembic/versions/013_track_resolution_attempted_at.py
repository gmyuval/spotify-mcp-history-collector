"""Add resolution_attempted_at to tracks for local track resolution

Revision ID: 013_resolution_attempted_at
Revises: 012_playlist_freshness
Create Date: 2026-04-03

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "013_resolution_attempted_at"
down_revision = "012_playlist_freshness"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tracks",
        sa.Column("resolution_attempted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tracks", "resolution_attempted_at")
