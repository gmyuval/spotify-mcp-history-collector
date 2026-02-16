"""Add Spotify API cache tables

Revision ID: 003_spotify_cache_tables
Revises: 002_timestamp_to_timestamptz
Create Date: 2026-02-16

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "003_spotify_cache_tables"
down_revision = "002_timestamp_to_timestamptz"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create cache tables for Spotify API data."""

    # Cached playlists
    op.create_table(
        "cached_playlists",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("spotify_playlist_id", sa.String(255), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_id", sa.String(255), nullable=True),
        sa.Column("owner_display_name", sa.String(500), nullable=True),
        sa.Column("public", sa.Boolean(), nullable=True),
        sa.Column("collaborative", sa.Boolean(), nullable=True),
        sa.Column("snapshot_id", sa.String(255), nullable=True),
        sa.Column("total_tracks", sa.Integer(), nullable=True),
        sa.Column("external_url", sa.String(500), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("spotify_playlist_id", "user_id", name="uq_cached_playlist_spotify_user"),
    )
    op.create_index("ix_cached_playlists_spotify_playlist_id", "cached_playlists", ["spotify_playlist_id"])
    op.create_index("ix_cached_playlists_user_id", "cached_playlists", ["user_id"])
    op.create_index("ix_cached_playlists_user_spotify", "cached_playlists", ["user_id", "spotify_playlist_id"])

    # Cached playlist tracks
    op.create_table(
        "cached_playlist_tracks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("cached_playlist_id", sa.BigInteger(), nullable=False),
        sa.Column("spotify_track_id", sa.String(255), nullable=True),
        sa.Column("track_name", sa.String(500), nullable=False),
        sa.Column("artists_json", sa.Text(), nullable=True),
        sa.Column("added_at", sa.String(50), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["cached_playlist_id"], ["cached_playlists.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_cached_playlist_tracks_cached_playlist_id", "cached_playlist_tracks", ["cached_playlist_id"])

    # Generic entity cache (tracks, artists, albums)
    op.create_table(
        "spotify_entity_cache",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("entity_type", sa.String(20), nullable=False),
        sa.Column("spotify_id", sa.String(255), nullable=False),
        sa.Column("data_json", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entity_type", "spotify_id", name="uq_entity_cache_type_id"),
    )
    op.create_index("ix_spotify_entity_cache_spotify_id", "spotify_entity_cache", ["spotify_id"])


def downgrade() -> None:
    """Drop cache tables."""
    op.drop_table("cached_playlist_tracks")
    op.drop_table("cached_playlists")
    op.drop_table("spotify_entity_cache")
