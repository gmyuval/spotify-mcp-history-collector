"""MCP tool handlers for operational status queries — class-based."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.registry import registry
from app.mcp.schemas import MCPToolParam
from shared.db.models.operations import ImportJob, JobRun, SyncCheckpoint
from shared.db.models.user import User

_USER_PARAM = MCPToolParam(name="user_id", type="int", description="User ID")
_LIMIT_PARAM = MCPToolParam(name="limit", type="int", description="Max results", required=False, default=5)


class OpsToolHandlers:
    """Registers and handles ops-related MCP tools."""

    def __init__(self) -> None:
        self._register()

    def _register(self) -> None:
        registry.register(
            name="ops.list_users",
            description="List all registered Spotify users with their IDs and display names",
            category="ops",
            parameters=[],
        )(self.list_users)

        registry.register(
            name="ops.sync_status",
            description="Current sync state for a user: status, initial sync progress, last poll time",
            category="ops",
            parameters=[_USER_PARAM],
        )(self.sync_status)

        registry.register(
            name="ops.latest_job_runs",
            description="Recent job execution history (poll, initial_sync, import_zip, enrich)",
            category="ops",
            parameters=[_USER_PARAM, _LIMIT_PARAM],
        )(self.latest_job_runs)

        registry.register(
            name="ops.latest_import_jobs",
            description="Recent ZIP import job status and statistics",
            category="ops",
            parameters=[_USER_PARAM, _LIMIT_PARAM],
        )(self.latest_import_jobs)

    async def list_users(self, args: dict[str, Any], session: AsyncSession) -> Any:
        result = await session.execute(select(User).order_by(User.id))
        users = result.scalars().all()
        return [
            {
                "user_id": u.id,
                "display_name": u.display_name,
            }
            for u in users
        ]

    async def sync_status(self, args: dict[str, Any], session: AsyncSession) -> Any:
        result = await session.execute(select(SyncCheckpoint).where(SyncCheckpoint.user_id == args["user_id"]))
        checkpoint = result.scalar_one_or_none()
        if checkpoint is None:
            return {"status": "no_checkpoint", "user_id": args["user_id"]}
        return {
            "user_id": checkpoint.user_id,
            "status": checkpoint.status.value,
            "initial_sync_started_at": str(checkpoint.initial_sync_started_at)
            if checkpoint.initial_sync_started_at
            else None,
            "initial_sync_completed_at": str(checkpoint.initial_sync_completed_at)
            if checkpoint.initial_sync_completed_at
            else None,
            "initial_sync_earliest_played_at": str(checkpoint.initial_sync_earliest_played_at)
            if checkpoint.initial_sync_earliest_played_at
            else None,
            "last_poll_started_at": str(checkpoint.last_poll_started_at) if checkpoint.last_poll_started_at else None,
            "last_poll_completed_at": str(checkpoint.last_poll_completed_at)
            if checkpoint.last_poll_completed_at
            else None,
            "last_poll_latest_played_at": str(checkpoint.last_poll_latest_played_at)
            if checkpoint.last_poll_latest_played_at
            else None,
            "error_message": checkpoint.error_message,
        }

    async def latest_job_runs(self, args: dict[str, Any], session: AsyncSession) -> Any:
        limit = args.get("limit", 5)
        result = await session.execute(
            select(JobRun).where(JobRun.user_id == args["user_id"]).order_by(JobRun.started_at.desc()).limit(limit)
        )
        runs = result.scalars().all()
        return [
            {
                "id": r.id,
                "job_type": r.job_type.value,
                "status": r.status.value,
                "started_at": str(r.started_at),
                "completed_at": str(r.completed_at) if r.completed_at else None,
                "records_fetched": r.records_fetched,
                "records_inserted": r.records_inserted,
                "records_skipped": r.records_skipped,
                "error_message": r.error_message,
            }
            for r in runs
        ]

    async def latest_import_jobs(self, args: dict[str, Any], session: AsyncSession) -> Any:
        limit = args.get("limit", 5)
        result = await session.execute(
            select(ImportJob)
            .where(ImportJob.user_id == args["user_id"])
            .order_by(ImportJob.created_at.desc())
            .limit(limit)
        )
        jobs = result.scalars().all()
        return [
            {
                "id": j.id,
                "status": j.status.value,
                "format_detected": j.format_detected,
                "records_ingested": j.records_ingested,
                "earliest_played_at": str(j.earliest_played_at) if j.earliest_played_at else None,
                "latest_played_at": str(j.latest_played_at) if j.latest_played_at else None,
                "started_at": str(j.started_at) if j.started_at else None,
                "completed_at": str(j.completed_at) if j.completed_at else None,
                "error_message": j.error_message,
                "created_at": str(j.created_at),
            }
            for j in jobs
        ]


_instance = OpsToolHandlers()
