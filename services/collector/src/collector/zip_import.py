"""ZIP import service — processes pending ImportJob records."""

import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, update

from collector.job_tracking import JobTracker
from collector.settings import CollectorSettings
from shared.db.enums import ImportStatus, JobType
from shared.db.models.operations import ImportJob, JobRun
from shared.db.operations import MusicRepository
from shared.db.session import DatabaseManager
from shared.zip_import.models import NormalizedPlayRecord
from shared.zip_import.parser import ZipImportParser

logger = logging.getLogger(__name__)


class ZipImportService:
    """Processes pending ZIP import jobs."""

    def __init__(self, settings: CollectorSettings) -> None:
        self._settings = settings
        self._music_repo = MusicRepository()
        self._job_tracker = JobTracker()
        self._parser = ZipImportParser(
            batch_size=5000,
            max_records=settings.IMPORT_MAX_RECORDS,
        )

    async def process_pending_imports(self, db_manager: DatabaseManager) -> int:
        """Find and process all pending import jobs. Returns count of jobs processed."""
        async with db_manager.session() as session:
            result = await session.execute(
                select(ImportJob).where(ImportJob.status == ImportStatus.PENDING).order_by(ImportJob.created_at)
            )
            pending_jobs = list(result.scalars().all())

        if not pending_jobs:
            return 0

        logger.info("Found %d pending import job(s)", len(pending_jobs))
        processed = 0

        for import_job in pending_jobs:
            await self._process_single_import(import_job.id, import_job.user_id, db_manager)
            processed += 1

        return processed

    async def _process_single_import(
        self,
        job_id: int,
        user_id: int,
        db_manager: DatabaseManager,
    ) -> None:
        """Process a single import job end-to-end."""
        # Atomically claim the job (prevents concurrent double-processing)
        async with db_manager.session() as session:
            result = await session.execute(
                update(ImportJob)
                .where(ImportJob.id == job_id, ImportJob.status == ImportStatus.PENDING)
                .values(
                    status=ImportStatus.PROCESSING,
                    started_at=datetime.now(UTC).replace(tzinfo=None),
                )
                .returning(ImportJob)
            )
            import_job = result.scalar_one_or_none()
            if import_job is None:
                return

            job_run = await self._job_tracker.start_job(user_id, JobType.IMPORT_ZIP, session)
            job_run_id = job_run.id

        zip_path = Path(import_job.file_path)
        logger.info("Processing import job %d for user %d: %s", job_id, user_id, zip_path)

        try:
            # Validate file
            if not zip_path.exists():
                raise FileNotFoundError(f"ZIP file not found: {zip_path}")

            file_size_mb = zip_path.stat().st_size / (1024 * 1024)
            if file_size_mb > self._settings.IMPORT_MAX_ZIP_SIZE_MB:
                raise ValueError(
                    f"ZIP file too large: {file_size_mb:.1f}MB (max {self._settings.IMPORT_MAX_ZIP_SIZE_MB}MB)"
                )

            # Detect format
            format_name = self._parser.detect_format(zip_path)

            async with db_manager.session() as session:
                result = await session.execute(select(ImportJob).where(ImportJob.id == job_id))
                job = result.scalar_one()
                job.format_detected = format_name

            logger.info("Detected format: %s", format_name)

            # Process batches
            total_inserted = 0
            total_skipped = 0
            total_parsed = 0
            earliest: datetime | None = None
            latest: datetime | None = None

            for batch in self._parser.iter_batches(zip_path, format_name):
                async with db_manager.session() as batch_session:
                    inserted, skipped = await self._music_repo.batch_process_import_records(
                        batch, user_id, batch_session
                    )

                total_inserted += inserted
                total_skipped += skipped
                total_parsed += len(batch)

                # Track date range
                batch_earliest, batch_latest = self._batch_date_range(batch)
                if batch_earliest and (earliest is None or batch_earliest < earliest):
                    earliest = batch_earliest
                if batch_latest and (latest is None or batch_latest > latest):
                    latest = batch_latest

                logger.info(
                    "Import job %d: batch done (%d inserted, %d skipped, %d total so far)",
                    job_id,
                    inserted,
                    skipped,
                    total_parsed,
                )

            # Mark success
            async with db_manager.session() as session:
                result = await session.execute(select(ImportJob).where(ImportJob.id == job_id))
                job = result.scalar_one()
                job.status = ImportStatus.SUCCESS
                job.completed_at = datetime.now(UTC).replace(tzinfo=None)
                job.records_ingested = total_inserted
                job.earliest_played_at = earliest
                job.latest_played_at = latest

                job_run_result = await session.execute(select(JobRun).where(JobRun.id == job_run_id))
                tracked_job = job_run_result.scalar_one()
                await self._job_tracker.complete_job(
                    tracked_job,
                    fetched=total_parsed,
                    inserted=total_inserted,
                    skipped=total_skipped,
                    session=session,
                )

            logger.info(
                "Import job %d completed: %d inserted, %d skipped, range=%s to %s",
                job_id,
                total_inserted,
                total_skipped,
                earliest,
                latest,
            )

        except Exception as exc:
            logger.exception("Import job %d failed", job_id)
            async with db_manager.session() as session:
                result = await session.execute(select(ImportJob).where(ImportJob.id == job_id))
                job = result.scalar_one()
                job.status = ImportStatus.ERROR
                job.completed_at = datetime.now(UTC).replace(tzinfo=None)
                job.error_message = str(exc)[:1000]

                job_run_result = await session.execute(select(JobRun).where(JobRun.id == job_run_id))
                tracked_job = job_run_result.scalar_one()
                await self._job_tracker.fail_job(tracked_job, str(exc)[:500], session)

    @staticmethod
    def _batch_date_range(batch: list[NormalizedPlayRecord]) -> tuple[datetime | None, datetime | None]:
        """Return (earliest, latest) played_at from a batch."""
        if not batch:
            return None, None
        dates = [r.played_at for r in batch]
        return min(dates), max(dates)
