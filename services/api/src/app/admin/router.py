"""Admin API endpoints — class-based router for user management, imports, operations, logs."""

import functools
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated

import anyio
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.auth import require_admin
from app.admin.schemas import (
    ActionResponse,
    GlobalSyncStatus,
    ImportJobResponse,
    ImportJobStatusResponse,
    JobRunResponse,
    LogEntry,
    PaginatedResponse,
    UserDetail,
    UserSummary,
)
from app.admin.service import AdminService
from app.dependencies import db_manager
from app.settings import AppSettings, get_settings
from shared.db.enums import ImportStatus
from shared.db.models.operations import ImportJob
from shared.db.models.user import User


class AdminRouter:
    """Class-based router for admin API endpoints."""

    def __init__(self) -> None:
        self._service = AdminService()
        self.router = APIRouter(dependencies=[Depends(require_admin)])
        self._register_routes()

    def _register_routes(self) -> None:
        r = self.router

        # User management
        r.add_api_route("/users", self.list_users, methods=["GET"], response_model=PaginatedResponse[UserSummary])
        r.add_api_route("/users/{user_id}", self.get_user, methods=["GET"], response_model=UserDetail)
        r.add_api_route("/users/{user_id}/pause", self.pause_user, methods=["POST"], response_model=ActionResponse)
        r.add_api_route("/users/{user_id}/resume", self.resume_user, methods=["POST"], response_model=ActionResponse)
        r.add_api_route(
            "/users/{user_id}/trigger-sync", self.trigger_sync, methods=["POST"], response_model=ActionResponse
        )
        r.add_api_route("/users/{user_id}", self.delete_user, methods=["DELETE"], response_model=ActionResponse)

        # Import endpoints
        r.add_api_route(
            "/users/{user_id}/import", self.upload_import, methods=["POST"], response_model=ImportJobResponse
        )
        r.add_api_route(
            "/import-jobs/{job_id}",
            self.get_import_job_status,
            methods=["GET"],
            response_model=ImportJobStatusResponse,
        )

        # Operational endpoints
        r.add_api_route("/sync-status", self.get_sync_status, methods=["GET"], response_model=GlobalSyncStatus)
        r.add_api_route(
            "/job-runs", self.list_job_runs, methods=["GET"], response_model=PaginatedResponse[JobRunResponse]
        )
        r.add_api_route(
            "/import-jobs",
            self.list_import_jobs,
            methods=["GET"],
            response_model=PaginatedResponse[ImportJobStatusResponse],
        )

        # Logs
        r.add_api_route("/logs", self.list_logs, methods=["GET"], response_model=PaginatedResponse[LogEntry])
        r.add_api_route("/maintenance/purge-logs", self.purge_logs, methods=["POST"], response_model=ActionResponse)

    # --- User Management ---

    async def list_users(
        self,
        session: Annotated[AsyncSession, Depends(db_manager.dependency)],
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> PaginatedResponse[UserSummary]:
        """List all users with sync status."""
        items, total = await self._service.list_users(session, limit=limit, offset=offset)
        return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)

    async def get_user(
        self,
        user_id: int,
        session: Annotated[AsyncSession, Depends(db_manager.dependency)],
    ) -> UserDetail:
        """Get user detail with full sync state and token status."""
        detail = await self._service.get_user_detail(user_id, session)
        if detail is None:
            raise HTTPException(status_code=404, detail=f"User {user_id} not found")
        return detail

    async def pause_user(
        self,
        user_id: int,
        session: Annotated[AsyncSession, Depends(db_manager.dependency)],
    ) -> ActionResponse:
        """Pause sync for a user."""
        await self._ensure_user_exists(user_id, session)
        return await self._service.pause_user(user_id, session)

    async def resume_user(
        self,
        user_id: int,
        session: Annotated[AsyncSession, Depends(db_manager.dependency)],
    ) -> ActionResponse:
        """Resume sync for a user."""
        await self._ensure_user_exists(user_id, session)
        return await self._service.resume_user(user_id, session)

    async def trigger_sync(
        self,
        user_id: int,
        session: Annotated[AsyncSession, Depends(db_manager.dependency)],
    ) -> ActionResponse:
        """Reset initial sync checkpoint to trigger a re-sync."""
        await self._ensure_user_exists(user_id, session)
        return await self._service.trigger_sync(user_id, session)

    async def delete_user(
        self,
        user_id: int,
        session: Annotated[AsyncSession, Depends(db_manager.dependency)],
    ) -> ActionResponse:
        """Delete a user and all associated data."""
        result = await self._service.delete_user(user_id, session)
        if not result.success:
            raise HTTPException(status_code=404, detail=result.message)
        return result

    # --- Import Endpoints ---

    async def upload_import(
        self,
        user_id: int,
        file: UploadFile,
        session: Annotated[AsyncSession, Depends(db_manager.dependency)],
        settings: Annotated[AppSettings, Depends(get_settings)],
    ) -> ImportJobResponse:
        """Upload a Spotify data export ZIP for a user."""
        await self._ensure_user_exists(user_id, session)

        if not file.filename or not file.filename.endswith(".zip"):
            raise HTTPException(status_code=400, detail="File must be a .zip archive")

        upload_dir = Path(settings.UPLOAD_DIR)
        await anyio.to_thread.run_sync(lambda: upload_dir.mkdir(parents=True, exist_ok=True))

        max_bytes = settings.IMPORT_MAX_ZIP_SIZE_MB * 1024 * 1024
        original_name = Path(file.filename).name
        safe_filename = f"{user_id}_{uuid.uuid4().hex}_{original_name}"
        dest_path = upload_dir / safe_filename

        total_size = 0
        chunk_size = 1024 * 1024

        try:
            with open(dest_path, "wb") as dest:
                while True:
                    chunk = await file.read(chunk_size)
                    if not chunk:
                        break
                    total_size += len(chunk)
                    if total_size > max_bytes:
                        await anyio.to_thread.run_sync(lambda: dest_path.unlink(missing_ok=True))
                        raise HTTPException(
                            status_code=413,
                            detail=f"File exceeds maximum size of {settings.IMPORT_MAX_ZIP_SIZE_MB}MB",
                        )
                    await anyio.to_thread.run_sync(functools.partial(dest.write, chunk))
        except HTTPException:
            raise
        except Exception as exc:
            await anyio.to_thread.run_sync(lambda: dest_path.unlink(missing_ok=True))
            raise HTTPException(status_code=500, detail="Failed to save file") from exc

        import_job = ImportJob(
            user_id=user_id,
            status=ImportStatus.PENDING,
            file_path=str(dest_path),
            file_size_bytes=total_size,
        )
        session.add(import_job)
        await session.flush()

        return ImportJobResponse(
            id=import_job.id,
            user_id=import_job.user_id,
            status=import_job.status.value,
            file_size_bytes=total_size,
            created_at=import_job.created_at,
        )

    async def get_import_job_status(
        self,
        job_id: int,
        session: Annotated[AsyncSession, Depends(db_manager.dependency)],
    ) -> ImportJobStatusResponse:
        """Get the status of an import job."""
        result = await session.execute(select(ImportJob).where(ImportJob.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            raise HTTPException(status_code=404, detail=f"Import job {job_id} not found")

        return ImportJobStatusResponse(
            id=job.id,
            user_id=job.user_id,
            status=job.status.value,
            format_detected=job.format_detected,
            records_ingested=job.records_ingested,
            earliest_played_at=job.earliest_played_at,
            latest_played_at=job.latest_played_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            error_message=job.error_message,
            created_at=job.created_at,
        )

    # --- Operational Endpoints ---

    async def get_sync_status(
        self,
        session: Annotated[AsyncSession, Depends(db_manager.dependency)],
    ) -> GlobalSyncStatus:
        """Global sync overview: user counts, active syncs, recent errors."""
        return await self._service.get_global_sync_status(session)

    async def list_job_runs(
        self,
        session: Annotated[AsyncSession, Depends(db_manager.dependency)],
        user_id: int | None = None,
        job_type: str | None = None,
        status: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> PaginatedResponse[JobRunResponse]:
        """Paginated job run history with optional filters."""
        items, total = await self._service.list_job_runs(
            session, user_id=user_id, job_type=job_type, status=status, limit=limit, offset=offset
        )
        return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)

    async def list_import_jobs(
        self,
        session: Annotated[AsyncSession, Depends(db_manager.dependency)],
        user_id: int | None = None,
        status: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> PaginatedResponse[ImportJobStatusResponse]:
        """Paginated import job history with optional filters."""
        items, total = await self._service.list_import_jobs(
            session, user_id=user_id, status=status, limit=limit, offset=offset
        )
        return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)

    # --- Logs ---

    async def list_logs(
        self,
        session: Annotated[AsyncSession, Depends(db_manager.dependency)],
        service: str | None = None,
        level: str | None = None,
        user_id: int | None = None,
        q: str | None = None,
        since: datetime | None = None,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> PaginatedResponse[LogEntry]:
        """Paginated log viewer with filtering."""
        items, total = await self._service.query_logs(
            session,
            service=service,
            level=level,
            user_id=user_id,
            q=q,
            since=since,
            limit=limit,
            offset=offset,
        )
        return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)

    async def purge_logs(
        self,
        session: Annotated[AsyncSession, Depends(db_manager.dependency)],
        settings: Annotated[AppSettings, Depends(get_settings)],
        older_than_days: int | None = None,
    ) -> ActionResponse:
        """Purge logs older than the specified number of days."""
        days = older_than_days if older_than_days is not None else settings.LOG_RETENTION_DAYS
        count = await self._service.purge_logs(session, older_than_days=days)
        return ActionResponse(success=True, message=f"Purged {count} log entries older than {days} days")

    # --- Helpers ---

    @staticmethod
    async def _ensure_user_exists(user_id: int, session: AsyncSession) -> None:
        result = await session.execute(select(User.id).where(User.id == user_id))
        if result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail=f"User {user_id} not found")


_instance = AdminRouter()
router = _instance.router
