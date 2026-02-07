"""Initial schema with all 11 tables

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-02-06

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create all initial tables."""

    # Note: We don't create enums here as SQLAlchemy will create them automatically
    # when creating the tables that use them

    # Users table
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("spotify_user_id", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("country", sa.String(10), nullable=True),
        sa.Column("product", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_spotify_user_id", "users", ["spotify_user_id"], unique=True)

    # Spotify tokens table
    op.create_table(
        "spotify_tokens",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(), nullable=True),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_spotify_tokens_user_id", "spotify_tokens", ["user_id"], unique=True)

    # Tracks table
    op.create_table(
        "tracks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("spotify_track_id", sa.String(255), nullable=True),
        sa.Column("local_track_id", sa.String(255), nullable=True),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("album_name", sa.String(500), nullable=True),
        sa.Column("album_spotify_id", sa.String(255), nullable=True),
        sa.Column("isrc", sa.String(50), nullable=True),
        sa.Column("source", sa.Enum("spotify_api", "import_zip", name="tracksource"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tracks_spotify_track_id", "tracks", ["spotify_track_id"], unique=True)
    op.create_index("ix_tracks_local_track_id", "tracks", ["local_track_id"], unique=True)

    # Artists table
    op.create_table(
        "artists",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("spotify_artist_id", sa.String(255), nullable=True),
        sa.Column("local_artist_id", sa.String(255), nullable=True),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("genres", sa.Text(), nullable=True),
        sa.Column("source", sa.Enum("spotify_api", "import_zip", name="tracksource"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_artists_spotify_artist_id", "artists", ["spotify_artist_id"], unique=True)
    op.create_index("ix_artists_local_artist_id", "artists", ["local_artist_id"], unique=True)

    # Track artists junction table
    op.create_table(
        "track_artists",
        sa.Column("track_id", sa.BigInteger(), nullable=False),
        sa.Column("artist_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["track_id"], ["tracks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["artist_id"], ["artists.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("track_id", "artist_id"),
    )
    op.create_index("ix_track_artists_track_id", "track_artists", ["track_id"])
    op.create_index("ix_track_artists_artist_id", "track_artists", ["artist_id"])

    # Plays table
    op.create_table(
        "plays",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("track_id", sa.BigInteger(), nullable=False),
        sa.Column("played_at", sa.DateTime(), nullable=False),
        sa.Column("ms_played", sa.Integer(), nullable=True),
        sa.Column("context_type", sa.String(50), nullable=True),
        sa.Column("context_uri", sa.String(255), nullable=True),
        sa.Column("source", sa.Enum("spotify_api", "import_zip", name="tracksource"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["track_id"], ["tracks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "played_at", "track_id", name="uq_plays_user_played_track"),
    )
    op.create_index("ix_plays_user_id", "plays", ["user_id"])
    op.create_index("ix_plays_track_id", "plays", ["track_id"])
    op.create_index("ix_plays_played_at", "plays", ["played_at"])
    op.create_index("ix_plays_user_played_at", "plays", ["user_id", "played_at"])

    # Audio features table
    op.create_table(
        "audio_features",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("track_id", sa.BigInteger(), nullable=False),
        sa.Column("danceability", sa.Float(), nullable=True),
        sa.Column("energy", sa.Float(), nullable=True),
        sa.Column("key", sa.Integer(), nullable=True),
        sa.Column("loudness", sa.Float(), nullable=True),
        sa.Column("mode", sa.Integer(), nullable=True),
        sa.Column("speechiness", sa.Float(), nullable=True),
        sa.Column("acousticness", sa.Float(), nullable=True),
        sa.Column("instrumentalness", sa.Float(), nullable=True),
        sa.Column("liveness", sa.Float(), nullable=True),
        sa.Column("valence", sa.Float(), nullable=True),
        sa.Column("tempo", sa.Float(), nullable=True),
        sa.Column("time_signature", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["track_id"], ["tracks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audio_features_track_id", "audio_features", ["track_id"], unique=True)

    # Sync checkpoints table
    op.create_table(
        "sync_checkpoints",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Enum("idle", "paused", "syncing", "error", name="syncstatus"), nullable=False),
        sa.Column("initial_sync_started_at", sa.DateTime(), nullable=True),
        sa.Column("initial_sync_completed_at", sa.DateTime(), nullable=True),
        sa.Column("initial_sync_earliest_played_at", sa.DateTime(), nullable=True),
        sa.Column("last_poll_started_at", sa.DateTime(), nullable=True),
        sa.Column("last_poll_completed_at", sa.DateTime(), nullable=True),
        sa.Column("last_poll_latest_played_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sync_checkpoints_user_id", "sync_checkpoints", ["user_id"], unique=True)

    # Job runs table
    op.create_table(
        "job_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("job_type", sa.Enum("import_zip", "initial_sync", "poll", "enrich", name="jobtype"), nullable=False),
        sa.Column("status", sa.Enum("running", "success", "error", name="jobstatus"), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("records_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_inserted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("job_metadata", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_runs_user_id", "job_runs", ["user_id"])
    op.create_index("ix_job_runs_started_at", "job_runs", ["started_at"])
    op.create_index("ix_job_runs_user_started", "job_runs", ["user_id", "started_at"])

    # Import jobs table
    op.create_table(
        "import_jobs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Enum("pending", "processing", "success", "error", name="importstatus"), nullable=False),
        sa.Column("file_path", sa.String(1000), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("format_detected", sa.String(100), nullable=True),
        sa.Column("records_ingested", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("earliest_played_at", sa.DateTime(), nullable=True),
        sa.Column("latest_played_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_import_jobs_user_id", "import_jobs", ["user_id"])
    op.create_index("ix_import_jobs_status", "import_jobs", ["status"])
    op.create_index("ix_import_jobs_created_at", "import_jobs", ["created_at"])

    # Logs table
    op.create_table(
        "logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("service", sa.String(50), nullable=False),
        sa.Column("level", sa.Enum("debug", "info", "warning", "error", name="loglevel"), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("job_run_id", sa.BigInteger(), nullable=True),
        sa.Column("import_job_id", sa.BigInteger(), nullable=True),
        sa.Column("log_metadata", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["job_run_id"], ["job_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["import_job_id"], ["import_jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_logs_timestamp", "logs", ["timestamp"])
    op.create_index("ix_logs_service", "logs", ["service"])
    op.create_index("ix_logs_level", "logs", ["level"])
    op.create_index("ix_logs_service_level", "logs", ["service", "level"])
    op.create_index("ix_logs_timestamp_service", "logs", ["timestamp", "service"])


def downgrade() -> None:
    """Drop all tables and enums."""
    op.drop_table("logs")
    op.drop_table("import_jobs")
    op.drop_table("job_runs")
    op.drop_table("sync_checkpoints")
    op.drop_table("audio_features")
    op.drop_table("plays")
    op.drop_table("track_artists")
    op.drop_table("artists")
    op.drop_table("tracks")
    op.drop_table("spotify_tokens")
    op.drop_table("users")

    # Drop enums (one at a time for asyncpg compatibility)
    op.execute("DROP TYPE IF EXISTS loglevel")
    op.execute("DROP TYPE IF EXISTS importstatus")
    op.execute("DROP TYPE IF EXISTS jobstatus")
    op.execute("DROP TYPE IF EXISTS jobtype")
    op.execute("DROP TYPE IF EXISTS syncstatus")
    op.execute("DROP TYPE IF EXISTS tracksource")
