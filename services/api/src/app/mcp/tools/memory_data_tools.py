"""MCP tool handlers for memory data management — search, export, delete."""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import String, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import cast

from app.mcp.registry import registry
from app.mcp.schemas import MCPToolParam
from shared.db.models.memory import (
    MemoryPlaylist,
    PlaylistEvent,
    PlaylistSnapshot,
    PreferenceEvent,
    TasteProfile,
)
from shared.db.search import text_match

logger = logging.getLogger(__name__)

_USER_PARAM = MCPToolParam(name="user_id", type="int", description="User ID")


def _validate_user_id(args: dict[str, Any]) -> int:
    """Extract and validate user_id from tool arguments."""
    user_id = args.get("user_id")
    if type(user_id) is not int or user_id < 1:
        raise ValueError("user_id must be a positive integer")
    return user_id


def _snippet(text: str, max_len: int = 100) -> str:
    """Truncate text to max_len, adding ellipsis if needed."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


class MemoryDataToolHandlers:
    """Registers and handles memory.* MCP tools for search, export, and delete."""

    def __init__(self) -> None:
        self._register()

    def _register(self) -> None:
        """Register all memory data MCP tools with the global registry."""
        registry.register(
            name="memory.search",
            description="Keyword search across all memory data (playlists, preferences, profile) for a user.",
            category="memory",
            parameters=[
                _USER_PARAM,
                MCPToolParam(name="query", type="string", description="Search query string"),
                MCPToolParam(
                    name="limit",
                    type="int",
                    description="Max results (default 25, max 200)",
                    required=False,
                    default=25,
                ),
            ],
        )(self.search)

        registry.register(
            name="memory.export_user_data",
            description="Export all stored memory data for a user as JSON (profile, preference events, playlists, snapshots, events).",
            category="memory",
            parameters=[_USER_PARAM],
        )(self.export_user_data)

        registry.register(
            name="memory.delete_user_data",
            description="Permanently delete all stored memory data for a user. Requires confirm=true as a safety guard.",
            category="memory",
            parameters=[
                _USER_PARAM,
                MCPToolParam(
                    name="confirm",
                    type="boolean",
                    description="Must be true to confirm deletion",
                ),
            ],
        )(self.delete_user_data)

    # ── memory.search ────────────────────────────────────────────────

    async def search(self, args: dict[str, Any], session: AsyncSession) -> dict[str, Any]:
        """Search across all memory data for a user by keyword.

        Searches playlist names/descriptions/tags, preference event payloads,
        and taste profile content. Returns results ranked by relevance with
        snippets and metadata.
        """
        user_id = _validate_user_id(args)

        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        query = query.strip()
        if len(query) > 500:
            raise ValueError("query must be 500 characters or fewer")

        limit = args.get("limit", 25)
        if not isinstance(limit, int) or limit < 1:
            limit = 25
        limit = min(limit, 200)

        dialect = session.bind.dialect.name if session.bind else "postgresql"
        results: list[dict[str, Any]] = []

        # Search playlists — deduplicate by playlist_id, keep highest score
        playlist_matches: dict[str, dict[str, Any]] = {}
        await self._search_playlists(session, user_id, query, dialect, playlist_matches)

        results.extend(playlist_matches.values())

        # Search preference events
        await self._search_preference_events(session, user_id, query, dialect, results)

        # Search taste profile
        await self._search_profile(session, user_id, query, dialect, results)

        # Sort by score descending, then limit
        results.sort(key=lambda r: r["score"], reverse=True)
        results = results[:limit]

        return {"results": results}

    async def _search_playlists(
        self,
        session: AsyncSession,
        user_id: int,
        query: str,
        dialect: str,
        matches: dict[str, dict[str, Any]],
    ) -> None:
        """Search playlists by name, description, and intent tags."""
        # Search by name (score 1.0)
        stmt = select(MemoryPlaylist).where(
            MemoryPlaylist.user_id == user_id,
            text_match(MemoryPlaylist.name, query, dialect),
        )
        result = await session.execute(stmt)
        for pl in result.scalars().all():
            if pl.playlist_id not in matches or matches[pl.playlist_id]["score"] < 1.0:
                matches[pl.playlist_id] = self._playlist_result(pl, 1.0)

        # Search by description (score 0.8)
        stmt = select(MemoryPlaylist).where(
            MemoryPlaylist.user_id == user_id,
            MemoryPlaylist.description.isnot(None),
            text_match(MemoryPlaylist.description, query, dialect),
        )
        result = await session.execute(stmt)
        for pl in result.scalars().all():
            if pl.playlist_id not in matches or matches[pl.playlist_id]["score"] < 0.8:
                matches[pl.playlist_id] = self._playlist_result(pl, 0.8)

        # Search by intent tags (score 0.7)
        stmt = select(MemoryPlaylist).where(
            MemoryPlaylist.user_id == user_id,
            text_match(cast(MemoryPlaylist.intent_tags, String), query, dialect),
        )
        result = await session.execute(stmt)
        for pl in result.scalars().all():
            if pl.playlist_id not in matches or matches[pl.playlist_id]["score"] < 0.7:
                matches[pl.playlist_id] = self._playlist_result(pl, 0.7)

    def _playlist_result(self, pl: MemoryPlaylist, score: float) -> dict[str, Any]:
        """Build a search result dict for a playlist."""
        desc_part = f" — {_snippet(pl.description)}" if pl.description else ""
        return {
            "kind": "playlist",
            "id": pl.playlist_id,
            "score": score,
            "snippet": f"{pl.name}{desc_part}",
            "metadata": {
                "name": pl.name,
                "intent_tags": pl.intent_tags,
                "created_at": pl.created_at.isoformat(),
            },
        }

    async def _search_preference_events(
        self,
        session: AsyncSession,
        user_id: int,
        query: str,
        dialect: str,
        results: list[dict[str, Any]],
    ) -> None:
        """Search preference events by payload content."""
        stmt = select(PreferenceEvent).where(
            PreferenceEvent.user_id == user_id,
            text_match(cast(PreferenceEvent.payload_json, String), query, dialect),
        )
        result = await session.execute(stmt)
        for event in result.scalars().all():
            payload = event.payload_json
            raw_text = str(payload.get("raw_text", "")) if isinstance(payload, dict) else ""
            snippet_text = raw_text if raw_text else _snippet(json.dumps(payload))
            results.append(
                {
                    "kind": "preference_event",
                    "id": str(event.event_id),
                    "score": 0.5,
                    "snippet": f"{event.type}: {_snippet(snippet_text)}",
                    "metadata": {
                        "type": event.type,
                        "source": event.source,
                        "timestamp": event.timestamp.isoformat(),
                    },
                }
            )

    async def _search_profile(
        self,
        session: AsyncSession,
        user_id: int,
        query: str,
        dialect: str,
        results: list[dict[str, Any]],
    ) -> None:
        """Search taste profile by JSON content."""
        stmt = select(TasteProfile).where(
            TasteProfile.user_id == user_id,
            text_match(cast(TasteProfile.profile_json, String), query, dialect),
        )
        result = await session.execute(stmt)
        profile = result.scalar_one_or_none()
        if profile is not None:
            results.append(
                {
                    "kind": "profile",
                    "id": str(profile.user_id),
                    "score": 0.3,
                    "snippet": f"Taste profile: {_snippet(json.dumps(profile.profile_json))}",
                    "metadata": {
                        "version": profile.version,
                        "updated_at": profile.updated_at.isoformat(),
                    },
                }
            )

    # ── memory.export_user_data ──────────────────────────────────────

    async def export_user_data(self, args: dict[str, Any], session: AsyncSession) -> dict[str, Any]:
        """Export all stored memory data for a user as a JSON structure.

        Returns the complete taste profile, all preference events, all tracked
        playlists with their snapshots and mutation events.
        """
        user_id = _validate_user_id(args)

        # Taste profile
        profile = await session.get(TasteProfile, user_id)
        profile_data = None
        if profile is not None:
            profile_data = {
                "profile_json": profile.profile_json,
                "version": profile.version,
                "created_at": profile.created_at.isoformat(),
                "updated_at": profile.updated_at.isoformat(),
            }

        # Preference events
        pref_stmt = (
            select(PreferenceEvent).where(PreferenceEvent.user_id == user_id).order_by(PreferenceEvent.timestamp)
        )
        pref_result = await session.execute(pref_stmt)
        pref_events = [
            {
                "event_id": str(e.event_id),
                "timestamp": e.timestamp.isoformat(),
                "source": e.source,
                "type": e.type,
                "payload_json": e.payload_json,
            }
            for e in pref_result.scalars().all()
        ]

        # Playlists
        pl_stmt = select(MemoryPlaylist).where(MemoryPlaylist.user_id == user_id).order_by(MemoryPlaylist.created_at)
        pl_result = await session.execute(pl_stmt)
        playlists_rows = pl_result.scalars().all()

        playlists_data = [
            {
                "playlist_id": pl.playlist_id,
                "name": pl.name,
                "description": pl.description,
                "intent_tags": pl.intent_tags,
                "seed_context": pl.seed_context,
                "created_at": pl.created_at.isoformat(),
                "updated_at": pl.updated_at.isoformat(),
            }
            for pl in playlists_rows
        ]

        playlist_ids = [pl.playlist_id for pl in playlists_rows]

        # Snapshots for user's playlists
        snapshots_data: list[dict[str, Any]] = []
        if playlist_ids:
            snap_stmt = (
                select(PlaylistSnapshot)
                .where(PlaylistSnapshot.playlist_id.in_(playlist_ids))
                .order_by(PlaylistSnapshot.created_at)
            )
            snap_result = await session.execute(snap_stmt)
            snapshots_data = [
                {
                    "snapshot_id": str(s.snapshot_id),
                    "playlist_id": s.playlist_id,
                    "created_at": s.created_at.isoformat(),
                    "track_ids": s.track_ids,
                    "source": s.source,
                }
                for s in snap_result.scalars().all()
            ]

        # Playlist events for user's playlists
        pl_events_data: list[dict[str, Any]] = []
        if playlist_ids:
            ev_stmt = (
                select(PlaylistEvent)
                .where(PlaylistEvent.playlist_id.in_(playlist_ids))
                .order_by(PlaylistEvent.timestamp)
            )
            ev_result = await session.execute(ev_stmt)
            pl_events_data = [
                {
                    "event_id": str(ev.event_id),
                    "playlist_id": ev.playlist_id,
                    "timestamp": ev.timestamp.isoformat(),
                    "type": ev.type,
                    "payload_json": ev.payload_json,
                }
                for ev in ev_result.scalars().all()
            ]

        return {
            "user_id": user_id,
            "exported_at": datetime.now(UTC).isoformat(),
            "data": {
                "profile": profile_data,
                "preference_events": pref_events,
                "playlists": playlists_data,
                "snapshots": snapshots_data,
                "playlist_events": pl_events_data,
            },
        }

    # ── memory.delete_user_data ──────────────────────────────────────

    async def delete_user_data(self, args: dict[str, Any], session: AsyncSession) -> dict[str, Any]:
        """Permanently delete all stored memory data for a user.

        Deletes taste profile, preference events, playlists, snapshots, and
        playlist events. Requires ``confirm=true`` as a safety guard. Deletion
        order respects FK constraints (child tables first, circular FK nulled).
        """
        user_id = _validate_user_id(args)

        confirm = args.get("confirm")
        if confirm is not True:
            raise ValueError("confirm must be true to delete all memory data")

        # Get user's playlist IDs for child-table cleanup
        id_stmt = select(MemoryPlaylist.playlist_id).where(MemoryPlaylist.user_id == user_id)
        id_result = await session.execute(id_stmt)
        playlist_ids = [row[0] for row in id_result.all()]

        if playlist_ids:
            # 1. Delete playlist events (child of memory_playlists)
            await session.execute(delete(PlaylistEvent).where(PlaylistEvent.playlist_id.in_(playlist_ids)))

            # 2. Null out latest_snapshot_id to break circular FK
            await session.execute(
                update(MemoryPlaylist).where(MemoryPlaylist.user_id == user_id).values(latest_snapshot_id=None)
            )

            # 3. Delete snapshots (child of memory_playlists)
            await session.execute(delete(PlaylistSnapshot).where(PlaylistSnapshot.playlist_id.in_(playlist_ids)))

            # 4. Delete playlists
            await session.execute(delete(MemoryPlaylist).where(MemoryPlaylist.user_id == user_id))

        # 5. Delete preference events
        await session.execute(delete(PreferenceEvent).where(PreferenceEvent.user_id == user_id))

        # 6. Delete taste profile
        await session.execute(delete(TasteProfile).where(TasteProfile.user_id == user_id))

        await session.flush()

        return {
            "user_id": user_id,
            "deleted_at": datetime.now(UTC).isoformat(),
            "deleted": True,
        }


_instance = MemoryDataToolHandlers()
