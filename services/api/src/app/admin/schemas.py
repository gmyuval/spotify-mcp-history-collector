"""Pydantic schemas for admin API endpoints."""

from datetime import datetime

from pydantic import BaseModel, Field

# --- Pagination ---


class PaginatedResponse[T](BaseModel):
    """Generic paginated response wrapper."""

    items: list[T]
    total: int
    limit: int
    offset: int


# --- Import Jobs (existing) ---


class ImportJobResponse(BaseModel):
    """Response schema for a created import job."""

    id: int
    user_id: int
    status: str
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


# --- User Management ---


class UserSummary(BaseModel):
    """User with sync status for list view."""

    id: int
    spotify_user_id: str
    display_name: str | None
    sync_status: str | None
    last_poll_completed_at: datetime | None
    initial_sync_completed_at: datetime | None
    created_at: datetime


class UserDetail(BaseModel):
    """Full user detail with sync state and token status."""

    id: int
    spotify_user_id: str
    display_name: str | None
    email: str | None
    country: str | None
    product: str | None
    sync_status: str | None
    initial_sync_started_at: datetime | None
    initial_sync_completed_at: datetime | None
    initial_sync_earliest_played_at: datetime | None
    last_poll_started_at: datetime | None
    last_poll_completed_at: datetime | None
    last_poll_latest_played_at: datetime | None
    token_expires_at: datetime | None
    has_custom_credentials: bool
    custom_spotify_client_id: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


# --- Global Sync Status ---


class RecentError(BaseModel):
    """A recent error from job runs."""

    job_run_id: int
    user_id: int
    job_type: str
    error_message: str | None
    started_at: datetime | None


class GlobalSyncStatus(BaseModel):
    """System-wide sync overview."""

    total_users: int
    active_syncs: int
    paused_users: int
    error_users: int
    recent_errors: list[RecentError]


# --- Job Runs ---


class JobRunResponse(BaseModel):
    """Response schema for a job run."""

    id: int
    user_id: int
    job_type: str
    status: str
    records_fetched: int
    records_inserted: int
    records_skipped: int
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None


# --- Logs ---


class LogEntry(BaseModel):
    """Response schema for a log record."""

    id: int
    timestamp: datetime
    service: str
    level: str
    message: str
    user_id: int | None
    job_run_id: int | None
    import_job_id: int | None
    log_metadata: str | None


# --- Action Responses ---


class ActionResponse(BaseModel):
    """Generic response for mutation actions."""

    success: bool
    message: str


# --- User Spotify Credentials ---


class SetUserCredentialsRequest(BaseModel):
    """Request to set custom Spotify app credentials for a user."""

    client_id: str = Field(..., min_length=1, max_length=255, description="Spotify app Client ID")
    client_secret: str = Field(..., min_length=1, max_length=255, description="Spotify app Client Secret")


class UserCredentialStatus(BaseModel):
    """Status of a user's custom Spotify app credentials."""

    has_custom_credentials: bool
    custom_client_id: str | None
