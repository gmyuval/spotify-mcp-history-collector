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
