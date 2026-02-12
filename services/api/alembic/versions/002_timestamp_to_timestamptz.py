"""Convert all TIMESTAMP columns to TIMESTAMPTZ

Revision ID: 002_timestamp_to_timestamptz
Revises: 001_initial_schema
Create Date: 2026-02-12

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "002_timestamp_to_timestamptz"
down_revision = "001_initial_schema"
branch_labels = None
depends_on = None

# All (table, column) pairs that need TIMESTAMP -> TIMESTAMPTZ.
_COLUMNS = [
    ("users", "created_at"),
    ("users", "updated_at"),
    ("spotify_tokens", "token_expires_at"),
    ("spotify_tokens", "created_at"),
    ("spotify_tokens", "updated_at"),
    ("tracks", "created_at"),
    ("tracks", "updated_at"),
    ("artists", "created_at"),
    ("artists", "updated_at"),
    ("plays", "played_at"),
    ("plays", "created_at"),
    ("audio_features", "created_at"),
    ("sync_checkpoints", "initial_sync_started_at"),
    ("sync_checkpoints", "initial_sync_completed_at"),
    ("sync_checkpoints", "initial_sync_earliest_played_at"),
    ("sync_checkpoints", "last_poll_started_at"),
    ("sync_checkpoints", "last_poll_completed_at"),
    ("sync_checkpoints", "last_poll_latest_played_at"),
    ("sync_checkpoints", "created_at"),
    ("sync_checkpoints", "updated_at"),
    ("job_runs", "started_at"),
    ("job_runs", "completed_at"),
    ("import_jobs", "earliest_played_at"),
    ("import_jobs", "latest_played_at"),
    ("import_jobs", "started_at"),
    ("import_jobs", "completed_at"),
    ("import_jobs", "created_at"),
    ("logs", "timestamp"),
]


def upgrade() -> None:
    """ALTER all TIMESTAMP columns to TIMESTAMP WITH TIME ZONE.

    PostgreSQL treats existing naive values as UTC when converting,
    which matches our convention (all values were stored as UTC).
    """
    for table, column in _COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.DateTime(timezone=True),
            existing_type=sa.DateTime(),
            existing_nullable=True,
        )


def downgrade() -> None:
    """Revert TIMESTAMPTZ back to TIMESTAMP."""
    for table, column in _COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.DateTime(),
            existing_type=sa.DateTime(timezone=True),
            existing_nullable=True,
        )
