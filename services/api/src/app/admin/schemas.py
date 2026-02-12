"""Pydantic schemas for admin API endpoints."""

from datetime import datetime

from pydantic import BaseModel


class ImportJobResponse(BaseModel):
    """Response schema for a created import job."""

    id: int
    user_id: int
    status: str
    file_path: str
    file_size_bytes: int
    created_at: datetime


class ImportJobStatusResponse(BaseModel):
    """Response schema for import job status."""

    id: int
    user_id: int
    status: str
    format_detected: str | None
    records_ingested: int
    earliest_played_at: datetime | None
    latest_played_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    created_at: datetime
