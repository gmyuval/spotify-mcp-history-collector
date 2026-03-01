"""MCP tool handlers for persistent taste memory — profile + preference events."""

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.registry import registry
from app.mcp.schemas import MCPToolParam
from shared.db.models.memory import PreferenceEvent, TasteProfile

logger = logging.getLogger(__name__)

_USER_PARAM = MCPToolParam(name="user_id", type="int", description="User ID")


# ── Tool handler class ──────────────────────────────────────────────


class MemoryToolHandlers:
    """Registers and handles memory.* MCP tools for taste profile + preference events."""

    def __init__(self) -> None:
        self._register()

    def _register(self) -> None:
        registry.register(
            name="memory.get_profile",
            description="Get the user's persistent taste profile (genres, rules, preferences). Returns empty profile if none exists yet.",
            category="memory",
            parameters=[_USER_PARAM],
        )(self.get_profile)

        registry.register(
            name="memory.update_profile",
            description="Update the user's taste profile via JSON merge-patch. Creates profile if missing (unless create_if_missing=false). Increments version.",
            category="memory",
            parameters=[
                _USER_PARAM,
                MCPToolParam(name="patch", type="object", description="JSON merge-patch to apply to the profile"),
                MCPToolParam(name="reason", type="string", description="Why this update was made", required=False),
                MCPToolParam(
                    name="source",
                    type="string",
                    description="Who originated this: user, assistant, or inferred",
                    required=False,
                    default="assistant",
                ),
                MCPToolParam(
                    name="create_if_missing",
                    type="boolean",
                    description="Create profile if it doesn't exist (default true)",
                    required=False,
                    default=True,
                ),
            ],
        )(self.update_profile)

        registry.register(
            name="memory.append_preference_event",
            description="Append an explicit preference event (like, dislike, rule, feedback, note) to the user's event log.",
            category="memory",
            parameters=[
                _USER_PARAM,
                MCPToolParam(
                    name="type",
                    type="string",
                    description="Event type: like, dislike, rule, feedback, or note",
                ),
                MCPToolParam(
                    name="payload", type="object", description="Event payload (e.g. {raw_text: '...', entities: [...]})"
                ),
                MCPToolParam(
                    name="source",
                    type="string",
                    description="Who originated this: user, assistant, or inferred",
                    required=False,
                    default="assistant",
                ),
                MCPToolParam(
                    name="timestamp",
                    type="string",
                    description="ISO datetime override (defaults to now)",
                    required=False,
                ),
            ],
        )(self.append_preference_event)

        registry.register(
            name="memory.clear_profile",
            description="Clear/reset the user's taste profile. Optionally also clear all preference events. After clearing, the profile returns to version 0.",
            category="memory",
            parameters=[
                _USER_PARAM,
                MCPToolParam(
                    name="clear_events",
                    type="boolean",
                    description="Also delete all preference events (default false)",
                    required=False,
                    default=False,
                ),
            ],
        )(self.clear_profile)

    # ── memory.get_profile ──────────────────────────────────────────

    async def get_profile(self, args: dict[str, Any], session: AsyncSession) -> dict[str, Any]:
        user_id = args.get("user_id")
        if not isinstance(user_id, int) or user_id < 1:
            raise ValueError("user_id must be a positive integer")

        profile = await session.get(TasteProfile, user_id)
        if profile is None:
            return {
                "user_id": user_id,
                "profile": {},
                "version": 0,
                "updated_at": None,
            }

        return {
            "user_id": profile.user_id,
            "profile": profile.profile_json,
            "version": profile.version,
            "updated_at": profile.updated_at.isoformat(),
        }

    # ── memory.update_profile ───────────────────────────────────────

    async def update_profile(self, args: dict[str, Any], session: AsyncSession) -> dict[str, Any]:
        user_id = args.get("user_id")
        if not isinstance(user_id, int) or user_id < 1:
            raise ValueError("user_id must be a positive integer")

        patch = args.get("patch")
        # ChatGPT may send object params as JSON strings
        if isinstance(patch, str):
            try:
                patch = json.loads(patch)
            except json.JSONDecodeError:
                raise ValueError("patch must be valid JSON") from None
        if not isinstance(patch, dict) or not patch:
            raise ValueError("patch must be a non-empty object")

        reason = args.get("reason", "")
        source = args.get("source", "assistant")
        create_if_missing = args.get("create_if_missing", True)
        if not isinstance(create_if_missing, bool):
            raise ValueError("create_if_missing must be a boolean")

        valid_sources = {"user", "assistant", "inferred"}
        if source not in valid_sources:
            raise ValueError(f"source must be one of: {', '.join(sorted(valid_sources))}")

        # Lock the row to prevent concurrent read-modify-write races
        stmt = select(TasteProfile).where(TasteProfile.user_id == user_id).with_for_update()
        result = await session.execute(stmt)
        profile = result.scalar_one_or_none()

        if profile is None:
            if not create_if_missing:
                raise ValueError(f"No taste profile exists for user {user_id}")
            # Create new profile with the patch as initial content
            profile = TasteProfile(
                user_id=user_id,
                profile_json=patch,
                version=1,
            )
            session.add(profile)
        else:
            # Shallow merge: patch keys overwrite existing, new keys added
            merged = {**profile.profile_json, **patch}
            profile.profile_json = merged
            profile.version += 1

        # Also append a preference event recording the reason for audit
        if reason:
            event = PreferenceEvent(
                event_id=uuid.uuid4(),
                user_id=user_id,
                source=source,
                type="note",
                payload_json={"action": "profile_update", "reason": reason, "patch_keys": list(patch.keys())},
            )
            session.add(event)

        await session.flush()

        return {
            "user_id": profile.user_id,
            "profile": profile.profile_json,
            "version": profile.version,
            "updated_at": profile.updated_at.isoformat(),
        }

    # ── memory.append_preference_event ──────────────────────────────

    async def append_preference_event(self, args: dict[str, Any], session: AsyncSession) -> dict[str, Any]:
        user_id = args.get("user_id")
        if not isinstance(user_id, int) or user_id < 1:
            raise ValueError("user_id must be a positive integer")

        event_type = args.get("type")
        valid_types = {"like", "dislike", "rule", "feedback", "note"}
        if event_type not in valid_types:
            raise ValueError(f"type must be one of: {', '.join(sorted(valid_types))}")

        payload = args.get("payload")
        # ChatGPT may send object params as JSON strings
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                raise ValueError("payload must be valid JSON") from None
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")

        source = args.get("source", "assistant")
        valid_sources = {"user", "assistant", "inferred"}
        if source not in valid_sources:
            raise ValueError(f"source must be one of: {', '.join(sorted(valid_sources))}")

        # Parse optional timestamp
        ts = datetime.now(UTC)
        ts_raw = args.get("timestamp")
        if ts_raw:
            try:
                ts = datetime.fromisoformat(ts_raw)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
            except ValueError, TypeError:
                raise ValueError("timestamp must be a valid ISO datetime string") from None

        event_id = uuid.uuid4()
        event = PreferenceEvent(
            event_id=event_id,
            user_id=user_id,
            timestamp=ts,
            source=source,
            type=event_type,
            payload_json=payload,
        )
        session.add(event)
        await session.flush()

        return {
            "event_id": str(event_id),
            "user_id": user_id,
            "timestamp": ts.isoformat(),
        }

    # ── memory.clear_profile ─────────────────────────────────────────

    async def clear_profile(self, args: dict[str, Any], session: AsyncSession) -> dict[str, Any]:
        user_id = args.get("user_id")
        if not isinstance(user_id, int) or user_id < 1:
            raise ValueError("user_id must be a positive integer")

        clear_events = args.get("clear_events", False)
        if not isinstance(clear_events, bool):
            raise ValueError("clear_events must be a boolean")

        # Delete the taste profile row
        await session.execute(delete(TasteProfile).where(TasteProfile.user_id == user_id))

        events_cleared = False
        if clear_events:
            await session.execute(delete(PreferenceEvent).where(PreferenceEvent.user_id == user_id))
            events_cleared = True

        await session.flush()

        return {
            "user_id": user_id,
            "cleared": True,
            "events_cleared": events_cleared,
        }


_instance = MemoryToolHandlers()
