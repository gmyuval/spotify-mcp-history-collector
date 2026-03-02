"""MCP tool handlers for playlist ledger — log, list, get, reconstruct."""

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any, NamedTuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.registry import registry
from app.mcp.schemas import MCPToolParam
from shared.db.enums import PlaylistEventType, PlaylistSnapshotSource
from shared.db.models.memory import MemoryPlaylist, PlaylistEvent, PlaylistSnapshot

logger = logging.getLogger(__name__)

_USER_PARAM = MCPToolParam(name="user_id", type="int", description="User ID")

# Snapshot compaction: auto-snapshot every N mutations
_COMPACTION_THRESHOLD = 10


class ReconstructionResult(NamedTuple):
    """Result of reconstructing a playlist's track list from snapshots and events."""

    track_ids: list[str]
    """Ordered list of track IDs representing the playlist at the reconstructed point."""
    used_snapshot_id: str | None
    """ID of the base snapshot used, or None if reconstructed from scratch."""
    applied_event_count: int
    """Number of mutation events replayed on top of the snapshot."""


def _parse_json_param(value: Any, name: str) -> Any:
    """Parse a JSON string parameter into a Python object.

    ChatGPT sends object/array parameters as JSON strings rather than
    native objects, so this handles transparent deserialization.
    """
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            raise ValueError(f"{name} must be valid JSON") from None
    return value


def _validate_user_id(args: dict[str, Any]) -> int:
    """Extract and validate user_id from tool arguments."""
    user_id = args.get("user_id")
    if not isinstance(user_id, int) or user_id < 1:
        raise ValueError("user_id must be a positive integer")
    return user_id


def _validate_playlist_id(args: dict[str, Any]) -> str:
    """Extract and validate playlist_id from tool arguments."""
    playlist_id = args.get("playlist_id")
    if not isinstance(playlist_id, str) or not playlist_id.strip():
        raise ValueError("playlist_id must be a non-empty string")
    return playlist_id.strip()


async def _reconstruct_track_list(
    playlist_id: str,
    session: AsyncSession,
    snapshot: PlaylistSnapshot | None = None,
    before_time: datetime | None = None,
) -> ReconstructionResult:
    """Reconstruct a playlist's track list by replaying events on a snapshot.

    Starts from the given snapshot's track list (or empty if no snapshot),
    then fetches all mutation events after the snapshot and before ``before_time``,
    applying each in chronological order to produce the final track list.

    Args:
        playlist_id: Spotify playlist ID to reconstruct.
        session: Active database session.
        snapshot: Base snapshot to start from (None = start empty).
        before_time: Only apply events up to this timestamp (None = all events).
    """
    # Initialize from the base snapshot, or start with an empty list
    if snapshot is not None:
        track_ids: list[str] = [str(t) for t in snapshot.track_ids]
        used_snapshot_id = str(snapshot.snapshot_id)
        base_time = snapshot.created_at
    else:
        track_ids = []
        used_snapshot_id = None
        base_time = None

    # Fetch mutation events after the snapshot's timestamp, ordered chronologically
    stmt = select(PlaylistEvent).where(PlaylistEvent.playlist_id == playlist_id).order_by(PlaylistEvent.timestamp)
    if base_time is not None:
        stmt = stmt.where(PlaylistEvent.timestamp > base_time)
    if before_time is not None:
        stmt = stmt.where(PlaylistEvent.timestamp <= before_time)

    result = await session.execute(stmt)
    events = result.scalars().all()

    # Replay each event to reconstruct the current track list.
    # Each event type modifies the track list differently:
    #   ADD_TRACKS:    append (or insert at position) new tracks
    #   REMOVE_TRACKS: filter out matching track IDs
    #   REORDER:       replace entire list with the new ordering
    #   UPDATE_META:   no track changes (name/description only)
    for event in events:
        payload = event.payload_json
        raw_tids = payload.get("track_ids")
        p_track_ids = list(raw_tids) if isinstance(raw_tids, list) else []

        if event.type == PlaylistEventType.ADD_TRACKS:
            new_ids = [str(t) for t in p_track_ids]
            insert_at = payload.get("insert_at")
            if insert_at is not None and isinstance(insert_at, int) and 0 <= insert_at <= len(track_ids):
                # Insert tracks at the specified position, preserving order
                for i, tid in enumerate(new_ids):
                    track_ids.insert(insert_at + i, tid)
            else:
                track_ids.extend(new_ids)

        elif event.type == PlaylistEventType.REMOVE_TRACKS:
            remove_ids = {str(t) for t in p_track_ids}
            track_ids = [t for t in track_ids if t not in remove_ids]

        elif event.type == PlaylistEventType.REORDER:
            new_order = [str(t) for t in p_track_ids]
            if new_order:
                track_ids = new_order

        # UPDATE_META events don't affect the track list — skip silently

    return ReconstructionResult(track_ids, used_snapshot_id, len(events))


