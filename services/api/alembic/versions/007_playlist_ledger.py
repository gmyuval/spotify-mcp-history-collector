"""Add memory_playlists, playlist_snapshots, and playlist_events tables

Revision ID: 007_playlist_ledger
Revises: 006_memory_taste
Create Date: 2026-03-02

"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "007_playlist_ledger"
down_revision = "006_memory_taste"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create playlist_snapshots first (referenced by memory_playlists.latest_snapshot_id)
    op.create_table(
        "playlist_snapshots",
        sa.Column("snapshot_id", sa.Uuid(), primary_key=True),
        sa.Column("playlist_id", sa.String(80), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("track_ids", postgresql.JSONB(), nullable=False),
        sa.Column(
            "source",
            sa.Enum("create", "periodic", "manual", name="playlist_snapshot_source"),
            nullable=False,
        ),
    )

    op.create_table(
        "memory_playlists",
        sa.Column("playlist_id", sa.String(80), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("intent_tags", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("seed_context", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "latest_snapshot_id",
            sa.Uuid(),
            sa.ForeignKey("playlist_snapshots.snapshot_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("idempotency_key", sa.String(255), nullable=True, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Now add the FK from playlist_snapshots.playlist_id → memory_playlists
    op.create_foreign_key(
        "fk_playlist_snapshots_playlist_id",
        "playlist_snapshots",
        "memory_playlists",
        ["playlist_id"],
        ["playlist_id"],
        ondelete="CASCADE",
    )

    op.create_table(
        "playlist_events",
        sa.Column("event_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "playlist_id",
            sa.String(80),
            sa.ForeignKey("memory_playlists.playlist_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "type",
            sa.Enum("ADD_TRACKS", "REMOVE_TRACKS", "REORDER", "UPDATE_META", name="playlist_event_type"),
            nullable=False,
        ),
        sa.Column("payload_json", postgresql.JSONB(), nullable=False),
        sa.Column("client_event_id", sa.Uuid(), nullable=True, unique=True),
    )

    op.create_index(
        "ix_playlist_events_playlist_timestamp",
        "playlist_events",
        ["playlist_id", "timestamp"],
    )


def downgrade() -> None:
    op.drop_index("ix_playlist_events_playlist_timestamp", table_name="playlist_events")
    op.drop_table("playlist_events")
    op.drop_constraint("fk_playlist_snapshots_playlist_id", "playlist_snapshots", type_="foreignkey")
    op.drop_table("memory_playlists")
    op.drop_table("playlist_snapshots")
    op.execute("DROP TYPE IF EXISTS playlist_snapshot_source")
    op.execute("DROP TYPE IF EXISTS playlist_event_type")
