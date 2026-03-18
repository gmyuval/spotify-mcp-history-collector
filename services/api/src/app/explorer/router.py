"""User-facing explorer API endpoints — JWT-gated, own data only."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.auth import require_permission
from app.auth.api_tokens import ApiTokenService
from app.auth.exceptions import TokenNotFoundError, TokenRefreshError
from app.dependencies import db_manager
from app.explorer.schemas import (
    AlbumDetail,
    ArtistDetail,
    CreatedTokenResponse,
    CreateTokenRequest,
    DashboardData,
    MemoryPlaylistDetail,
    PaginatedArtists,
    PaginatedHistory,
    PaginatedMemoryPlaylistEvents,
    PaginatedMemoryPlaylists,
    PaginatedPreferenceEvents,
    PaginatedTracks,
    PlaylistDetail,
    PlaylistSummary,
    TasteProfilePatch,
    TasteProfileResponse,
    TasteProfileWithEvents,
    TokenListItem,
    TokenListResponse,
    TrackDetail,
    TrackSummary,
    UserProfile,
)
from app.explorer.service import ExplorerService
from app.history.schemas import ArtistCount
from app.history.service import HistoryService
from shared.spotify.exceptions import SpotifyAuthError, SpotifyClientError, SpotifyRateLimitError, SpotifyRequestError

logger = logging.getLogger(__name__)

RequireOwnDataView = Annotated[int, Depends(require_permission("own_data.view"))]
DBSession = Annotated[AsyncSession, Depends(db_manager.dependency)]


class ExplorerRouter:
    """User-facing API endpoints for the explorer frontend."""

    def __init__(self) -> None:
        self._service = ExplorerService()
        self._history_service = HistoryService()
        self.router = APIRouter()
        self._register_routes()

    def _register_routes(self) -> None:
        r = self.router
        r.add_api_route("/dashboard", self.dashboard, methods=["GET"])
        r.add_api_route("/history", self.history, methods=["GET"])
        r.add_api_route("/top-artists", self.top_artists, methods=["GET"])
        r.add_api_route("/top-tracks", self.top_tracks, methods=["GET"])
        r.add_api_route("/profile", self.profile, methods=["GET"])
        r.add_api_route("/playlists", self.playlists, methods=["GET"])
        r.add_api_route("/playlists/refresh", self.refresh_playlists, methods=["POST"])
        r.add_api_route("/playlists/{spotify_playlist_id}", self.playlist_detail, methods=["GET"])
        r.add_api_route("/playlists/{spotify_playlist_id}/fetch-tracks", self.fetch_playlist_tracks, methods=["POST"])
        r.add_api_route("/taste-profile", self.taste_profile, methods=["GET"])
        r.add_api_route("/taste-profile", self.update_taste_profile, methods=["PATCH"])
        r.add_api_route("/taste-profile", self.clear_taste_profile, methods=["DELETE"])
        r.add_api_route("/preference-events", self.preference_events, methods=["GET"])
        r.add_api_route("/memory-playlists", self.memory_playlists, methods=["GET"])
        r.add_api_route("/memory-playlists/{playlist_id}", self.memory_playlist_detail, methods=["GET"])
        r.add_api_route("/memory-playlists/{playlist_id}/events", self.memory_playlist_events, methods=["GET"])
        r.add_api_route("/tracks", self.tracks, methods=["GET"])
        r.add_api_route("/tracks/{track_id}", self.track_detail, methods=["GET"])
        r.add_api_route("/artists", self.artists, methods=["GET"])
        r.add_api_route("/artists/{artist_id}", self.artist_detail, methods=["GET"])
        r.add_api_route("/albums/{album_spotify_id}", self.album_detail, methods=["GET"])
        r.add_api_route("/tokens", self.list_tokens, methods=["GET"])
        r.add_api_route("/tokens", self.create_token, methods=["POST"], status_code=201)
        r.add_api_route("/tokens/{token_id}", self.revoke_token, methods=["DELETE"], status_code=204)

    async def dashboard(
        self,
        user_id: RequireOwnDataView,
        session: DBSession,
        days: int = Query(default=30, ge=1),
    ) -> DashboardData:
        return await self._service.get_dashboard(user_id, session, days=days)

    async def history(
        self,
        user_id: RequireOwnDataView,
        session: DBSession,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        q: str | None = Query(default=None),
    ) -> PaginatedHistory:
        return await self._service.get_history(user_id, session, limit=limit, offset=offset, q=q)

    async def top_artists(
        self,
        user_id: RequireOwnDataView,
        session: DBSession,
        days: int = Query(default=90, ge=1),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> list[ArtistCount]:
        return await self._history_service.get_top_artists(user_id, session, days=days, limit=limit)

    async def top_tracks(
        self,
        user_id: RequireOwnDataView,
        session: DBSession,
        days: int = Query(default=90, ge=1),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> list[TrackSummary]:
        rows = await self._history_service.get_top_tracks(user_id, session, days=days, limit=limit)
        return [
            TrackSummary(
                track_id=r.track_id,
                track_name=r.track_name,
                artist_name=r.artist_name,
                play_count=r.play_count,
            )
            for r in rows
        ]

    async def profile(self, user_id: RequireOwnDataView, session: DBSession) -> UserProfile:
        return await self._service.get_profile(user_id, session)

    async def playlists(self, user_id: RequireOwnDataView, session: DBSession) -> list[PlaylistSummary]:
        return await self._service.get_playlists(user_id, session)

    async def refresh_playlists(self, user_id: RequireOwnDataView, session: DBSession) -> list[PlaylistSummary]:
        """Force-refresh playlist list from Spotify API."""
        try:
            return await self._service.refresh_playlists(user_id, session)
        except (TokenNotFoundError, TokenRefreshError, SpotifyAuthError) as exc:
            logger.warning("Auth failure refreshing playlists for user %d: %s", user_id, exc)
            raise HTTPException(status_code=401, detail="Spotify authentication failed") from exc
        except SpotifyRateLimitError as exc:
            raise HTTPException(status_code=429, detail="Spotify rate limit exceeded, try again later") from exc
        except SpotifyClientError as exc:
            logger.error("Spotify client error refreshing playlists for user %d: %s", user_id, exc)
            raise HTTPException(status_code=502, detail="Spotify service unavailable") from exc

    async def playlist_detail(
        self,
        spotify_playlist_id: str,
        user_id: RequireOwnDataView,
        session: DBSession,
    ) -> PlaylistDetail:
        result = await self._service.get_playlist_detail(user_id, spotify_playlist_id, session)
        if result is None:
            raise HTTPException(status_code=404, detail="Playlist not found")
        return result

    async def fetch_playlist_tracks(
        self,
        spotify_playlist_id: str,
        user_id: RequireOwnDataView,
        session: DBSession,
    ) -> PlaylistDetail:
        """Fetch tracks from Spotify and cache them."""
        try:
            result = await self._service.fetch_playlist_tracks(user_id, spotify_playlist_id, session)
        except (TokenNotFoundError, TokenRefreshError, SpotifyAuthError) as exc:
            logger.warning("Auth failure fetching tracks for playlist %s: %s", spotify_playlist_id, exc)
            raise HTTPException(status_code=401, detail="Spotify authentication failed") from exc
        except SpotifyRateLimitError as exc:
            raise HTTPException(status_code=429, detail="Spotify rate limit exceeded, try again later") from exc
        except SpotifyRequestError as exc:
            status = 404 if exc.status_code in (403, 404) else 502
            raise HTTPException(status_code=status, detail=f"Spotify error: {exc.detail}") from exc
        except SpotifyClientError as exc:
            logger.error("Spotify error fetching tracks for playlist %s: %s", spotify_playlist_id, exc)
            raise HTTPException(status_code=502, detail="Spotify service unavailable") from exc
        if result is None:
            raise HTTPException(status_code=404, detail="Playlist not found")
        return result

    async def taste_profile(self, user_id: RequireOwnDataView, session: DBSession) -> TasteProfileWithEvents:
        """Get the user's taste profile with recent preference events."""
        return await self._service.get_taste_profile(user_id, session)

    async def update_taste_profile(
        self, body: TasteProfilePatch, user_id: RequireOwnDataView, session: DBSession
    ) -> TasteProfileResponse:
        """Update taste profile via JSON merge-patch. Creates if missing."""
        if not body.patch:
            raise HTTPException(status_code=422, detail="patch must be a non-empty object")
        return await self._service.update_taste_profile(user_id, body.patch, body.reason, session)

    async def clear_taste_profile(self, user_id: RequireOwnDataView, session: DBSession) -> dict[str, bool]:
        """Delete the user's taste profile, resetting to version 0."""
        await self._service.clear_taste_profile(user_id, session)
        return {"cleared": True}

    async def preference_events(
        self,
        user_id: RequireOwnDataView,
        session: DBSession,
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> PaginatedPreferenceEvents:
        """Get paginated preference event history."""
        return await self._service.get_preference_events(user_id, session, limit=limit, offset=offset)

    async def memory_playlists(
        self,
        user_id: RequireOwnDataView,
        session: DBSession,
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> PaginatedMemoryPlaylists:
        """List assistant-tracked playlists from the memory ledger."""
        return await self._service.get_memory_playlists(user_id, session, limit=limit, offset=offset)

    async def memory_playlist_detail(
        self,
        playlist_id: str,
        user_id: RequireOwnDataView,
        session: DBSession,
    ) -> MemoryPlaylistDetail:
        """Get a memory playlist with track IDs and recent events."""
        result = await self._service.get_memory_playlist_detail(user_id, playlist_id, session)
        if result is None:
            raise HTTPException(status_code=404, detail="Memory playlist not found")
        return result

    async def memory_playlist_events(
        self,
        playlist_id: str,
        user_id: RequireOwnDataView,
        session: DBSession,
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> PaginatedMemoryPlaylistEvents:
        """Get paginated mutation events for a memory playlist."""
        result = await self._service.get_memory_playlist_events(
            user_id, playlist_id, session, limit=limit, offset=offset
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Memory playlist not found")
        return result

    async def tracks(
        self,
        user_id: RequireOwnDataView,
        session: DBSession,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        sort: str = Query(default="play_count"),
        q: str | None = Query(default=None),
        days: int | None = Query(default=None, ge=1),
    ) -> PaginatedTracks:
        """Browse all tracks with pagination, search, sort, and optional time window."""
        return await self._service.get_tracks(user_id, session, limit=limit, offset=offset, sort=sort, q=q, days=days)

    async def artists(
        self,
        user_id: RequireOwnDataView,
        session: DBSession,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        sort: str = Query(default="play_count"),
        q: str | None = Query(default=None),
        days: int | None = Query(default=None, ge=1),
    ) -> PaginatedArtists:
        """Browse all artists with pagination, search, sort, and optional time window."""
        return await self._service.get_artists(user_id, session, limit=limit, offset=offset, sort=sort, q=q, days=days)

    async def track_detail(self, track_id: int, user_id: RequireOwnDataView, session: DBSession) -> TrackDetail:
        """Get detailed track information with play stats and enrichment."""
        result = await self._service.get_track_detail(user_id, track_id, session)
        if result is None:
            raise HTTPException(status_code=404, detail="Track not found")
        return result

    async def artist_detail(self, artist_id: int, user_id: RequireOwnDataView, session: DBSession) -> ArtistDetail:
        """Get detailed artist information with play stats and enrichment."""
        result = await self._service.get_artist_detail(user_id, artist_id, session)
        if result is None:
            raise HTTPException(status_code=404, detail="Artist not found")
        return result

    async def album_detail(self, album_spotify_id: str, user_id: RequireOwnDataView, session: DBSession) -> AlbumDetail:
        """Get album detail with per-track play stats and enrichment."""
        result = await self._service.get_album_detail(user_id, album_spotify_id, session)
        if result is None:
            raise HTTPException(status_code=404, detail="Album not found")
        return result

    async def list_tokens(self, user_id: RequireOwnDataView, session: DBSession) -> TokenListResponse:
        """List all active API tokens for the user."""
        tokens = await ApiTokenService.list_tokens(user_id, session)
        return TokenListResponse(
            items=[
                TokenListItem(
                    token_id=t.id,
                    name=t.name,
                    prefix=t.token_prefix,
                    created_at=t.created_at,
                    last_used_at=t.last_used_at,
                )
                for t in tokens
            ]
        )

    async def create_token(
        self, body: CreateTokenRequest, user_id: RequireOwnDataView, session: DBSession
    ) -> CreatedTokenResponse:
        """Create a new API token. The plaintext token is returned only once."""
        created = await ApiTokenService.create(user_id, body.name.strip(), session)
        return CreatedTokenResponse(
            token_id=created.token_id,
            name=created.name,
            token=created.token,
            prefix=created.prefix,
            created_at=created.created_at,
        )

    async def revoke_token(self, token_id: int, user_id: RequireOwnDataView, session: DBSession) -> None:
        """Revoke an API token (soft delete)."""
        revoked = await ApiTokenService.revoke(token_id, user_id, session)
        if not revoked:
            raise HTTPException(status_code=404, detail="Token not found")


_instance = ExplorerRouter()
router = _instance.router
