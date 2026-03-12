"""Job lifecycle tracking — create, complete, and fail JobRun records."""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.enums import JobStatus, JobType
from shared.db.models.operations import JobRun
from shared.logging.context import LogContext

logger = logging.getLogger(__name__)


class JobTracker:
    """Manages JobRun records for collector operations."""

    async def start_job(
        self,
        user_id: int,
        job_type: JobType,
        session: AsyncSession,
    ) -> JobRun:
        """Create a new JobRun with status=running."""
        job_run = JobRun(
            user_id=user_id,
            job_type=job_type,
            status=JobStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        session.add(job_run)
        await session.flush()
        LogContext.set_user_id(user_id)
        LogContext.set_job_run_id(job_run.id)
        logger.info("Started %s job %d for user %d", job_type.value, job_run.id, user_id)
        return job_run

    async def complete_job(
        self,
        job_run: JobRun,
        *,
        fetched: int = 0,
        inserted: int = 0,
        skipped: int = 0,
        session: AsyncSession,
    ) -> None:
        """Mark a JobRun as successfully completed with stats."""
        job_run.status = JobStatus.SUCCESS
        job_run.completed_at = datetime.now(UTC)
        job_run.records_fetched = fetched
        job_run.records_inserted = inserted
        job_run.records_skipped = skipped
        await session.flush()
        logger.info(
            "Completed job %d: fetched=%d inserted=%d skipped=%d",
            job_run.id,
            fetched,
            inserted,
            skipped,
        )
        LogContext.clear()

    async def fail_job(
        self,
        job_run: JobRun,
        error_message: str,
        session: AsyncSession,
    ) -> None:
        """Mark a JobRun as failed with an error message."""
        job_run.status = JobStatus.ERROR
        job_run.completed_at = datetime.now(UTC)
        job_run.error_message = error_message
        await session.flush()
        logger.error("Job %d failed: %s", job_run.id, error_message)
        LogContext.clear()

    async def is_cancelled(self, job_run_id: int, session: AsyncSession) -> bool:
        """Check (via fresh DB query) whether a running job has been cancelled."""
        result = await session.execute(select(JobRun.cancelled_at).where(JobRun.id == job_run_id))
        cancelled_at = result.scalar_one_or_none()
        return cancelled_at is not None

    async def mark_cancelled(self, job_run: JobRun, session: AsyncSession) -> None:
        """Mark a JobRun as cancelled."""
        job_run.status = JobStatus.CANCELLED
        job_run.cancelled_at = datetime.now(UTC)
        job_run.completed_at = datetime.now(UTC)
        await session.flush()
        logger.info("Job %d cancelled", job_run.id)
        LogContext.clear()
