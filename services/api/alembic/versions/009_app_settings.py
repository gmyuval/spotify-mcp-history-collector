"""Create app_settings table and seed default values

Revision ID: 009_app_settings
Revises: 008_add_backfill_snapshot_source
Create Date: 2026-03-06

"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision = "009_app_settings"
down_revision = "008_add_backfill_snapshot_source"
branch_labels = None
depends_on = None

# Default settings seeded on migration.
# Format: (key, value, category, description)
_DEFAULTS: list[tuple[str, object, str, str]] = [
    # Search settings
    ("search.max_query_length", 500, "search", "Maximum allowed length for search queries"),
    ("search.default_limit", 25, "search", "Default number of results returned by memory.search"),
    ("search.max_limit", 200, "search", "Maximum results allowed per memory.search call"),
    ("search.snippet_max_length", 100, "search", "Maximum characters in a result snippet"),
    ("search.score_playlist_name", 1.0, "search", "Relevance score weight for playlist name matches"),
    ("search.score_playlist_description", 0.8, "search", "Relevance score weight for playlist description matches"),
    ("search.score_playlist_tags", 0.7, "search", "Relevance score weight for playlist tag matches"),
    ("search.score_preference_event", 0.5, "search", "Relevance score weight for preference event matches"),
    ("search.score_profile", 0.3, "search", "Relevance score weight for taste profile matches"),
    # Playlist ledger settings
    ("playlist.snapshot_compaction_threshold", 10, "playlist", "Auto-snapshot created every N mutations"),
    ("playlist.default_page_size", 50, "playlist", "Default page size for memory.get_playlists"),
    ("playlist.max_page_size", 200, "playlist", "Maximum page size for memory.get_playlists"),
    ("playlist.recent_events_limit", 50, "playlist", "Default number of events included in memory.get_playlist"),
]


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value_json", JSONB(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Seed defaults
    settings_table = sa.table(
        "app_settings",
        sa.column("key", sa.String),
        sa.column("value_json", JSONB),
        sa.column("description", sa.Text),
        sa.column("category", sa.String),
    )
    op.bulk_insert(
        settings_table,
        [
            {
                "key": key,
                "value_json": value,
                "description": description,
                "category": category,
            }
            for key, value, category, description in _DEFAULTS
        ],
    )


def downgrade() -> None:
    op.drop_table("app_settings")
