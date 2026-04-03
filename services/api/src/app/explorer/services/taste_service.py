"""Taste profile CRUD and preference event history."""

import uuid

from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.explorer.schemas import (
    PaginatedPreferenceEvents,
    PreferenceEventItem,
    TasteProfileResponse,
    TasteProfileWithEvents,
)
from app.explorer.services._base import BaseExplorerService
from shared.db.enums import PreferenceEventSource, PreferenceEventType
from shared.db.models.memory import PreferenceEvent, TasteProfile


class TasteService(BaseExplorerService):
    """Manages the user's taste profile and preference events."""

    async def get_taste_profile(self, user_id: int, session: AsyncSession) -> TasteProfileWithEvents:
        """Return taste profile with the 10 most recent preference events."""
        profile = await session.get(TasteProfile, user_id)
        if profile is None:
            profile_resp = TasteProfileResponse(user_id=user_id, profile={}, version=0, updated_at=None)
        else:
            profile_resp = TasteProfileResponse(
                user_id=profile.user_id,
                profile=profile.profile_json,
                version=profile.version,
                updated_at=profile.updated_at.isoformat(),
            )

        stmt = (
            select(PreferenceEvent)
            .where(PreferenceEvent.user_id == user_id)
            .order_by(desc(PreferenceEvent.timestamp), desc(PreferenceEvent.event_id))
            .limit(10)
        )
        result = await session.execute(stmt)
        events = [
            PreferenceEventItem(
                event_id=str(e.event_id),
                timestamp=e.timestamp.isoformat(),
                source=e.source,
                type=e.type,
                payload=e.payload_json,
            )
            for e in result.scalars().all()
        ]

        return TasteProfileWithEvents(profile=profile_resp, recent_events=events)

    async def update_taste_profile(
        self, user_id: int, patch: dict[str, object], reason: str | None, session: AsyncSession
    ) -> TasteProfileResponse:
        """Apply a JSON merge-patch to the taste profile, creating it if needed."""
        profile = await session.get(TasteProfile, user_id)
        if profile is None:
            profile = TasteProfile(user_id=user_id, profile_json=patch, version=1)
            session.add(profile)
        else:
            profile.profile_json = {**profile.profile_json, **patch}
            profile.version += 1

        if reason:
            event = PreferenceEvent(
                event_id=uuid.uuid4(),
                user_id=user_id,
                source=PreferenceEventSource.USER,
                type=PreferenceEventType.NOTE,
                payload_json={"action": "profile_update", "reason": reason, "patch_keys": list(patch.keys())},
            )
            session.add(event)

        await session.flush()

        return TasteProfileResponse(
            user_id=profile.user_id,
            profile=profile.profile_json,
            version=profile.version,
            updated_at=profile.updated_at.isoformat(),
        )

    async def clear_taste_profile(self, user_id: int, session: AsyncSession) -> None:
        """Delete the user's taste profile row, resetting it to version 0."""
        await session.execute(delete(TasteProfile).where(TasteProfile.user_id == user_id))
        await session.flush()

    async def get_preference_events(
        self, user_id: int, session: AsyncSession, limit: int = 20, offset: int = 0
    ) -> PaginatedPreferenceEvents:
        """Return paginated preference events, newest first."""
        count_stmt = select(func.count()).select_from(PreferenceEvent).where(PreferenceEvent.user_id == user_id)
        total = (await session.execute(count_stmt)).scalar_one()

        stmt = (
            select(PreferenceEvent)
            .where(PreferenceEvent.user_id == user_id)
            .order_by(desc(PreferenceEvent.timestamp), desc(PreferenceEvent.event_id))
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        items = [
            PreferenceEventItem(
                event_id=str(e.event_id),
                timestamp=e.timestamp.isoformat(),
                source=e.source,
                type=e.type,
                payload=e.payload_json,
            )
            for e in result.scalars().all()
        ]

        return PaginatedPreferenceEvents(items=items, total=total, limit=limit, offset=offset)
