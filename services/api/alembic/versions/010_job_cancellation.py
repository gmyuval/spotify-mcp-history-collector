"""Add cancelled_at to job_runs and cancelled to job_status enum

Revision ID: 010_job_cancellation
Revises: 009_app_settings
Create Date: 2026-03-11

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "010_job_cancellation"
down_revision = "009_app_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add 'cancelled' value to the job_status enum (PostgreSQL only)
    op.execute("ALTER TYPE jobstatus ADD VALUE IF NOT EXISTS 'cancelled'")

    # Add cancelled_at column to job_runs
    op.add_column(
        "job_runs",
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    # Rewrite any 'cancelled' rows to 'error' so pre-010 code can read them after rollback
    op.execute("UPDATE job_runs SET status = 'error' WHERE status = 'cancelled'")
    op.drop_column("job_runs", "cancelled_at")
    # Note: PostgreSQL does not support removing enum values — downgrade leaves enum intact
