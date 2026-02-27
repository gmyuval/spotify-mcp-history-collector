"""Admin business logic — user management, sync operations, job queries."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.admin.schemas import (
    DEFAULT_PAGE_LIMIT,
    ActionResponse,
    GlobalSyncStatus,
    ImportJobStatusResponse,
    JobRunResponse,
    LogEntry,
    PaginatedResult,
    PermissionResponse,
    RecentError,
    RoleSummary,
    UserCredentialStatus,
    UserDetail,
    UserRolesResponse,
    UserSummary,
)
from shared.db.enums import JobStatus, SyncStatus
from shared.db.models.log import Log
from shared.db.models.operations import ImportJob, JobRun, SyncCheckpoint
from shared.db.models.rbac import Permission, Role, RolePermission, UserRole
from shared.db.models.user import SpotifyToken, User


class AdminService:
    """Stateless service for admin operations."""

    # --- User Management ---

    async def list_users(
        self,
        session: AsyncSession,
        limit: int = DEFAULT_PAGE_LIMIT,
        offset: int = 0,
    ) -> PaginatedResult[UserSummary]:
        total_q = select(func.count(User.id))
        total = (await session.execute(total_q)).scalar() or 0

        stmt = (
            select(User)
            .outerjoin(SyncCheckpoint, SyncCheckpoint.user_id == User.id)
            .options(selectinload(User.sync_checkpoint))
            .order_by(User.id)
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        users = result.scalars().unique().all()

        return PaginatedResult(
            [
                UserSummary(
                    id=u.id,
                    spotify_user_id=u.spotify_user_id,
                    display_name=u.display_name,
                    sync_status=u.sync_checkpoint.status.value if u.sync_checkpoint else None,
                    last_poll_completed_at=(u.sync_checkpoint.last_poll_completed_at if u.sync_checkpoint else None),
                    initial_sync_completed_at=(
                        u.sync_checkpoint.initial_sync_completed_at if u.sync_checkpoint else None
                    ),
                    created_at=u.created_at,
                )
                for u in users
            ],
            total,
        )

    async def get_user_detail(
        self,
        user_id: int,
        session: AsyncSession,
    ) -> UserDetail | None:
        stmt = (
            select(User).options(selectinload(User.sync_checkpoint), selectinload(User.token)).where(User.id == user_id)
        )
        result = await session.execute(stmt)
        u = result.scalar_one_or_none()
        if u is None:
            return None

        cp = u.sync_checkpoint
        has_custom = bool(u.custom_spotify_client_id and u.encrypted_custom_client_secret)
        return UserDetail(
            id=u.id,
            spotify_user_id=u.spotify_user_id,
            display_name=u.display_name,
            email=u.email,
            country=u.country,
            product=u.product,
            sync_status=cp.status.value if cp else None,
            initial_sync_started_at=cp.initial_sync_started_at if cp else None,
            initial_sync_completed_at=cp.initial_sync_completed_at if cp else None,
            initial_sync_earliest_played_at=cp.initial_sync_earliest_played_at if cp else None,
            last_poll_started_at=cp.last_poll_started_at if cp else None,
            last_poll_completed_at=cp.last_poll_completed_at if cp else None,
            last_poll_latest_played_at=cp.last_poll_latest_played_at if cp else None,
            token_expires_at=u.token.token_expires_at if u.token else None,
            has_custom_credentials=has_custom,
            custom_spotify_client_id=u.custom_spotify_client_id if has_custom else None,
            error_message=cp.error_message if cp else None,
            created_at=u.created_at,
            updated_at=u.updated_at,
        )

    async def pause_user(self, user_id: int, session: AsyncSession) -> ActionResponse:
        cp = await self._get_checkpoint(user_id, session)
        if cp is None:
            return ActionResponse(success=False, message=f"No sync checkpoint for user {user_id}")
        if cp.status == SyncStatus.PAUSED:
            return ActionResponse(success=True, message="User already paused")
        cp.status = SyncStatus.PAUSED
        await session.flush()
        return ActionResponse(success=True, message="User sync paused")

    async def resume_user(self, user_id: int, session: AsyncSession) -> ActionResponse:
        cp = await self._get_checkpoint(user_id, session)
        if cp is None:
            return ActionResponse(success=False, message=f"No sync checkpoint for user {user_id}")
        if cp.status == SyncStatus.IDLE:
            return ActionResponse(success=True, message="User already active")
        cp.status = SyncStatus.IDLE
        cp.error_message = None
        await session.flush()
        return ActionResponse(success=True, message="User sync resumed")

    async def trigger_sync(self, user_id: int, session: AsyncSession) -> ActionResponse:
        cp = await self._get_checkpoint(user_id, session)
        if cp is None:
            return ActionResponse(success=False, message=f"No sync checkpoint for user {user_id}")
        cp.initial_sync_started_at = None
        cp.initial_sync_completed_at = None
        cp.initial_sync_earliest_played_at = None
        cp.status = SyncStatus.IDLE
        cp.error_message = None
        await session.flush()
        return ActionResponse(success=True, message="Initial sync reset — will re-sync on next cycle")

    async def delete_user(self, user_id: int, session: AsyncSession) -> ActionResponse:
        from shared.db.models.music import Play

        stmt = select(User).where(User.id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        if user is None:
            return ActionResponse(success=False, message=f"User {user_id} not found")

        # Bulk delete related rows directly — avoids loading potentially millions of ORM objects
        await session.execute(delete(Log).where(Log.user_id == user_id))
        await session.execute(delete(ImportJob).where(ImportJob.user_id == user_id))
        await session.execute(delete(JobRun).where(JobRun.user_id == user_id))
        await session.execute(delete(SyncCheckpoint).where(SyncCheckpoint.user_id == user_id))
        await session.execute(delete(SpotifyToken).where(SpotifyToken.user_id == user_id))
        await session.execute(delete(Play).where(Play.user_id == user_id))
        await session.delete(user)
        await session.flush()
        return ActionResponse(success=True, message=f"User {user_id} and all associated data deleted")

    async def _get_checkpoint(self, user_id: int, session: AsyncSession) -> SyncCheckpoint | None:
        stmt = select(SyncCheckpoint).where(SyncCheckpoint.user_id == user_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    # --- User Spotify Credentials ---

    async def get_credential_status(self, user_id: int, session: AsyncSession) -> UserCredentialStatus | None:
        """Return credential status for a user, or None if user not found."""
        stmt = select(User).where(User.id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        if user is None:
            return None
        has_custom = bool(user.custom_spotify_client_id and user.encrypted_custom_client_secret)
        return UserCredentialStatus(
            has_custom_credentials=has_custom,
            custom_client_id=user.custom_spotify_client_id if has_custom else None,
        )

    async def set_credentials(
        self,
        user_id: int,
        client_id: str,
        encrypted_client_secret: str,
        session: AsyncSession,
    ) -> ActionResponse:
        """Set custom Spotify credentials for a user."""
        stmt = select(User).where(User.id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        if user is None:
            return ActionResponse(success=False, message=f"User {user_id} not found")
        user.custom_spotify_client_id = client_id
        user.encrypted_custom_client_secret = encrypted_client_secret
        await session.flush()
        return ActionResponse(
            success=True,
            message=f"Custom Spotify credentials set for user {user_id}. "
            "User must re-authorize via /auth/login?user_id={} to use new credentials.".format(user_id),
        )

    async def clear_credentials(self, user_id: int, session: AsyncSession) -> ActionResponse:
        """Remove custom Spotify credentials for a user."""
        stmt = select(User).where(User.id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        if user is None:
            return ActionResponse(success=False, message=f"User {user_id} not found")
        user.custom_spotify_client_id = None
        user.encrypted_custom_client_secret = None
        await session.flush()
        return ActionResponse(
            success=True,
            message=f"Custom Spotify credentials removed for user {user_id}. "
            "User must re-authorize via /auth/login to revert to system credentials.",
        )

    # --- Global Sync Status ---

    async def get_global_sync_status(self, session: AsyncSession) -> GlobalSyncStatus:
        total = (await session.execute(select(func.count(User.id)))).scalar() or 0

        status_counts = (
            await session.execute(
                select(SyncCheckpoint.status, func.count(SyncCheckpoint.id)).group_by(SyncCheckpoint.status)
            )
        ).all()

        counts: dict[str, int] = {}
        for status_val, count in status_counts:
            counts[status_val.value if hasattr(status_val, "value") else str(status_val)] = count

        error_stmt = select(JobRun).where(JobRun.status == JobStatus.ERROR).order_by(JobRun.started_at.desc()).limit(5)
        error_rows = (await session.execute(error_stmt)).scalars().all()

        return GlobalSyncStatus(
            total_users=total,
            active_syncs=counts.get("syncing", 0),
            paused_users=counts.get("paused", 0),
            error_users=counts.get("error", 0),
            recent_errors=[
                RecentError(
                    job_run_id=j.id,
                    user_id=j.user_id,
                    job_type=j.job_type.value,
                    error_message=j.error_message,
                    started_at=j.started_at,
                )
                for j in error_rows
            ],
        )

    # --- Job Runs ---

    async def list_job_runs(
        self,
        session: AsyncSession,
        user_id: int | None = None,
        job_type: str | None = None,
        status: str | None = None,
        limit: int = DEFAULT_PAGE_LIMIT,
        offset: int = 0,
    ) -> PaginatedResult[JobRunResponse]:
        base = select(JobRun)
        count_base = select(func.count(JobRun.id))

        if user_id is not None:
            base = base.where(JobRun.user_id == user_id)
            count_base = count_base.where(JobRun.user_id == user_id)
        if job_type is not None:
            base = base.where(JobRun.job_type == job_type)
            count_base = count_base.where(JobRun.job_type == job_type)
        if status is not None:
            base = base.where(JobRun.status == status)
            count_base = count_base.where(JobRun.status == status)

        total = (await session.execute(count_base)).scalar() or 0
        stmt = base.order_by(JobRun.started_at.desc()).limit(limit).offset(offset)
        rows = (await session.execute(stmt)).scalars().all()

        return PaginatedResult(
            [
                JobRunResponse(
                    id=j.id,
                    user_id=j.user_id,
                    job_type=j.job_type.value,
                    status=j.status.value,
                    records_fetched=j.records_fetched,
                    records_inserted=j.records_inserted,
                    records_skipped=j.records_skipped,
                    started_at=j.started_at,
                    completed_at=j.completed_at,
                    error_message=j.error_message,
                )
                for j in rows
            ],
            total,
        )

    # --- Import Jobs ---

    async def list_import_jobs(
        self,
        session: AsyncSession,
        user_id: int | None = None,
        status: str | None = None,
        limit: int = DEFAULT_PAGE_LIMIT,
        offset: int = 0,
    ) -> PaginatedResult[ImportJobStatusResponse]:
        base = select(ImportJob)
        count_base = select(func.count(ImportJob.id))

        if user_id is not None:
            base = base.where(ImportJob.user_id == user_id)
            count_base = count_base.where(ImportJob.user_id == user_id)
        if status is not None:
            base = base.where(ImportJob.status == status)
            count_base = count_base.where(ImportJob.status == status)

        total = (await session.execute(count_base)).scalar() or 0
        stmt = base.order_by(ImportJob.created_at.desc()).limit(limit).offset(offset)
        rows = (await session.execute(stmt)).scalars().all()

        return PaginatedResult(
            [
                ImportJobStatusResponse(
                    id=j.id,
                    user_id=j.user_id,
                    status=j.status.value,
                    format_detected=j.format_detected,
                    records_ingested=j.records_ingested,
                    earliest_played_at=j.earliest_played_at,
                    latest_played_at=j.latest_played_at,
                    started_at=j.started_at,
                    completed_at=j.completed_at,
                    error_message=j.error_message,
                    created_at=j.created_at,
                )
                for j in rows
            ],
            total,
        )

    # --- Logs ---

    async def query_logs(
        self,
        session: AsyncSession,
        service: str | None = None,
        level: str | None = None,
        user_id: int | None = None,
        q: str | None = None,
        since: datetime | None = None,
        limit: int = DEFAULT_PAGE_LIMIT,
        offset: int = 0,
    ) -> PaginatedResult[LogEntry]:
        base = select(Log)
        count_base = select(func.count(Log.id))

        if service is not None:
            base = base.where(Log.service == service)
            count_base = count_base.where(Log.service == service)
        if level is not None:
            base = base.where(Log.level == level)
            count_base = count_base.where(Log.level == level)
        if user_id is not None:
            base = base.where(Log.user_id == user_id)
            count_base = count_base.where(Log.user_id == user_id)
        if q is not None:
            base = base.where(Log.message.icontains(q))
            count_base = count_base.where(Log.message.icontains(q))
        if since is not None:
            base = base.where(Log.timestamp >= since)
            count_base = count_base.where(Log.timestamp >= since)

        total = (await session.execute(count_base)).scalar() or 0
        stmt = base.order_by(Log.timestamp.desc()).limit(limit).offset(offset)
        rows = (await session.execute(stmt)).scalars().all()

        return PaginatedResult(
            [
                LogEntry(
                    id=row.id,
                    timestamp=row.timestamp,
                    service=row.service,
                    level=row.level.value if hasattr(row.level, "value") else str(row.level),
                    message=row.message,
                    user_id=row.user_id,
                    job_run_id=row.job_run_id,
                    import_job_id=row.import_job_id,
                    log_metadata=row.log_metadata,
                )
                for row in rows
            ],
            total,
        )

    async def purge_logs(
        self,
        session: AsyncSession,
        older_than_days: int = 30,
    ) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
        stmt = delete(Log).where(Log.timestamp < cutoff)
        cursor = await session.execute(stmt)
        await session.flush()
        deleted: int = cursor.rowcount  # type: ignore[attr-defined]
        return deleted

    # --- RBAC ---

    async def list_roles(self, session: AsyncSession) -> list[RoleSummary]:
        """List all roles with their permissions."""
        stmt = (
            select(Role)
            .options(selectinload(Role.role_permissions).selectinload(RolePermission.permission))
            .order_by(Role.id)
        )
        result = await session.execute(stmt)
        roles = result.scalars().unique().all()
        return [self._role_to_summary(r) for r in roles]

    async def list_permissions(self, session: AsyncSession) -> list[PermissionResponse]:
        """List all available permissions."""
        result = await session.execute(select(Permission).order_by(Permission.codename))
        return [
            PermissionResponse(id=p.id, codename=p.codename, description=p.description) for p in result.scalars().all()
        ]

    async def create_role(
        self,
        name: str,
        description: str | None,
        permission_codenames: list[str],
        session: AsyncSession,
    ) -> RoleSummary:
        """Create a new role with specified permissions."""
        unique_codenames = list(dict.fromkeys(permission_codenames))
        perm_map = await self._get_permission_map(unique_codenames, session)

        role = Role(name=name, description=description, is_system=False)
        session.add(role)
        await session.flush()

        for codename in unique_codenames:
            session.add(RolePermission(role_id=role.id, permission_id=perm_map[codename]))
        await session.flush()

        return await self._get_role_summary(role.id, session)

    async def update_role(
        self,
        role_id: int,
        name: str | None,
        description: str | None,
        permission_codenames: list[str] | None,
        session: AsyncSession,
    ) -> RoleSummary:
        """Update a role. System roles cannot be renamed."""
        role = await self._get_role_or_raise(role_id, session)

        if name is not None and name != role.name:
            if role.is_system:
                raise ValueError("Cannot rename system roles")
            role.name = name
        if description is not None:
            role.description = description

        if permission_codenames is not None:
            unique_codenames = list(dict.fromkeys(permission_codenames))
            perm_map = await self._get_permission_map(unique_codenames, session)
            await session.execute(delete(RolePermission).where(RolePermission.role_id == role_id))
            for codename in unique_codenames:
                session.add(RolePermission(role_id=role_id, permission_id=perm_map[codename]))

        await session.flush()
        return await self._get_role_summary(role_id, session)

    async def delete_role(self, role_id: int, session: AsyncSession) -> ActionResponse:
        """Delete a non-system role."""
        role = await self._get_role_or_raise(role_id, session)
        if role.is_system:
            return ActionResponse(success=False, message="Cannot delete system roles")

        await session.delete(role)
        await session.flush()
        return ActionResponse(success=True, message=f"Role '{role.name}' deleted")

    async def get_user_roles(self, user_id: int, session: AsyncSession) -> UserRolesResponse:
        """Get a user's assigned roles with permissions."""
        stmt = (
            select(Role)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
            .options(selectinload(Role.role_permissions).selectinload(RolePermission.permission))
        )
        result = await session.execute(stmt)
        roles = result.scalars().unique().all()
        return UserRolesResponse(
            user_id=user_id,
            roles=[self._role_to_summary(r) for r in roles],
        )

    async def set_user_roles(
        self,
        user_id: int,
        role_ids: list[int],
        session: AsyncSession,
    ) -> ActionResponse:
        """Replace a user's role assignments."""
        await self._get_user_or_raise(user_id, session)
        unique_role_ids = list(dict.fromkeys(role_ids))
        for rid in unique_role_ids:
            await self._get_role_or_raise(rid, session)

        await session.execute(delete(UserRole).where(UserRole.user_id == user_id))
        for rid in unique_role_ids:
            session.add(UserRole(user_id=user_id, role_id=rid))
        await session.flush()
        return ActionResponse(success=True, message=f"Roles updated for user {user_id}")

    # --- RBAC helpers ---

    @staticmethod
    def _role_to_summary(role: Role) -> RoleSummary:
        return RoleSummary(
            id=role.id,
            name=role.name,
            description=role.description,
            is_system=role.is_system,
            permissions=[
                PermissionResponse(
                    id=rp.permission.id,
                    codename=rp.permission.codename,
                    description=rp.permission.description,
                )
                for rp in role.role_permissions
            ],
            created_at=role.created_at,
            updated_at=role.updated_at,
        )

    async def _get_role_summary(self, role_id: int, session: AsyncSession) -> RoleSummary:
        stmt = (
            select(Role)
            .where(Role.id == role_id)
            .options(selectinload(Role.role_permissions).selectinload(RolePermission.permission))
        )
        result = await session.execute(stmt)
        role = result.scalar_one()
        return self._role_to_summary(role)

    @staticmethod
    async def _get_user_or_raise(user_id: int, session: AsyncSession) -> User:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise ValueError(f"User {user_id} not found")
        return user

    @staticmethod
    async def _get_role_or_raise(role_id: int, session: AsyncSession) -> Role:
        result = await session.execute(select(Role).where(Role.id == role_id))
        role = result.scalar_one_or_none()
        if role is None:
            raise ValueError(f"Role {role_id} not found")
        return role

    @staticmethod
    async def _get_permission_map(codenames: list[str], session: AsyncSession) -> dict[str, int]:
        """Return a codename->id map, raising ValueError for unknown codenames."""
        if not codenames:
            return {}
        result = await session.execute(select(Permission).where(Permission.codename.in_(codenames)))
        perms = {p.codename: p.id for p in result.scalars().all()}
        unknown = set(codenames) - perms.keys()
        if unknown:
            raise ValueError(f"Unknown permissions: {', '.join(sorted(unknown))}")
        return perms
