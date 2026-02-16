"""Add per-user Spotify app credential columns to users table

Revision ID: 005_user_spotify_credentials
Revises: 004_rbac_tables
Create Date: 2026-02-16

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "005_user_spotify_credentials"
down_revision = "004_rbac_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add custom Spotify credential columns to users."""
    op.add_column("users", sa.Column("custom_spotify_client_id", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("encrypted_custom_client_secret", sa.Text(), nullable=True))


def downgrade() -> None:
    """Remove custom Spotify credential columns from users."""
    op.drop_column("users", "encrypted_custom_client_secret")
    op.drop_column("users", "custom_spotify_client_id")
