"""RBAC permission checking — service class and FastAPI dependencies."""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models.rbac import Permission, Role, RolePermission, UserRole

logger = logging.getLogger(__name__)


class PermissionChecker:
    """Checks whether a user holds a specific permission via their assigned roles.

    Usage::

        checker = PermissionChecker()
        if await checker.has_permission(user_id, "mcp_tools.use", session):
            ...

    For repeated checks within the same request, use :meth:`get_user_permissions`
    once and test membership locally.
    """

    async def has_permission(
        self,
        user_id: int,
        codename: str,
        session: AsyncSession,
    ) -> bool:
        """Return ``True`` if *user_id* holds the permission identified by *codename*."""
        permissions = await self.get_user_permissions(user_id, session)
        return codename in permissions

    async def get_user_permissions(
        self,
        user_id: int,
        session: AsyncSession,
    ) -> set[str]:
        """Return the full set of permission codenames granted to *user_id*."""
        stmt = (
            select(Permission.codename)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(Role, Role.id == RolePermission.role_id)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
        )
        result = await session.execute(stmt)
        return {row[0] for row in result.all()}

    async def get_user_roles(
        self,
        user_id: int,
        session: AsyncSession,
    ) -> list[dict[str, Any]]:
        """Return a list of role dicts ``{"id", "name", "is_system"}`` for *user_id*."""
        stmt = (
            select(Role.id, Role.name, Role.is_system)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
        )
        result = await session.execute(stmt)
        return [{"id": row.id, "name": row.name, "is_system": row.is_system} for row in result.all()]

    async def assign_role(
        self,
        user_id: int,
        role_name: str,
        session: AsyncSession,
    ) -> bool:
        """Assign a role to a user by role name. Returns ``True`` if newly assigned.

        Returns ``False`` if the user already had the role (idempotent).
        Uses a nested transaction to atomically attempt the insert, avoiding
        race conditions where two concurrent callers both pass an existence
        check and one fails on the unique constraint.
        Raises ``ValueError`` if the role does not exist.
        """
        role = await self._get_role_by_name(role_name, session)
        if role is None:
            raise ValueError(f"Role not found: {role_name}")

        try:
            async with session.begin_nested():
                session.add(UserRole(user_id=user_id, role_id=role.id))
                await session.flush()
        except IntegrityError as exc:
            # Only swallow duplicate-key errors (unique/PK constraint on user_roles).
            # Re-raise unexpected integrity errors (e.g. FK violations for invalid user_id).
            exc_text = str(exc.orig).lower() if exc.orig else str(exc).lower()
            if "unique" in exc_text or "duplicate" in exc_text or "user_roles_pkey" in exc_text:
                return False
            raise

        logger.info("Assigned role '%s' to user %d", role_name, user_id)
        return True

    async def revoke_role(
        self,
        user_id: int,
        role_name: str,
        session: AsyncSession,
    ) -> bool:
        """Revoke a role from a user by role name. Returns ``True`` if revoked.

        Returns ``False`` if the user didn't have the role (idempotent).
        Raises ``ValueError`` if the role does not exist.
        """
        role = await self._get_role_by_name(role_name, session)
        if role is None:
            raise ValueError(f"Role not found: {role_name}")

        result = await session.execute(select(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role.id))
        row = result.scalar_one_or_none()
        if row is None:
            return False

        await session.delete(row)
        await session.flush()
        logger.info("Revoked role '%s' from user %d", role_name, user_id)
        return True

    @staticmethod
    async def _get_role_by_name(name: str, session: AsyncSession) -> Role | None:
        result = await session.execute(select(Role).where(Role.name == name))
        return result.scalar_one_or_none()
