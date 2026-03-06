"""Admin API endpoints for managing configurable settings."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.auth import require_admin
from app.admin.schemas import (
    ActionResponse,
    ResetSettingsRequest,
    SettingDetail,
    SettingsListResponse,
    UpdateSettingRequest,
)
from app.admin.settings_service import SettingsService, _settings_service
from app.dependencies import db_manager
from shared.db.models.settings import AppSetting

logger = logging.getLogger(__name__)


def _row_to_detail(row: AppSetting, svc: SettingsService) -> SettingDetail:
    """Convert an AppSetting DB row to a SettingDetail response."""
    return SettingDetail(
        key=row.key,
        value_json=row.value_json,
        default_value=svc.default_value(row.key) if row.key in svc.DEFAULTS else None,
        description=row.description,
        category=row.category,
        updated_at=row.updated_at,
    )


class SettingsRouter:
    """Class-based router for admin settings API endpoints."""

    def __init__(self) -> None:
        self._svc = _settings_service
        self.router = APIRouter(dependencies=[Depends(require_admin)])
        self._register_routes()

    def _register_routes(self) -> None:
        r = self.router
        r.add_api_route("/settings", self.list_settings, methods=["GET"], response_model=SettingsListResponse)
        r.add_api_route("/settings/reset", self.reset_settings, methods=["POST"], response_model=ActionResponse)
        r.add_api_route("/settings/{key:path}", self.get_setting, methods=["GET"], response_model=SettingDetail)
        r.add_api_route("/settings/{key:path}", self.update_setting, methods=["PUT"], response_model=SettingDetail)

    async def list_settings(
        self,
        session: Annotated[AsyncSession, Depends(db_manager.dependency)],
    ) -> SettingsListResponse:
        """List all settings grouped by category.

        Any keys missing from the DB are filled in with their hardcoded defaults.
        """
        rows = await self._svc.get_all(session)
        rows_by_key = {r.key: r for r in rows}

        # Ensure every key in DEFAULTS appears in the response (seeded or not)
        from datetime import UTC, datetime

        by_category: dict[str, list[SettingDetail]] = {}
        for key, (default_val, description, category) in self._svc.DEFAULTS.items():
            row = rows_by_key.get(key)
            if row is None:
                # Return the default as if it were stored
                detail = SettingDetail(
                    key=key,
                    value_json=default_val,
                    default_value=default_val,
                    description=description,
                    category=category,
                    updated_at=datetime.now(UTC),
                )
            else:
                detail = _row_to_detail(row, self._svc)
            by_category.setdefault(category, []).append(detail)

        return SettingsListResponse(by_category=by_category)

    async def get_setting(
        self,
        key: str,
        session: Annotated[AsyncSession, Depends(db_manager.dependency)],
    ) -> SettingDetail:
        """Get a single setting by key."""
        if key not in self._svc.DEFAULTS:
            raise HTTPException(status_code=404, detail=f"Unknown setting key: {key!r}")

        row = await session.get(AppSetting, key)
        default_val, description, category = self._svc.DEFAULTS[key]

        if row is None:
            from datetime import UTC, datetime

            return SettingDetail(
                key=key,
                value_json=default_val,
                default_value=default_val,
                description=description,
                category=category,
                updated_at=datetime.now(UTC),
            )
        return _row_to_detail(row, self._svc)

    async def update_setting(
        self,
        key: str,
        body: UpdateSettingRequest,
        session: Annotated[AsyncSession, Depends(db_manager.dependency)],
    ) -> SettingDetail:
        """Update a setting value."""
        if key not in self._svc.DEFAULTS:
            raise HTTPException(status_code=404, detail=f"Unknown setting key: {key!r}")
        try:
            row = await self._svc.set(key, body.value_json, session)
        except Exception as exc:
            logger.exception("Failed to update setting %r", key)
            raise HTTPException(status_code=500, detail="Failed to update setting") from exc
        return _row_to_detail(row, self._svc)

    async def reset_settings(
        self,
        body: ResetSettingsRequest,
        session: Annotated[AsyncSession, Depends(db_manager.dependency)],
    ) -> ActionResponse:
        """Reset one or all settings to their hardcoded defaults."""
        if body.key is not None and body.key not in self._svc.DEFAULTS:
            raise HTTPException(status_code=404, detail=f"Unknown setting key: {body.key!r}")
        try:
            count = await self._svc.reset_to_default(body.key, session)
        except Exception as exc:
            logger.exception("Failed to reset settings")
            raise HTTPException(status_code=500, detail="Failed to reset settings") from exc
        noun = f"setting {body.key!r}" if body.key else f"{count} settings"
        return ActionResponse(success=True, message=f"Reset {noun} to default.")


_instance = SettingsRouter()
router = _instance.router
