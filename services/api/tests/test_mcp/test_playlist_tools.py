"""Tests for spotify info + playlist tools invoked through the MCP dispatcher."""

from collections.abc import AsyncGenerator, Generator
from unittest.mock import AsyncMock, patch

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.dependencies import db_manager
from app.main import app
from app.settings import AppSettings, get_settings
from shared.db.base import Base
from shared.db.models.user import SpotifyToken, User
from shared.spotify.models import (
    SpotifyAlbumFull,
    SpotifyAlbumSimplified,
    SpotifyAlbumTracksPage,
    SpotifyArtistFull,
    SpotifyArtistSimplified,
    SpotifyImage,
    SpotifyPlaylist,
    SpotifyPlaylistOwner,
    SpotifyPlaylistSimplified,
    SpotifyPlaylistTrackItem,
    SpotifyPlaylistTracks,
    SpotifySnapshotResponse,
    SpotifyTrack,
    SpotifyTrackSimplified,
    UserPlaylistsResponse,
)

TEST_FERNET_KEY = Fernet.generate_key().decode()

_FULL_SCOPES = (
    "user-read-recently-played user-top-read user-read-email user-read-private "
    "playlist-read-private playlist-modify-public playlist-modify-private"
)


def _test_settings() -> AppSettings:
    return AppSettings(
        SPOTIFY_CLIENT_ID="test",
        SPOTIFY_CLIENT_SECRET="test",
        TOKEN_ENCRYPTION_KEY=TEST_FERNET_KEY,
        RATE_LIMIT_MCP_PER_MINUTE=10000,
    )


@pytest.fixture
async def async_engine() -> AsyncGenerator[AsyncEngine]:
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def override_deps(async_engine: AsyncEngine) -> Generator[None]:
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    async def _override() -> AsyncGenerator[AsyncSession]:
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[db_manager.dependency] = _override
    app.dependency_overrides[get_settings] = _test_settings
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client(override_deps: None) -> TestClient:
    return TestClient(app)


@pytest.fixture
async def seeded_user(async_engine: AsyncEngine) -> int:
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        user = User(spotify_user_id="pluser", display_name="Playlist User")
        session.add(user)
        await session.flush()
        uid = user.id
        await session.commit()
    return uid


@pytest.fixture
async def seeded_user_with_scopes(async_engine: AsyncEngine) -> int:
    """User with a SpotifyToken that has full playlist write scopes."""
    encryptor = Fernet(TEST_FERNET_KEY.encode())
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        user = User(spotify_user_id="plwriter", display_name="Playlist Writer")
        session.add(user)
        await session.flush()
        token = SpotifyToken(
            user_id=user.id,
            encrypted_refresh_token=encryptor.encrypt(b"fake-refresh").decode(),
            access_token="fake-access",
            scope=_FULL_SCOPES,
        )
        session.add(token)
        await session.flush()
        uid = user.id
        await session.commit()
    return uid


@pytest.fixture
async def seeded_user_no_write_scopes(async_engine: AsyncEngine) -> int:
    """User with a SpotifyToken that has only read scopes (no playlist-modify)."""
    encryptor = Fernet(TEST_FERNET_KEY.encode())
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        user = User(spotify_user_id="plreader", display_name="Playlist Reader")
        session.add(user)
        await session.flush()
        token = SpotifyToken(
            user_id=user.id,
            encrypted_refresh_token=encryptor.encrypt(b"fake-refresh").decode(),
            access_token="fake-access",
            scope="user-read-recently-played playlist-read-private",
        )
        session.add(token)
        await session.flush()
        uid = user.id
        await session.commit()
    return uid


# ---------------------------------------------------------------------------
# spotify.get_track
# ---------------------------------------------------------------------------