class PlaylistLedgerToolHandlers:
    """Registers and handles memory.* MCP tools for the playlist ledger."""

    def __init__(self) -> None:
        self._register()

    def _register(self) -> None:
        """Register all playlist ledger MCP tools with the global registry."""
        registry.register(
            name="memory.log_playlist_create",
            description="Log a newly created playlist with its initial track list. Called after spotify.create_playlist + spotify.add_tracks.",
            category="memory",
            parameters=[
                _USER_PARAM,
                MCPToolParam(name="playlist_id", type="string", description="Spotify playlist ID"),
                MCPToolParam(name="name", type="string", description="Playlist name"),
                MCPToolParam(name="track_ids", type="array", description="Ordered list of Spotify track IDs"),
                MCPToolParam(name="description", type="string", description="Playlist description", required=False),
                MCPToolParam(
                    name="intent_tags",
                    type="array",
                    description='Tags describing playlist intent (e.g. ["upbeat", "symphonic metal"])',
                    required=False,
                    default=[],
                ),
                MCPToolParam(
                    name="seed_context",
                    type="object",
                    description="Context that inspired the playlist (time window, top artists used, etc.)",
                    required=False,
                    default={},
                ),
                MCPToolParam(
                    name="idempotency_key",
                    type="string",
                    description="Idempotency key to prevent duplicate creates on retry",
                    required=False,
                ),
            ],
        )(self.log_playlist_create)

        registry.register(
            name="memory.log_playlist_mutation",
            description="Log a playlist mutation (add/remove tracks, reorder, update metadata). Called after each Spotify playlist edit.",
            category="memory",
            parameters=[
                _USER_PARAM,
                MCPToolParam(name="playlist_id", type="string", description="Spotify playlist ID"),
                MCPToolParam(
                    name="type",
                    type="string",
                    description="Mutation type: ADD_TRACKS, REMOVE_TRACKS, REORDER, or UPDATE_META",
                ),
                MCPToolParam(
                    name="payload",
                    type="object",
                    description="Mutation payload (e.g. {track_ids: [...]} for ADD/REMOVE/REORDER, {name: ...} for UPDATE_META)",
                ),
                MCPToolParam(
                    name="client_event_id",
                    type="string",
                    description="Client-generated UUID for idempotency",
                    required=False,
                ),
            ],
        )(self.log_playlist_mutation)

        registry.register(
            name="memory.get_playlists",
            description="List assistant-tracked playlists for a user, ordered by most recently updated.",
            category="memory",
            parameters=[
                _USER_PARAM,
                MCPToolParam(
                    name="limit", type="int", description="Max results (default 50)", required=False, default=50
                ),
                MCPToolParam(
                    name="cursor", type="string", description="Pagination cursor from previous response", required=False
                ),
            ],
        )(self.get_playlists)

        registry.register(
            name="memory.get_playlist",
            description="Get full details of an assistant-tracked playlist including metadata, latest snapshot, and recent events.",
            category="memory",
            parameters=[
                _USER_PARAM,
                MCPToolParam(name="playlist_id", type="string", description="Spotify playlist ID"),
                MCPToolParam(
                    name="include_events_limit",
                    type="int",
                    description="Max events to include (default 50, max 500)",
                    required=False,
                    default=50,
                ),
            ],
        )(self.get_playlist)

        registry.register(
            name="memory.reconstruct_playlist",
            description="Reconstruct the playlist's track list from snapshots and events. Use when Spotify read-back fails (403).",
            category="memory",
            parameters=[
                _USER_PARAM,
                MCPToolParam(name="playlist_id", type="string", description="Spotify playlist ID"),
                MCPToolParam(
                    name="at_time",
                    type="string",
                    description="Reconstruct as of this ISO datetime (defaults to now)",
                    required=False,
                ),
            ],
        )(self.reconstruct_playlist)

    # ── memory.log_playlist_create ────────────────────────────────────

    async def log_playlist_create(self, args: dict[str, Any], session: AsyncSession) -> dict[str, Any]:
        """Log a newly created playlist with its initial track list.

        Creates a MemoryPlaylist record and an initial PlaylistSnapshot.
        Supports idempotency via ``idempotency_key`` — duplicate calls return
        the existing record without error.
        """
        user_id = _validate_user_id(args)
        playlist_id = _validate_playlist_id(args)

        name = args.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name must be a non-empty string")
        name = name.strip()

        track_ids = _parse_json_param(args.get("track_ids"), "track_ids")
        if not isinstance(track_ids, list) or not track_ids:
            raise ValueError("track_ids must be a non-empty array")
        if not all(isinstance(t, str) and t.strip() for t in track_ids):
            raise ValueError("track_ids must contain non-empty strings")

        description = args.get("description")
        if description is not None and not isinstance(description, str):
            raise ValueError("description must be a string")

        intent_tags = _parse_json_param(args.get("intent_tags", []), "intent_tags")
        if not isinstance(intent_tags, list):
            raise ValueError("intent_tags must be an array")

        seed_context = _parse_json_param(args.get("seed_context", {}), "seed_context")
        if not isinstance(seed_context, dict):
            raise ValueError("seed_context must be an object")

        idempotency_key = args.get("idempotency_key")

        # Idempotency check
        if idempotency_key:
            stmt = select(MemoryPlaylist).where(MemoryPlaylist.idempotency_key == idempotency_key)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing is not None:
                # Return existing record with track count from stored snapshot
                existing_snap_id = str(existing.latest_snapshot_id) if existing.latest_snapshot_id else None
                stored_count = 0
                if existing.latest_snapshot_id:
                    snap = await session.get(PlaylistSnapshot, existing.latest_snapshot_id)
                    if snap:
                        stored_count = len(snap.track_ids)
                return {
                    "playlist_id": existing.playlist_id,
                    "snapshot_id": existing_snap_id,
                    "created_at": existing.created_at.isoformat(),
                    "stored_track_count": stored_count,
                }

        # Also check if playlist_id already exists
        existing_playlist = await session.get(MemoryPlaylist, playlist_id)
        if existing_playlist is not None:
            raise ValueError(f"Playlist {playlist_id} already exists in memory ledger")

        # Create playlist record first (without snapshot ref to avoid circular FK)
        playlist = MemoryPlaylist(
            playlist_id=playlist_id,
            user_id=user_id,
            name=name,
            description=description,
            intent_tags=intent_tags,
            seed_context=seed_context,
            latest_snapshot_id=None,
            idempotency_key=idempotency_key,
        )
        session.add(playlist)
        await session.flush()

        # Now create snapshot (playlist_id FK is satisfied)
        snapshot_id = uuid.uuid4()
        snapshot = PlaylistSnapshot(
            snapshot_id=snapshot_id,
            playlist_id=playlist_id,
            track_ids=track_ids,
            source=PlaylistSnapshotSource.CREATE,
        )
        session.add(snapshot)
        await session.flush()

        # Update playlist with snapshot reference
        playlist.latest_snapshot_id = snapshot_id
        await session.flush()

        return {
            "playlist_id": playlist_id,
            "snapshot_id": str(snapshot_id),
            "created_at": playlist.created_at.isoformat(),
            "stored_track_count": len(track_ids),
        }

    # ── memory.log_playlist_mutation ──────────────────────────────────

    async def log_playlist_mutation(self, args: dict[str, Any], session: AsyncSession) -> dict[str, Any]:
        """Log a playlist mutation event (add/remove tracks, reorder, update metadata).

        Validates the mutation type and payload structure, creates a PlaylistEvent
        record, updates playlist metadata for UPDATE_META events, and triggers
        snapshot compaction if enough events have accumulated since the last snapshot.
        Supports idempotency via ``client_event_id``.
        """
        user_id = _validate_user_id(args)
        playlist_id = _validate_playlist_id(args)

        mutation_type = args.get("type")
        valid_types = {e.value for e in PlaylistEventType}
        if mutation_type not in valid_types:
            raise ValueError(f"type must be one of: {', '.join(sorted(valid_types))}")

        payload = _parse_json_param(args.get("payload"), "payload")
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")

        # Validate payload per mutation type
        if mutation_type in (PlaylistEventType.ADD_TRACKS, PlaylistEventType.REMOVE_TRACKS):
            p_track_ids = payload.get("track_ids")
            if not isinstance(p_track_ids, list) or not p_track_ids:
                raise ValueError(f"payload.track_ids is required for {mutation_type}")
        elif mutation_type == PlaylistEventType.REORDER:
            p_track_ids = payload.get("track_ids")
            if not isinstance(p_track_ids, list) or not p_track_ids:
                raise ValueError("payload.track_ids is required for REORDER (full new order)")
        elif mutation_type == PlaylistEventType.UPDATE_META:
            valid_meta_fields = {"name", "description", "intent_tags"}
            if not any(k in payload for k in valid_meta_fields):
                raise ValueError(f"payload must contain at least one of: {', '.join(sorted(valid_meta_fields))}")

        client_event_id_raw = args.get("client_event_id")
        client_event_id: uuid.UUID | None = None
        if client_event_id_raw is not None:
            if isinstance(client_event_id_raw, str):
                try:
                    client_event_id = uuid.UUID(client_event_id_raw)
                except ValueError:
                    raise ValueError("client_event_id must be a valid UUID") from None
            elif isinstance(client_event_id_raw, uuid.UUID):
                client_event_id = client_event_id_raw
            else:
                raise ValueError("client_event_id must be a valid UUID")
            # Idempotency check
            stmt = select(PlaylistEvent).where(PlaylistEvent.client_event_id == client_event_id)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing is not None:
                return {
                    "event_id": str(existing.event_id),
                    "playlist_id": existing.playlist_id,
                    "timestamp": existing.timestamp.isoformat(),
                    "new_snapshot_id": None,
                }

        # Verify playlist exists and belongs to user
        playlist = await session.get(MemoryPlaylist, playlist_id)
        if playlist is None:
            raise ValueError(f"Playlist {playlist_id} not found in memory ledger")
        if playlist.user_id != user_id:
            raise ValueError(f"Playlist {playlist_id} not found in memory ledger")

        # Create event
        event_id = uuid.uuid4()
        event = PlaylistEvent(
            event_id=event_id,
            playlist_id=playlist_id,
            user_id=user_id,
            type=mutation_type,
            payload_json=payload,
            client_event_id=client_event_id,
        )
        session.add(event)

        # Update playlist metadata if UPDATE_META
        if mutation_type == PlaylistEventType.UPDATE_META:
            if "name" in payload:
                playlist.name = payload["name"]
            if "description" in payload:
                playlist.description = payload["description"]
            if "intent_tags" in payload:
                playlist.intent_tags = payload["intent_tags"]

        await session.flush()

        # Check if snapshot compaction is needed
        new_snapshot_id = await self._maybe_compact(playlist, session)

        return {
            "event_id": str(event_id),
            "playlist_id": playlist_id,
            "timestamp": event.timestamp.isoformat(),
            "new_snapshot_id": str(new_snapshot_id) if new_snapshot_id else None,
        }

    async def _maybe_compact(self, playlist: MemoryPlaylist, session: AsyncSession) -> uuid.UUID | None:
        """Auto-create a periodic snapshot if enough events have accumulated."""
        if playlist.latest_snapshot_id is None:
            return None

        latest_snapshot = await session.get(PlaylistSnapshot, playlist.latest_snapshot_id)
        if latest_snapshot is None:
            return None

        # Count events since last snapshot
        stmt = (
            select(func.count())
            .select_from(PlaylistEvent)
            .where(
                PlaylistEvent.playlist_id == playlist.playlist_id,
                PlaylistEvent.timestamp > latest_snapshot.created_at,
            )
        )
        result = await session.execute(stmt)
        count = result.scalar_one()

        if count < _COMPACTION_THRESHOLD:
            return None

        # Reconstruct current track list and create new snapshot
        reconstruction = await _reconstruct_track_list(playlist.playlist_id, session, snapshot=latest_snapshot)
        track_ids = reconstruction.track_ids

        new_snapshot_id = uuid.uuid4()
        new_snapshot = PlaylistSnapshot(
            snapshot_id=new_snapshot_id,
            playlist_id=playlist.playlist_id,
            track_ids=track_ids,
            source=PlaylistSnapshotSource.PERIODIC,
        )
        session.add(new_snapshot)
        playlist.latest_snapshot_id = new_snapshot_id
        await session.flush()

        logger.info(
            "Playlist %s: auto-snapshot %s after %d events",
            playlist.playlist_id,
            new_snapshot_id,
            count,
        )
        return new_snapshot_id

    # ── memory.get_playlists ──────────────────────────────────────────

    async def get_playlists(self, args: dict[str, Any], session: AsyncSession) -> dict[str, Any]:
        """List assistant-tracked playlists for a user, ordered by most recently updated.

        Returns paginated results with cursor-based navigation. Each item includes
        the track count derived from the latest snapshot.
        """
        user_id = _validate_user_id(args)
        limit = args.get("limit", 50)
        if not isinstance(limit, int) or limit < 1:
            limit = 50
        limit = min(limit, 200)

        cursor = args.get("cursor")

        stmt = (
            select(MemoryPlaylist)
            .where(MemoryPlaylist.user_id == user_id)
            .order_by(MemoryPlaylist.updated_at.desc())
            .limit(limit + 1)  # Fetch one extra to determine next_cursor
        )

        if cursor:
            try:
                cursor_dt = datetime.fromisoformat(cursor)
            except ValueError, TypeError:
                raise ValueError("cursor must be a valid ISO datetime string") from None
            stmt = stmt.where(MemoryPlaylist.updated_at < cursor_dt)

        result = await session.execute(stmt)
        playlists = list(result.scalars().all())

        has_more = len(playlists) > limit
        if has_more:
            playlists = playlists[:limit]

        items = []
        for pl in playlists:
            # Get track count from latest snapshot
            track_count = 0
            if pl.latest_snapshot_id is not None:
                snap = await session.get(PlaylistSnapshot, pl.latest_snapshot_id)
                if snap is not None:
                    track_count = len(snap.track_ids)

            items.append(
                {
                    "playlist_id": pl.playlist_id,
                    "name": pl.name,
                    "created_at": pl.created_at.isoformat(),
                    "updated_at": pl.updated_at.isoformat(),
                    "intent_tags": pl.intent_tags,
                    "track_count": track_count,
                }
            )

        next_cursor = playlists[-1].updated_at.isoformat() if has_more else None

        return {
            "items": items,
            "next_cursor": next_cursor,
        }

    # ── memory.get_playlist ───────────────────────────────────────────

    async def get_playlist(self, args: dict[str, Any], session: AsyncSession) -> dict[str, Any]:
        """Get full details of an assistant-tracked playlist.

        Returns playlist metadata, the latest snapshot (track IDs), and recent
        mutation events (up to ``include_events_limit``, max 500).
        """
        user_id = _validate_user_id(args)
        playlist_id = _validate_playlist_id(args)

        include_events_limit = args.get("include_events_limit", 50)
        if not isinstance(include_events_limit, int) or include_events_limit < 0:
            include_events_limit = 50
        include_events_limit = min(include_events_limit, 500)

        playlist = await session.get(MemoryPlaylist, playlist_id)
        if playlist is None or playlist.user_id != user_id:
            raise ValueError(f"Playlist {playlist_id} not found")

        # Get latest snapshot
        latest_snapshot_data = None
        if playlist.latest_snapshot_id is not None:
            snap = await session.get(PlaylistSnapshot, playlist.latest_snapshot_id)
            if snap is not None:
                latest_snapshot_data = {
                    "snapshot_id": str(snap.snapshot_id),
                    "created_at": snap.created_at.isoformat(),
                    "track_ids": snap.track_ids,
                }

        # Get recent events
        stmt = (
            select(PlaylistEvent)
            .where(PlaylistEvent.playlist_id == playlist_id)
            .order_by(PlaylistEvent.timestamp.desc())
            .limit(include_events_limit)
        )
        result = await session.execute(stmt)
        events = result.scalars().all()

        recent_events = [
            {
                "event_id": str(e.event_id),
                "timestamp": e.timestamp.isoformat(),
                "type": e.type,
                "payload": e.payload_json,
            }
            for e in events
        ]

        return {
            "playlist": {
                "playlist_id": playlist.playlist_id,
                "user_id": playlist.user_id,
                "name": playlist.name,
                "description": playlist.description,
                "created_at": playlist.created_at.isoformat(),
                "updated_at": playlist.updated_at.isoformat(),
                "intent_tags": playlist.intent_tags,
                "seed_context": playlist.seed_context,
            },
            "latest_snapshot": latest_snapshot_data,
            "recent_events": recent_events,
        }

    # ── memory.reconstruct_playlist ───────────────────────────────────

    async def reconstruct_playlist(self, args: dict[str, Any], session: AsyncSession) -> dict[str, Any]:
        """Reconstruct a playlist's track list from snapshots and events.

        Finds the best snapshot to use as a base (nearest before ``at_time``
        or the latest overall), then replays subsequent events to produce the
        track list. Useful when Spotify read-back fails (403, missing scopes).
        """
        user_id = _validate_user_id(args)
        playlist_id = _validate_playlist_id(args)

        playlist = await session.get(MemoryPlaylist, playlist_id)
        if playlist is None or playlist.user_id != user_id:
            raise ValueError(f"Playlist {playlist_id} not found")

        # Parse optional at_time
        at_time = None
        at_time_raw = args.get("at_time")
        if at_time_raw:
            try:
                at_time = datetime.fromisoformat(at_time_raw)
                if at_time.tzinfo is None:
                    at_time = at_time.replace(tzinfo=UTC)
            except ValueError, TypeError:
                raise ValueError("at_time must be a valid ISO datetime string") from None

        # Find the best snapshot to use
        snapshot = None
        if at_time is not None:
            # Find latest snapshot before at_time
            stmt = (
                select(PlaylistSnapshot)
                .where(
                    PlaylistSnapshot.playlist_id == playlist_id,
                    PlaylistSnapshot.created_at <= at_time,
                )
                .order_by(PlaylistSnapshot.created_at.desc())
                .limit(1)
            )
        else:
            # Find the latest snapshot overall
            stmt = (
                select(PlaylistSnapshot)
                .where(PlaylistSnapshot.playlist_id == playlist_id)
                .order_by(PlaylistSnapshot.created_at.desc())
                .limit(1)
            )

        result = await session.execute(stmt)
        snapshot = result.scalar_one_or_none()

        reconstruction = await _reconstruct_track_list(playlist_id, session, snapshot=snapshot, before_time=at_time)

        as_of = at_time.isoformat() if at_time else datetime.now(UTC).isoformat()

        return {
            "playlist_id": playlist_id,
            "as_of": as_of,
            "track_ids": reconstruction.track_ids,
            "reconstruction": {
                "used_snapshot_id": reconstruction.used_snapshot_id,
                "applied_event_count": reconstruction.applied_event_count,
            },
        }


_instance = PlaylistLedgerToolHandlers()
