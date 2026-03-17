"""Create api_tokens table for user-facing Bearer tokens

Revision ID: 011_api_tokens
Revises: 010_job_cancellation
Create Date: 2026-03-14

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "011_api_tokens"
down_revision = "010_job_cancellation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_tokens",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("token_prefix", sa.String(16), nullable=False),
        sa.Column("token_hash", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_api_tokens_user_revoked", "api_tokens", ["user_id", "revoked_at"])
    op.create_index("ix_api_tokens_token_hash", "api_tokens", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_api_tokens_token_hash", table_name="api_tokens")
    op.drop_index("ix_api_tokens_user_revoked", table_name="api_tokens")
    op.drop_table("api_tokens")
