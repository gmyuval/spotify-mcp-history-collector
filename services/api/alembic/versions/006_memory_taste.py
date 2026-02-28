"""Add taste_profiles and preference_events tables for MCP memory

Revision ID: 006_memory_taste
Revises: 005_user_spotify_credentials
Create Date: 2026-02-28

"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "006_memory_taste"
down_revision = "005_user_spotify_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "taste_profiles",
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("profile_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "preference_events",
        sa.Column("event_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "source",
            sa.Enum("user", "assistant", "inferred", name="preference_event_source"),
            nullable=False,
            server_default="assistant",
        ),
        sa.Column(
            "type",
            sa.Enum("like", "dislike", "rule", "feedback", "note", name="preference_event_type"),
            nullable=False,
        ),
        sa.Column("payload_json", postgresql.JSONB(), nullable=False, server_default="{}"),
    )

    # Index for listing events by user in chronological order
    op.create_index("ix_preference_events_user_timestamp", "preference_events", ["user_id", "timestamp"])


def downgrade() -> None:
    op.drop_index("ix_preference_events_user_timestamp", table_name="preference_events")
    op.drop_table("preference_events")
    op.drop_table("taste_profiles")
    op.execute("DROP TYPE IF EXISTS preference_event_source")
    op.execute("DROP TYPE IF EXISTS preference_event_type")
