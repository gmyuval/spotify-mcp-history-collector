"""Admin API endpoints — user management, import uploads, status."""

import functools
import uuid
from pathlib import Path
from typing import Annotated

import anyio
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.schemas import ImportJobResponse, ImportJobStatusResponse
from app.dependencies import db_manager
from app.settings import AppSettings, get_settings
from shared.db.enums import ImportStatus
from shared.db.models.operations import ImportJob
from shared.db.models.user import User

router = APIRouter()


@router.post("/users/{user_id}/import", response_model=ImportJobResponse)
async def upload_import(
    user_id: int,
    file: UploadFile,
    session: Annotated[AsyncSession, Depends(db_manager.dependency)],
    settings: Annotated[AppSettings, Depends(get_settings)],
) -> ImportJobResponse:
    """Upload a Spotify data export ZIP for a user.

    The file is saved to disk and an ImportJob is created with PENDING status.
    The collector service will pick it up on its next cycle.
    """
    # Validate user exists
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")

    # Validate file
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="File must be a .zip archive")

    # Prepare upload directory
    upload_dir = Path(settings.UPLOAD_DIR)
    await anyio.to_thread.run_sync(lambda: upload_dir.mkdir(parents=True, exist_ok=True))

    max_bytes = settings.IMPORT_MAX_ZIP_SIZE_MB * 1024 * 1024

    # Generate unique filename (sanitize user-supplied name to prevent path traversal)
    original_name = Path(file.filename).name
    safe_filename = f"{user_id}_{uuid.uuid4().hex}_{original_name}"
    dest_path = upload_dir / safe_filename

    # Stream upload to disk with size check
    total_size = 0
    chunk_size = 1024 * 1024  # 1MB chunks

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
        raise HTTPException(status_code=500, detail=f"Failed to save file: {exc}") from exc

    # Create ImportJob
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


@router.get("/import-jobs/{job_id}", response_model=ImportJobStatusResponse)
async def get_import_job_status(
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