def test_get_track(client: TestClient, seeded_user: int) -> None:
    mock_track = SpotifyTrack(
        id="t1",
        name="Test Track",
        duration_ms=240000,
        popularity=72,
        explicit=False,
        artists=[SpotifyArtistSimplified(id="a1", name="Artist One")],
        album=SpotifyAlbumSimplified(id="al1", name="Album One"),
        external_urls={"spotify": "https://open.spotify.com/track/t1"},
    )

    with patch(
        "app.mcp.tools.spotify_tools.SpotifyToolHandlers._get_client",
        new_callable=AsyncMock,
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_client.get_track = AsyncMock(return_value=mock_track)
        mock_get_client.return_value = mock_client

        resp = client.post(
            "/mcp/call",
            json={"tool": "spotify.get_track", "user_id": seeded_user, "track_id": "t1"},
        )
        data = resp.json()
        assert data["success"] is True
        assert data["result"]["id"] == "t1"
        assert data["result"]["name"] == "Test Track"
        assert data["result"]["duration_ms"] == 240000
        assert data["result"]["popularity"] == 72
        assert data["result"]["artists"][0]["name"] == "Artist One"
        assert data["result"]["album"]["name"] == "Album One"


# ---------------------------------------------------------------------------
# spotify.get_artist
# ---------------------------------------------------------------------------


def test_get_artist(client: TestClient, seeded_user: int) -> None:
    mock_artist = SpotifyArtistFull(
        id="a1",
        name="Artist One",
        genres=["indie rock", "alternative"],
        popularity=85,
        followers={"total": 500000},
        images=[SpotifyImage(url="https://img.spotify.com/a1.jpg", height=640, width=640)],
        external_urls={"spotify": "https://open.spotify.com/artist/a1"},
    )

    with patch(
        "app.mcp.tools.spotify_tools.SpotifyToolHandlers._get_client",
        new_callable=AsyncMock,
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_client.get_artist = AsyncMock(return_value=mock_artist)
        mock_get_client.return_value = mock_client

        resp = client.post(
            "/mcp/call",
            json={"tool": "spotify.get_artist", "user_id": seeded_user, "artist_id": "a1"},
        )
        data = resp.json()
        assert data["success"] is True
        assert data["result"]["id"] == "a1"
        assert data["result"]["name"] == "Artist One"
        assert data["result"]["genres"] == ["indie rock", "alternative"]
        assert data["result"]["popularity"] == 85
        assert data["result"]["followers"] == {"total": 500000}
        assert len(data["result"]["images"]) == 1


# ---------------------------------------------------------------------------
# spotify.get_album
# ---------------------------------------------------------------------------


def test_get_album(client: TestClient, seeded_user: int) -> None:
    mock_album = SpotifyAlbumFull(
        id="al1",
        name="Test Album",
        album_type="album",
        release_date="2025-06-15",
        total_tracks=10,
        artists=[SpotifyArtistSimplified(id="a1", name="Artist One")],
        genres=["rock"],
        popularity=60,
        label="Test Records",
        tracks=SpotifyAlbumTracksPage(
            items=[
                SpotifyTrackSimplified(
                    id="t1",
                    name="Track 1",
                    track_number=1,
                    duration_ms=180000,
                    artists=[SpotifyArtistSimplified(id="a1", name="Artist One")],
                ),
                SpotifyTrackSimplified(
                    id="t2",
                    name="Track 2",
                    track_number=2,
                    duration_ms=210000,
                    artists=[SpotifyArtistSimplified(id="a1", name="Artist One")],
                ),
            ],
            total=10,
        ),
        images=[SpotifyImage(url="https://img.spotify.com/al1.jpg")],
        external_urls={"spotify": "https://open.spotify.com/album/al1"},
    )

    with patch(
        "app.mcp.tools.spotify_tools.SpotifyToolHandlers._get_client",
        new_callable=AsyncMock,
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_client.get_album = AsyncMock(return_value=mock_album)
        mock_get_client.return_value = mock_client

        resp = client.post(
            "/mcp/call",
            json={"tool": "spotify.get_album", "user_id": seeded_user, "album_id": "al1"},
        )
        data = resp.json()
        assert data["success"] is True
        assert data["result"]["id"] == "al1"
        assert data["result"]["name"] == "Test Album"
        assert data["result"]["total_tracks"] == 10
        assert data["result"]["label"] == "Test Records"
        assert len(data["result"]["tracks"]) == 2
        assert data["result"]["tracks"][0]["name"] == "Track 1"
        assert data["result"]["tracks"][0]["track_number"] == 1


# ---------------------------------------------------------------------------
# spotify.list_playlists
# ---------------------------------------------------------------------------


def test_list_playlists(client: TestClient, seeded_user: int) -> None:
    mock_response = UserPlaylistsResponse(
        items=[
            SpotifyPlaylistSimplified(
                id="pl1",
                name="My Playlist",
                public=True,
                tracks={"total": 42},
                owner=SpotifyPlaylistOwner(id="pluser", display_name="Playlist User"),
            ),
            SpotifyPlaylistSimplified(
                id="pl2",
                name="Private Jams",
                public=False,
                tracks={"total": 10},
                owner=SpotifyPlaylistOwner(id="pluser", display_name="Playlist User"),
            ),
        ],
        total=2,
    )

    with patch(
        "app.mcp.tools.playlist_tools.PlaylistToolHandlers._get_client",
        new_callable=AsyncMock,
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_client.get_user_playlists = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        resp = client.post(
            "/mcp/call",
            json={"tool": "spotify.list_playlists", "user_id": seeded_user},
        )
        data = resp.json()
        assert data["success"] is True
        assert len(data["result"]) == 2
        assert data["result"][0]["id"] == "pl1"
        assert data["result"][0]["name"] == "My Playlist"
        assert data["result"][0]["public"] is True
        assert data["result"][0]["tracks_total"] == 42
        assert data["result"][1]["id"] == "pl2"
        assert data["result"][1]["public"] is False


# ---------------------------------------------------------------------------
# spotify.get_playlist
# ---------------------------------------------------------------------------


def test_get_playlist(client: TestClient, seeded_user: int) -> None:
    mock_playlist = SpotifyPlaylist(
        id="pl1",
        name="My Playlist",
        description="A great playlist",
        public=True,
        owner=SpotifyPlaylistOwner(id="pluser", display_name="Playlist User"),
        snapshot_id="snap123",
        external_urls={"spotify": "https://open.spotify.com/playlist/pl1"},
        tracks=SpotifyPlaylistTracks(
            items=[],
            total=2,
        ),
    )

    # get_playlist_all_tracks returns the full paginated track list
    mock_all_tracks = [
        SpotifyPlaylistTrackItem(
            track=SpotifyTrack(
                id="t1",
                name="Track 1",
                artists=[SpotifyArtistSimplified(id="a1", name="Artist One")],
            ),
            added_at="2025-01-15T10:00:00Z",
        ),
        SpotifyPlaylistTrackItem(
            track=SpotifyTrack(
                id="t2",
                name="Track 2",
                artists=[SpotifyArtistSimplified(id="a2", name="Artist Two")],
            ),
            added_at="2025-01-16T12:00:00Z",
        ),
    ]

    with patch(
        "app.mcp.tools.playlist_tools.PlaylistToolHandlers._get_client",
        new_callable=AsyncMock,
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_client.get_playlist = AsyncMock(return_value=mock_playlist)
        mock_client.get_playlist_all_tracks = AsyncMock(return_value=mock_all_tracks)
        mock_get_client.return_value = mock_client

        resp = client.post(
            "/mcp/call",
            json={"tool": "spotify.get_playlist", "user_id": seeded_user, "playlist_id": "pl1"},
        )
        data = resp.json()
        assert data["success"] is True
        assert data["result"]["id"] == "pl1"
        assert data["result"]["name"] == "My Playlist"
        assert data["result"]["description"] == "A great playlist"
        assert data["result"]["public"] is True
        assert data["result"]["owner"] == "Playlist User"
        assert data["result"]["tracks_total"] == 2
        assert len(data["result"]["tracks"]) == 2
        assert data["result"]["tracks"][0]["id"] == "t1"
        assert data["result"]["tracks"][0]["artists"][0]["name"] == "Artist One"
        assert data["result"]["snapshot_id"] == "snap123"
        mock_client.get_playlist_all_tracks.assert_called_once_with("pl1")


def test_get_playlist_stale_cache_without_tracks(client: TestClient, seeded_user: int) -> None:
    """get_playlist fetches tracks even when cache has a matching snapshot but no tracks.

    Regression test: list_playlists caches snapshot_ids without track rows.
    A subsequent get_playlist must NOT return the empty-tracks cache entry.
    """
    mock_playlist = SpotifyPlaylist(
        id="pl_stale",
        name="Stale Cache Playlist",
        public=True,
        owner=SpotifyPlaylistOwner(id="pluser", display_name="Playlist User"),
        snapshot_id="snap_stale",
        external_urls={},
        tracks=SpotifyPlaylistTracks(items=[], total=3),
    )

    mock_all_tracks = [
        SpotifyPlaylistTrackItem(
            track=SpotifyTrack(
                id=f"t{i}",
                name=f"Track {i}",
                artists=[SpotifyArtistSimplified(id="a1", name="Artist")],
            ),
            added_at="2025-01-01T00:00:00Z",
        )
        for i in range(3)
    ]

    with patch(
        "app.mcp.tools.playlist_tools.PlaylistToolHandlers._get_client",
        new_callable=AsyncMock,
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_client.get_playlist = AsyncMock(return_value=mock_playlist)
        mock_client.get_playlist_all_tracks = AsyncMock(return_value=mock_all_tracks)
        mock_get_client.return_value = mock_client

        # First call list_playlists to seed cache with snapshot_id but NO tracks
        mock_client.get_user_playlists = AsyncMock(
            return_value=UserPlaylistsResponse(
                items=[
                    SpotifyPlaylistSimplified(
                        id="pl_stale",
                        name="Stale Cache Playlist",
                        public=True,
                        owner=SpotifyPlaylistOwner(id="pluser", display_name="Playlist User"),
                        snapshot_id="snap_stale",
                        tracks={"total": 3},
                    )
                ],
                total=1,
            )
        )
        client.post(
            "/mcp/call",
            json={"tool": "spotify.list_playlists", "user_id": seeded_user, "limit": 50},
        )

        # Now get_playlist — should NOT return empty tracks from stale cache
        resp = client.post(
            "/mcp/call",
            json={"tool": "spotify.get_playlist", "user_id": seeded_user, "playlist_id": "pl_stale"},
        )
        data = resp.json()
        assert data["success"] is True
        assert len(data["result"]["tracks"]) == 3, (
            f"Expected 3 tracks but got {len(data['result']['tracks'])} — stale cache served empty tracks"
        )
        # Confirm pagination was actually called (not served from cache)
        mock_client.get_playlist_all_tracks.assert_called_once_with("pl_stale")


def test_get_playlist_403_fallback(client: TestClient, seeded_user: int) -> None:
    """get_playlist falls back to cached metadata when Spotify returns 403.

    Spotify may return 403 for GET /playlists/{id} in dev mode while
    GET /playlists/{id}/tracks still works. The handler should use cached
    metadata from list_playlists and fetch tracks via pagination.
    """
    from shared.spotify.exceptions import SpotifyRequestError

    mock_all_tracks = [
        SpotifyPlaylistTrackItem(
            track=SpotifyTrack(
                id=f"t{i}",
                name=f"Track {i}",
                artists=[SpotifyArtistSimplified(id="a1", name="Artist")],
            ),
            added_at="2025-01-01T00:00:00Z",
        )
        for i in range(5)
    ]

    with patch(
        "app.mcp.tools.playlist_tools.PlaylistToolHandlers._get_client",
        new_callable=AsyncMock,
    ) as mock_get_client:
        mock_client = AsyncMock()
        # Simulate Spotify 403 on GET /playlists/{id}
        mock_client.get_playlist = AsyncMock(side_effect=SpotifyRequestError(403, "Forbidden"))
        mock_client.get_playlist_all_tracks = AsyncMock(return_value=mock_all_tracks)
        mock_get_client.return_value = mock_client

        # Seed cache with metadata via list_playlists first
        mock_client.get_user_playlists = AsyncMock(
            return_value=UserPlaylistsResponse(
                items=[
                    SpotifyPlaylistSimplified(
                        id="pl_403",
                        name="Forbidden Playlist",
                        public=True,
                        owner=SpotifyPlaylistOwner(id="user1", display_name="User One"),
                        snapshot_id="snap_403",
                        tracks={"total": 5},
                    )
                ],
                total=1,
            )
        )
        client.post(
            "/mcp/call",
            json={"tool": "spotify.list_playlists", "user_id": seeded_user, "limit": 50},
        )

        # Now get_playlist — should gracefully handle 403 and return tracks
        resp = client.post(
            "/mcp/call",
            json={"tool": "spotify.get_playlist", "user_id": seeded_user, "playlist_id": "pl_403"},
        )
        data = resp.json()
        assert data["success"] is True
        assert data["result"]["name"] == "Forbidden Playlist"
        assert len(data["result"]["tracks"]) == 5
        mock_client.get_playlist_all_tracks.assert_called_once_with("pl_403")


def test_get_playlist_403_both_endpoints(client: TestClient, seeded_user_with_scopes: int) -> None:
    """get_playlist returns metadata with restriction notice when both endpoints 403.

    In Spotify dev mode, both GET /playlists/{id} and GET /playlists/{id}/tracks
    may return 403 (Extended Quota Mode required). The handler should return
    cached metadata with a clear restriction message, including a backfill hint.
    """
    from app.mcp.tools.playlist_tools import _instance as playlist_instance
    from shared.spotify.exceptions import SpotifyEmbedError, SpotifyRequestError

    with patch(
        "app.mcp.tools.playlist_tools.PlaylistToolHandlers._get_client",
        new_callable=AsyncMock,
    ) as mock_get_client:
        mock_client = AsyncMock()
        # Both endpoints return 403
        mock_client.get_playlist = AsyncMock(side_effect=SpotifyRequestError(403, "Forbidden"))
        mock_client.get_playlist_all_tracks = AsyncMock(side_effect=SpotifyRequestError(403, "Forbidden"))
        mock_get_client.return_value = mock_client

        # Seed cache with metadata via list_playlists first
        mock_client.get_user_playlists = AsyncMock(
            return_value=UserPlaylistsResponse(
                items=[
                    SpotifyPlaylistSimplified(
                        id="pl_full403",
                        name="Fully Restricted",
                        public=True,
                        owner=SpotifyPlaylistOwner(id="user1", display_name="User One"),
                        snapshot_id="snap_full403",
                        tracks={"total": 10},
                    )
                ],
                total=1,
            )
        )
        client.post(
            "/mcp/call",
            json={"tool": "spotify.list_playlists", "user_id": seeded_user_with_scopes, "limit": 50},
        )

        # get_playlist should return metadata + restriction notice with backfill hint
        # Mock embed fallback to also fail
        with patch.object(
            playlist_instance._embed_client,
            "fetch_playlist_tracks",
            new_callable=AsyncMock,
            side_effect=SpotifyEmbedError("Embed failed"),
        ):
            resp = client.post(
                "/mcp/call",
                json={"tool": "spotify.get_playlist", "user_id": seeded_user_with_scopes, "playlist_id": "pl_full403"},
            )
        data = resp.json()
        assert data["success"] is True
        assert data["result"]["name"] == "Fully Restricted"
        assert data["result"]["tracks"] == []
        assert data["result"]["tracks_restricted"] is True
        assert "memory.backfill_playlist" in data["result"]["tracks_restricted_reason"]


def test_get_playlist_403_missing_read_private_scope(client: TestClient, seeded_user: int) -> None:
    """When the token lacks playlist-read-private, the reason says to re-authorize.

    seeded_user has no SpotifyToken at all, so the scope check returns empty → re-auth hint.
    """
    from app.mcp.tools.playlist_tools import _instance as playlist_instance
    from shared.spotify.exceptions import SpotifyEmbedError, SpotifyRequestError

    with patch(
        "app.mcp.tools.playlist_tools.PlaylistToolHandlers._get_client",
        new_callable=AsyncMock,
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_client.get_playlist = AsyncMock(side_effect=SpotifyRequestError(403, "Forbidden"))
        mock_client.get_playlist_all_tracks = AsyncMock(side_effect=SpotifyRequestError(403, "Forbidden"))
        mock_client.get_user_playlists = AsyncMock(
            return_value=UserPlaylistsResponse(
                items=[
                    SpotifyPlaylistSimplified(
                        id="pl_missing_scope",
                        name="Private Playlist",
                        public=False,
                        owner=SpotifyPlaylistOwner(id="user1", display_name="User One"),
                        snapshot_id="snap_missing_scope",
                        tracks={"total": 5},
                    )
                ],
                total=1,
            )
        )
        mock_get_client.return_value = mock_client

        # Seed cache
        client.post(
            "/mcp/call",
            json={"tool": "spotify.list_playlists", "user_id": seeded_user, "limit": 50},
        )

        with patch.object(
            playlist_instance._embed_client,
            "fetch_playlist_tracks",
            new_callable=AsyncMock,
            side_effect=SpotifyEmbedError("Embed failed"),
        ):
            resp = client.post(
                "/mcp/call",
                json={
                    "tool": "spotify.get_playlist",
                    "user_id": seeded_user,
                    "playlist_id": "pl_missing_scope",
                },
            )
        data = resp.json()
        assert data["success"] is True
        assert data["result"]["tracks_restricted"] is True
        assert "re-authorize" in data["result"]["tracks_restricted_reason"]
        assert "playlist-read-private" in data["result"]["tracks_restricted_reason"]


def test_get_playlist_403_no_cache(client: TestClient, seeded_user: int) -> None:
    """get_playlist raises error when 403 and no cached metadata available."""
    from shared.spotify.exceptions import SpotifyRequestError

    with patch(
        "app.mcp.tools.playlist_tools.PlaylistToolHandlers._get_client",
        new_callable=AsyncMock,
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_client.get_playlist = AsyncMock(side_effect=SpotifyRequestError(403, "Forbidden"))
        mock_client.get_playlist_all_tracks = AsyncMock(side_effect=SpotifyRequestError(403, "Forbidden"))
        mock_get_client.return_value = mock_client

        # No list_playlists call — no cache seeded
        resp = client.post(
            "/mcp/call",
            json={"tool": "spotify.get_playlist", "user_id": seeded_user, "playlist_id": "pl_nocache"},
        )
        data = resp.json()
        assert data["success"] is False
        assert "no cached metadata" in data["error"].lower()


def test_get_playlist_large_paginated(client: TestClient, seeded_user: int) -> None:
    """get_playlist returns all tracks even when the playlist has more than one page."""
    mock_playlist = SpotifyPlaylist(
        id="bigpl",
        name="Big Playlist",
        public=True,
        owner=SpotifyPlaylistOwner(id="pluser", display_name="Playlist User"),
        snapshot_id="snap_big",
        external_urls={},
        tracks=SpotifyPlaylistTracks(items=[], total=150),
    )

    # Simulate 150 tracks returned by paginated fetch
    mock_all_tracks = [
        SpotifyPlaylistTrackItem(
            track=SpotifyTrack(
                id=f"t{i}",
                name=f"Track {i}",
                artists=[SpotifyArtistSimplified(id="a1", name="Artist")],
            ),
            added_at="2025-01-01T00:00:00Z",
        )
        for i in range(150)
    ]

    with patch(
        "app.mcp.tools.playlist_tools.PlaylistToolHandlers._get_client",
        new_callable=AsyncMock,
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_client.get_playlist = AsyncMock(return_value=mock_playlist)
        mock_client.get_playlist_all_tracks = AsyncMock(return_value=mock_all_tracks)
        mock_get_client.return_value = mock_client

        resp = client.post(
            "/mcp/call",
            json={"tool": "spotify.get_playlist", "user_id": seeded_user, "playlist_id": "bigpl"},
        )
        data = resp.json()
        assert data["success"] is True
        assert data["result"]["tracks_total"] == 150
        assert len(data["result"]["tracks"]) == 150
        assert data["result"]["tracks"][0]["id"] == "t0"
        assert data["result"]["tracks"][149]["id"] == "t149"


# ---------------------------------------------------------------------------
# spotify.create_playlist
# ---------------------------------------------------------------------------


def test_create_playlist(client: TestClient, seeded_user_with_scopes: int) -> None:
    mock_playlist = SpotifyPlaylist(
        id="newpl1",
        name="New Playlist",
        description="Created by ChatGPT",
        public=False,
        external_urls={"spotify": "https://open.spotify.com/playlist/newpl1"},
    )

    with patch(
        "app.mcp.tools.playlist_tools.PlaylistToolHandlers._get_client",
        new_callable=AsyncMock,
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_client.create_playlist = AsyncMock(return_value=mock_playlist)
        mock_get_client.return_value = mock_client

        resp = client.post(
            "/mcp/call",
            json={
                "tool": "spotify.create_playlist",
                "user_id": seeded_user_with_scopes,
                "name": "New Playlist",
                "description": "Created by ChatGPT",
                "public": False,
            },
        )
        data = resp.json()
        assert data["success"] is True
        assert data["result"]["id"] == "newpl1"
        assert data["result"]["name"] == "New Playlist"
        assert data["result"]["public"] is False
        mock_client.create_playlist.assert_called_once_with(
            name="New Playlist",
            description="Created by ChatGPT",
            public=False,
        )


def test_create_playlist_missing_scopes(client: TestClient, seeded_user_no_write_scopes: int) -> None:
    resp = client.post(
        "/mcp/call",
        json={
            "tool": "spotify.create_playlist",
            "user_id": seeded_user_no_write_scopes,
            "name": "Should Fail",
        },
    )
    data = resp.json()
    assert data["success"] is False
    assert "Missing required scopes" in data["error"]
    assert "re-authorize" in data["error"]


# ---------------------------------------------------------------------------
# spotify.add_tracks
# ---------------------------------------------------------------------------


def test_add_tracks(client: TestClient, seeded_user_with_scopes: int) -> None:
    mock_snap = SpotifySnapshotResponse(snapshot_id="snap456")

    with patch(
        "app.mcp.tools.playlist_tools.PlaylistToolHandlers._get_client",
        new_callable=AsyncMock,
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_client.add_tracks_to_playlist = AsyncMock(return_value=mock_snap)
        mock_get_client.return_value = mock_client

        resp = client.post(
            "/mcp/call",
            json={
                "tool": "spotify.add_tracks",
                "user_id": seeded_user_with_scopes,
                "playlist_id": "pl1",
                "track_ids": ["t1", "t2", "t3"],
            },
        )
        data = resp.json()
        assert data["success"] is True
        assert data["result"]["snapshot_id"] == "snap456"
        assert data["result"]["tracks_added"] == 3
        # Verify IDs were converted to URIs
        mock_client.add_tracks_to_playlist.assert_called_once_with(
            "pl1",
            ["spotify:track:t1", "spotify:track:t2", "spotify:track:t3"],
        )


def test_add_tracks_empty_list(client: TestClient, seeded_user_with_scopes: int) -> None:
    resp = client.post(
        "/mcp/call",
        json={
            "tool": "spotify.add_tracks",
            "user_id": seeded_user_with_scopes,
            "playlist_id": "pl1",
            "track_ids": [],
        },
    )
    data = resp.json()
    assert data["success"] is False
    assert "must not be empty" in data["error"]


def test_add_tracks_over_100(client: TestClient, seeded_user_with_scopes: int) -> None:
    resp = client.post(
        "/mcp/call",
        json={
            "tool": "spotify.add_tracks",
            "user_id": seeded_user_with_scopes,
            "playlist_id": "pl1",
            "track_ids": [f"t{i}" for i in range(101)],
        },
    )
    data = resp.json()
    assert data["success"] is False
    assert "Maximum 100" in data["error"]


# ---------------------------------------------------------------------------
# spotify.remove_tracks
# ---------------------------------------------------------------------------


def test_remove_tracks(client: TestClient, seeded_user_with_scopes: int) -> None:
    mock_snap = SpotifySnapshotResponse(snapshot_id="snap789")

    with patch(
        "app.mcp.tools.playlist_tools.PlaylistToolHandlers._get_client",
        new_callable=AsyncMock,
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_client.remove_tracks_from_playlist = AsyncMock(return_value=mock_snap)
        mock_get_client.return_value = mock_client

        resp = client.post(
            "/mcp/call",
            json={
                "tool": "spotify.remove_tracks",
                "user_id": seeded_user_with_scopes,
                "playlist_id": "pl1",
                "track_ids": ["t1"],
            },
        )
        data = resp.json()
        assert data["success"] is True
        assert data["result"]["snapshot_id"] == "snap789"
        assert data["result"]["tracks_removed"] == 1
        mock_client.remove_tracks_from_playlist.assert_called_once_with(
            "pl1",
            ["spotify:track:t1"],
        )


def test_remove_tracks_missing_scopes(client: TestClient, seeded_user_no_write_scopes: int) -> None:
    resp = client.post(
        "/mcp/call",
        json={
            "tool": "spotify.remove_tracks",
            "user_id": seeded_user_no_write_scopes,
            "playlist_id": "pl1",
            "track_ids": ["t1"],
        },
    )
    data = resp.json()
    assert data["success"] is False
    assert "Missing required scopes" in data["error"]


# ---------------------------------------------------------------------------
# spotify.update_playlist
# ---------------------------------------------------------------------------


def test_update_playlist(client: TestClient, seeded_user_with_scopes: int) -> None:
    with patch(
        "app.mcp.tools.playlist_tools.PlaylistToolHandlers._get_client",
        new_callable=AsyncMock,
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_client.update_playlist_details = AsyncMock(return_value=None)
        mock_get_client.return_value = mock_client

        resp = client.post(
            "/mcp/call",
            json={
                "tool": "spotify.update_playlist",
                "user_id": seeded_user_with_scopes,
                "playlist_id": "pl1",
                "name": "Renamed Playlist",
                "description": "New description",
            },
        )
        data = resp.json()
        assert data["success"] is True
        assert data["result"]["updated"] is True
        assert data["result"]["playlist_id"] == "pl1"
        mock_client.update_playlist_details.assert_called_once_with(
            "pl1",
            name="Renamed Playlist",
            description="New description",
            public=None,
        )


def test_update_playlist_no_fields(client: TestClient, seeded_user_with_scopes: int) -> None:
    resp = client.post(
        "/mcp/call",
        json={
            "tool": "spotify.update_playlist",
            "user_id": seeded_user_with_scopes,
            "playlist_id": "pl1",
        },
    )
    data = resp.json()
    assert data["success"] is False
    assert "At least one of" in data["error"]


def test_create_playlist_no_token(client: TestClient, seeded_user: int) -> None:
    """User without any SpotifyToken at all gets a clear error."""
    resp = client.post(
        "/mcp/call",
        json={
            "tool": "spotify.create_playlist",
            "user_id": seeded_user,
            "name": "Should Fail",
        },
    )
    data = resp.json()
    assert data["success"] is False
    assert "No token found" in data["error"]


# ---------------------------------------------------------------------------
# Embed fallback tests
# ---------------------------------------------------------------------------


def test_get_playlist_403_embed_fallback_success(client: TestClient, seeded_user: int) -> None:
    """get_playlist falls back to embed endpoint when API returns 403, and returns tracks."""
    from app.mcp.tools.playlist_tools import _instance as playlist_instance
    from shared.spotify.exceptions import SpotifyRequestError
    from shared.spotify.models import EmbedTrackItem

    with patch(
        "app.mcp.tools.playlist_tools.PlaylistToolHandlers._get_client",
        new_callable=AsyncMock,
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_client.get_playlist = AsyncMock(side_effect=SpotifyRequestError(403, "Forbidden"))
        mock_client.get_playlist_all_tracks = AsyncMock(side_effect=SpotifyRequestError(403, "Forbidden"))
        mock_get_client.return_value = mock_client

        # Seed cache via list_playlists
        mock_client.get_user_playlists = AsyncMock(
            return_value=UserPlaylistsResponse(
                items=[
                    SpotifyPlaylistSimplified(
                        id="pl_embed",
                        name="Embed Playlist",
                        public=True,
                        owner=SpotifyPlaylistOwner(id="user1", display_name="User One"),
                        snapshot_id="snap_embed",
                        tracks={"total": 2},
                    )
                ],
                total=1,
            )
        )
        client.post(
            "/mcp/call",
            json={"tool": "spotify.list_playlists", "user_id": seeded_user, "limit": 50},
        )

        # Mock embed to return tracks
        embed_tracks = [
            EmbedTrackItem(track_id="t1", name="Track 1", artists=["Artist A"], duration_ms=180000),
            EmbedTrackItem(track_id="t2", name="Track 2", artists=["Artist B", "Artist C"], duration_ms=240000),
        ]
        with patch.object(
            playlist_instance._embed_client,
            "fetch_playlist_tracks",
            new_callable=AsyncMock,
            return_value=embed_tracks,
        ):
            resp = client.post(
                "/mcp/call",
                json={"tool": "spotify.get_playlist", "user_id": seeded_user, "playlist_id": "pl_embed"},
            )

        data = resp.json()
        assert data["success"] is True
        assert data["result"]["name"] == "Embed Playlist"
        assert len(data["result"]["tracks"]) == 2
        assert data["result"]["tracks"][0]["id"] == "t1"
        assert data["result"]["tracks"][0]["name"] == "Track 1"
        assert data["result"]["tracks_source"] == "embed"
        assert "tracks_restricted" not in data["result"]


def test_get_playlist_unavailable_tracks_placeholder(client: TestClient, seeded_user: int) -> None:
    """Unavailable tracks (track=None) are included as placeholder entries."""
    mock_playlist = SpotifyPlaylist(
        id="pl_unavail",
        name="Mixed Playlist",
        public=True,
        owner=SpotifyPlaylistOwner(id="pluser", display_name="Playlist User"),
        snapshot_id="snap_unavail",
        external_urls={},
        tracks=SpotifyPlaylistTracks(items=[], total=3),
    )

    mock_all_tracks = [
        SpotifyPlaylistTrackItem(
            track=SpotifyTrack(
                id="t1",
                name="Track 1",
                artists=[SpotifyArtistSimplified(id="a1", name="Artist One")],
            ),
            added_at="2025-01-15T10:00:00Z",
        ),
        # Unavailable track (removed / not in market)
        SpotifyPlaylistTrackItem(track=None, added_at="2025-01-16T12:00:00Z"),
        SpotifyPlaylistTrackItem(
            track=SpotifyTrack(
                id="t3",
                name="Track 3",
                artists=[SpotifyArtistSimplified(id="a3", name="Artist Three")],
            ),
            added_at="2025-01-17T14:00:00Z",
        ),
    ]

    with patch(
        "app.mcp.tools.playlist_tools.PlaylistToolHandlers._get_client",
        new_callable=AsyncMock,
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_client.get_playlist = AsyncMock(return_value=mock_playlist)
        mock_client.get_playlist_all_tracks = AsyncMock(return_value=mock_all_tracks)
        mock_get_client.return_value = mock_client

        resp = client.post(
            "/mcp/call",
            json={"tool": "spotify.get_playlist", "user_id": seeded_user, "playlist_id": "pl_unavail"},
        )
        data = resp.json()
        assert data["success"] is True
        result = data["result"]
        assert len(result["tracks"]) == 3
        assert result["tracks_returned"] == 3
        assert result["tracks_unavailable"] == 1
        # First track is normal
        assert result["tracks"][0]["id"] == "t1"
        assert "unavailable" not in result["tracks"][0]
        # Second track is placeholder
        assert result["tracks"][1]["id"] is None
        assert result["tracks"][1]["unavailable"] is True
        assert result["tracks"][1]["added_at"] == "2025-01-16T12:00:00Z"
        # Third track is normal
        assert result["tracks"][2]["id"] == "t3"


def test_get_playlist_mismatch_warning(client: TestClient, seeded_user: int) -> None:
    """When tracks_returned != tracks_total, a mismatch warning is included."""
    mock_playlist = SpotifyPlaylist(
        id="pl_mismatch",
        name="Mismatched Playlist",
        public=True,
        owner=SpotifyPlaylistOwner(id="pluser", display_name="Playlist User"),
        snapshot_id="snap_mm",
        external_urls={},
        # Spotify says 5 tracks, but API only returns 3
        tracks=SpotifyPlaylistTracks(items=[], total=5),
    )

    mock_all_tracks = [
        SpotifyPlaylistTrackItem(
            track=SpotifyTrack(id="t1", name="Track 1", artists=[SpotifyArtistSimplified(id="a1", name="A1")]),
            added_at="2025-01-15T10:00:00Z",
        ),
        SpotifyPlaylistTrackItem(track=None, added_at="2025-01-16T12:00:00Z"),
        SpotifyPlaylistTrackItem(
            track=SpotifyTrack(id="t3", name="Track 3", artists=[SpotifyArtistSimplified(id="a3", name="A3")]),
            added_at="2025-01-17T14:00:00Z",
        ),
    ]

    with patch(
        "app.mcp.tools.playlist_tools.PlaylistToolHandlers._get_client",
        new_callable=AsyncMock,
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_client.get_playlist = AsyncMock(return_value=mock_playlist)
        mock_client.get_playlist_all_tracks = AsyncMock(return_value=mock_all_tracks)
        mock_get_client.return_value = mock_client

        resp = client.post(
            "/mcp/call",
            json={"tool": "spotify.get_playlist", "user_id": seeded_user, "playlist_id": "pl_mismatch"},
        )
        data = resp.json()
        assert data["success"] is True
        result = data["result"]
        assert result["tracks_returned"] == 3
        assert result["tracks_total"] == 5
        assert "tracks_mismatch_warning" in result
        assert "5 tracks but 3 were returned" in result["tracks_mismatch_warning"]


def test_get_playlist_no_mismatch_when_counts_match(client: TestClient, seeded_user: int) -> None:
    """No mismatch warning when tracks_returned == tracks_total."""
    mock_playlist = SpotifyPlaylist(
        id="pl_ok",
        name="OK Playlist",
        public=True,
        owner=SpotifyPlaylistOwner(id="pluser", display_name="Playlist User"),
        snapshot_id="snap_ok",
        external_urls={},
        tracks=SpotifyPlaylistTracks(items=[], total=2),
    )

    mock_all_tracks = [
        SpotifyPlaylistTrackItem(
            track=SpotifyTrack(id="t1", name="Track 1", artists=[SpotifyArtistSimplified(id="a1", name="A1")]),
            added_at="2025-01-15T10:00:00Z",
        ),
        SpotifyPlaylistTrackItem(
            track=SpotifyTrack(id="t2", name="Track 2", artists=[SpotifyArtistSimplified(id="a2", name="A2")]),
            added_at="2025-01-16T12:00:00Z",
        ),
    ]

    with patch(
        "app.mcp.tools.playlist_tools.PlaylistToolHandlers._get_client",
        new_callable=AsyncMock,
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_client.get_playlist = AsyncMock(return_value=mock_playlist)
        mock_client.get_playlist_all_tracks = AsyncMock(return_value=mock_all_tracks)
        mock_get_client.return_value = mock_client

        resp = client.post(
            "/mcp/call",
            json={"tool": "spotify.get_playlist", "user_id": seeded_user, "playlist_id": "pl_ok"},
        )
        data = resp.json()
        assert data["success"] is True
        result = data["result"]
        assert result["tracks_returned"] == 2
        assert "tracks_mismatch_warning" not in result
        assert "tracks_unavailable" not in result


def test_get_playlist_embed_unavailable_placeholder(client: TestClient, seeded_user: int) -> None:
    """Embed fallback includes unavailable placeholders for tracks without IDs."""
    from app.mcp.tools.playlist_tools import _instance as playlist_instance
    from shared.spotify.exceptions import SpotifyRequestError
    from shared.spotify.models import EmbedTrackItem

    with patch(
        "app.mcp.tools.playlist_tools.PlaylistToolHandlers._get_client",
        new_callable=AsyncMock,
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_client.get_playlist = AsyncMock(side_effect=SpotifyRequestError(403, "Forbidden"))
        mock_client.get_playlist_all_tracks = AsyncMock(side_effect=SpotifyRequestError(403, "Forbidden"))
        mock_get_client.return_value = mock_client

        # Seed cache via list_playlists
        mock_client.get_user_playlists = AsyncMock(
            return_value=UserPlaylistsResponse(
                items=[
                    SpotifyPlaylistSimplified(
                        id="pl_emb_unavail",
                        name="Embed Unavail",
                        public=True,
                        owner=SpotifyPlaylistOwner(id="user1", display_name="User One"),
                        snapshot_id="snap_eu",
                        tracks={"total": 3},
                    )
                ],
                total=1,
            )
        )
        client.post(
            "/mcp/call",
            json={"tool": "spotify.list_playlists", "user_id": seeded_user, "limit": 50},
        )

        embed_tracks = [
            EmbedTrackItem(track_id="t1", name="Track 1", artists=["Artist A"], duration_ms=180000),
            EmbedTrackItem(
                track_id=None, name="Gone Track", artists=["Artist B"], duration_ms=200000, unavailable=True
            ),
            EmbedTrackItem(track_id="t3", name="Track 3", artists=["Artist C"], duration_ms=220000),
        ]
        with patch.object(
            playlist_instance._embed_client,
            "fetch_playlist_tracks",
            new_callable=AsyncMock,
            return_value=embed_tracks,
        ):
            resp = client.post(
                "/mcp/call",
                json={"tool": "spotify.get_playlist", "user_id": seeded_user, "playlist_id": "pl_emb_unavail"},
            )

        data = resp.json()
        assert data["success"] is True
        result = data["result"]
        assert len(result["tracks"]) == 3
        assert result["tracks"][0]["id"] == "t1"
        assert result["tracks"][1]["id"] is None
        assert result["tracks"][1]["unavailable"] is True
        assert result["tracks"][1]["name"] == "Gone Track"
        assert result["tracks"][2]["id"] == "t3"
        assert result["tracks_source"] == "embed"


def test_get_playlist_cache_hit_fidelity_fields(client: TestClient, seeded_user: int) -> None:
    """Cache-hit responses include tracks_returned / tracks_unavailable / tracks_mismatch_warning."""
    mock_playlist = SpotifyPlaylist(
        id="pl_cache_fidelity",
        name="Cache Fidelity",
        public=True,
        owner=SpotifyPlaylistOwner(id="pluser", display_name="Playlist User"),
        snapshot_id="snap_cf",
        external_urls={},
        # Spotify reports 3 but we'll return 2 available + 1 unavailable
        tracks=SpotifyPlaylistTracks(items=[], total=3),
    )

    mock_all_tracks = [
        SpotifyPlaylistTrackItem(
            track=SpotifyTrack(id="t1", name="Track 1", artists=[SpotifyArtistSimplified(id="a1", name="A1")]),
            added_at="2025-01-15T10:00:00Z",
        ),
        # Unavailable track
        SpotifyPlaylistTrackItem(track=None, added_at="2025-01-16T12:00:00Z"),
        SpotifyPlaylistTrackItem(
            track=SpotifyTrack(id="t3", name="Track 3", artists=[SpotifyArtistSimplified(id="a3", name="A3")]),
            added_at="2025-01-17T14:00:00Z",
        ),
    ]

    def _assert_fidelity(result: dict) -> None:
        assert result["tracks_returned"] == 3
        assert result["tracks_unavailable"] == 1
        assert "tracks_mismatch_warning" not in result  # returned == total (3 == 3)

    with patch(
        "app.mcp.tools.playlist_tools.PlaylistToolHandlers._get_client",
        new_callable=AsyncMock,
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_client.get_playlist = AsyncMock(return_value=mock_playlist)
        mock_client.get_playlist_all_tracks = AsyncMock(return_value=mock_all_tracks)
        mock_get_client.return_value = mock_client

        # First call — live fetch, populates cache
        resp1 = client.post(
            "/mcp/call",
            json={"tool": "spotify.get_playlist", "user_id": seeded_user, "playlist_id": "pl_cache_fidelity"},
        )
        data1 = resp1.json()
        assert data1["success"] is True
        _assert_fidelity(data1["result"])

        # Second call — should hit cache (snapshot_id matches)
        resp2 = client.post(
            "/mcp/call",
            json={"tool": "spotify.get_playlist", "user_id": seeded_user, "playlist_id": "pl_cache_fidelity"},
        )
        data2 = resp2.json()
        assert data2["success"] is True
        # Fidelity fields must be present even from cache
        _assert_fidelity(data2["result"])
        # get_playlist_all_tracks should only have been called once (cache hit on second)
        mock_client.get_playlist_all_tracks.assert_called_once()


# ---------------------------------------------------------------------------
# Tool registration check
# ---------------------------------------------------------------------------


def test_all_tools_registered(client: TestClient) -> None:
    """All 9 playlist/info tools appear in the tool catalog."""
    resp = client.get("/mcp/tools")
    names = {t["name"] for t in resp.json()}
    expected = {
        "spotify.get_track",
        "spotify.get_artist",
        "spotify.get_album",
        "spotify.list_playlists",
        "spotify.get_playlist",
        "spotify.create_playlist",
        "spotify.add_tracks",
        "spotify.remove_tracks",
        "spotify.update_playlist",
    }
    assert expected.issubset(names), f"Missing tools: {expected - names}"
