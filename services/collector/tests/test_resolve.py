"""Tests for LocalTrackResolutionService."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from collector.resolve import LocalTrackResolutionService, _is_match, _normalize
from collector.settings import CollectorSettings
from shared.crypto import TokenEncryptor
from shared.db.base import Base
from shared.db.enums import JobStatus, JobType, TrackSource
from shared.db.models.music import Artist, Track, TrackArtist
from shared.db.models.operations import JobRun
from shared.db.models.user import SpotifyToken, User
from shared.spotify.models import (
    SpotifyArtistSimplified,
    SpotifySearchResponse,
    SpotifySearchTracks,
    SpotifyTrack,
)

TEST_FERNET_KEY = Fernet.generate_key().decode()


def _test_settings(**overrides: object) -> CollectorSettings:
    defaults: dict[str, object] = {
        "SPOTIFY_CLIENT_ID": "test-id",
        "SPOTIFY_CLIENT_SECRET": "test-secret",
        "TOKEN_ENCRYPTION_KEY": TEST_FERNET_KEY,
        "RESOLVE_LOCAL_TRACKS_ENABLED": True,
        "RESOLVE_BATCH_SIZE": 10,
        "RESOLVE_MAX_PER_CYCLE": 100,
        "RESOLVE_COOLDOWN_DAYS": 30,
    }
    defaults.update(overrides)
    return CollectorSettings(**defaults)  # type: ignore[arg-type]


@pytest.fixture
async def async_engine():  # type: ignore[no-untyped-def]
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def async_session(async_engine):  # type: ignore[no-untyped-def]
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session


async def _create_user_with_token(session: AsyncSession) -> User:
    encryptor = TokenEncryptor(TEST_FERNET_KEY)
    user = User(spotify_user_id="testuser", display_name="Test")
    session.add(user)
    await session.flush()
    token = SpotifyToken(
        user_id=user.id,
        encrypted_refresh_token=encryptor.encrypt("refresh-token"),
        access_token="valid-access-token",
        token_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    session.add(token)
    await session.flush()
    return user


async def _create_local_track(
    session: AsyncSession,
    name: str,
    artist_name: str,
    local_id: str = "local:abc123",
    *,
    resolution_attempted_at: datetime | None = None,
) -> Track:
    """Create a local track with an artist association."""
    track = Track(
        local_track_id=local_id,
        spotify_track_id=None,
        name=name,
        source=TrackSource.IMPORT_ZIP,
        resolution_attempted_at=resolution_attempted_at,
    )
    session.add(track)
    await session.flush()

    artist = Artist(
        local_artist_id=f"local:artist_{local_id}",
        name=artist_name,
        source=TrackSource.IMPORT_ZIP,
    )
    session.add(artist)
    await session.flush()

    ta = TrackArtist(track_id=track.id, artist_id=artist.id, position=0)
    session.add(ta)
    await session.flush()

    return track


def _make_search_response(*tracks: SpotifyTrack) -> SpotifySearchResponse:
    """Build a SpotifySearchResponse with the given tracks."""
    return SpotifySearchResponse(tracks=SpotifySearchTracks(items=list(tracks), total=len(tracks)))


# ---------------------------------------------------------------------------
# Unit tests for normalization and matching
# ---------------------------------------------------------------------------


class TestNormalize:
    def test_lowercase(self) -> None:
        assert _normalize("Hello World") == "hello world"

    def test_strip_whitespace(self) -> None:
        assert _normalize("  hello  world  ") == "hello world"

    def test_unicode_normalization(self) -> None:
        # NFKD normalizes e.g. composed characters
        assert _normalize("café") == _normalize("café")

    def test_empty_string(self) -> None:
        assert _normalize("") == ""


class TestIsMatch:
    def test_exact_match(self) -> None:
        candidate = SpotifyTrack(
            id="abc",
            name="Bohemian Rhapsody",
            artists=[SpotifyArtistSimplified(id="a1", name="Queen")],
        )
        assert _is_match("Bohemian Rhapsody", "Queen", candidate) is True

    def test_case_insensitive_match(self) -> None:
        candidate = SpotifyTrack(
            id="abc",
            name="bohemian rhapsody",
            artists=[SpotifyArtistSimplified(id="a1", name="queen")],
        )
        assert _is_match("Bohemian Rhapsody", "Queen", candidate) is True

    def test_no_match_different_track(self) -> None:
        candidate = SpotifyTrack(
            id="abc",
            name="We Will Rock You",
            artists=[SpotifyArtistSimplified(id="a1", name="Queen")],
        )
        assert _is_match("Bohemian Rhapsody", "Queen", candidate) is False

    def test_no_match_different_artist(self) -> None:
        candidate = SpotifyTrack(
            id="abc",
            name="Bohemian Rhapsody",
            artists=[SpotifyArtistSimplified(id="a1", name="The Beatles")],
        )
        assert _is_match("Bohemian Rhapsody", "Queen", candidate) is False

    def test_no_match_empty_artists(self) -> None:
        candidate = SpotifyTrack(id="abc", name="Bohemian Rhapsody", artists=[])
        assert _is_match("Bohemian Rhapsody", "Queen", candidate) is False

    def test_whitespace_differences(self) -> None:
        candidate = SpotifyTrack(
            id="abc",
            name="Bohemian  Rhapsody",
            artists=[SpotifyArtistSimplified(id="a1", name="Queen")],
        )
        assert _is_match("Bohemian Rhapsody", "Queen", candidate) is True


# ---------------------------------------------------------------------------
# Integration tests for resolution service
# ---------------------------------------------------------------------------


async def test_resolve_happy_path(async_session: AsyncSession) -> None:
    """Successful resolution updates track with Spotify ID and source."""
    await _create_user_with_token(async_session)
    track = await _create_local_track(async_session, "Bohemian Rhapsody", "Queen", "local:aaa")

    settings = _test_settings()
    service = LocalTrackResolutionService(settings)

    search_response = _make_search_response(
        SpotifyTrack(
            id="6rqhFgbbKwnb9MLmUQDhG6",
            name="Bohemian Rhapsody",
            duration_ms=354000,
            artists=[SpotifyArtistSimplified(id="1dfeR4HaWDbWqFHLkxsg1d", name="Queen")],
        )
    )

    with (
        patch.object(service._token_manager, "get_valid_token", new_callable=AsyncMock, return_value="token"),
        patch("collector.resolve.SpotifyClient") as mock_cls,
    ):
        mock_client = AsyncMock()
        mock_client.search = AsyncMock(return_value=search_response)
        mock_cls.return_value = mock_client

        resolved = await service.resolve(async_session)

    assert resolved == 1

    # Verify track updated
    result = await async_session.execute(select(Track).where(Track.id == track.id))
    updated = result.scalar_one()
    assert updated.spotify_track_id == "6rqhFgbbKwnb9MLmUQDhG6"
    assert updated.source == TrackSource.RESOLVED
    assert updated.duration_ms == 354000
    assert updated.resolution_attempted_at is not None

    # Verify job run
    result = await async_session.execute(select(JobRun).where(JobRun.job_type == JobType.RESOLVE_LOCAL))
    job = result.scalar_one()
    assert job.status == JobStatus.SUCCESS
    assert job.records_inserted == 1
    assert job.records_fetched == 1


async def test_resolve_no_match(async_session: AsyncSession) -> None:
    """When search returns no match, track keeps local ID but gets timestamp."""
    await _create_user_with_token(async_session)
    track = await _create_local_track(async_session, "Obscure Song", "Unknown Artist", "local:bbb")

    service = LocalTrackResolutionService(_test_settings())

    # Search returns results but none match
    search_response = _make_search_response(
        SpotifyTrack(
            id="xyz",
            name="Different Song",
            artists=[SpotifyArtistSimplified(id="a1", name="Different Artist")],
        )
    )

    with (
        patch.object(service._token_manager, "get_valid_token", new_callable=AsyncMock, return_value="token"),
        patch("collector.resolve.SpotifyClient") as mock_cls,
    ):
        mock_client = AsyncMock()
        mock_client.search = AsyncMock(return_value=search_response)
        mock_cls.return_value = mock_client

        resolved = await service.resolve(async_session)

    assert resolved == 0

    result = await async_session.execute(select(Track).where(Track.id == track.id))
    updated = result.scalar_one()
    assert updated.spotify_track_id is None
    assert updated.source == TrackSource.IMPORT_ZIP
    assert updated.resolution_attempted_at is not None


async def test_resolve_empty_search_results(async_session: AsyncSession) -> None:
    """When search returns empty results, track is marked as attempted."""
    await _create_user_with_token(async_session)
    track = await _create_local_track(async_session, "NoResults", "NoArtist", "local:ccc")

    service = LocalTrackResolutionService(_test_settings())
    empty_response = SpotifySearchResponse(tracks=SpotifySearchTracks(items=[], total=0))

    with (
        patch.object(service._token_manager, "get_valid_token", new_callable=AsyncMock, return_value="token"),
        patch("collector.resolve.SpotifyClient") as mock_cls,
    ):
        mock_client = AsyncMock()
        mock_client.search = AsyncMock(return_value=empty_response)
        mock_cls.return_value = mock_client

        resolved = await service.resolve(async_session)

    assert resolved == 0

    result = await async_session.execute(select(Track).where(Track.id == track.id))
    updated = result.scalar_one()
    assert updated.resolution_attempted_at is not None


async def test_resolve_skips_recently_attempted(async_session: AsyncSession) -> None:
    """Tracks attempted within cooldown period are skipped."""
    await _create_user_with_token(async_session)
    recent = datetime.now(UTC) - timedelta(days=1)
    await _create_local_track(async_session, "Recent Track", "Artist", "local:ddd", resolution_attempted_at=recent)

    service = LocalTrackResolutionService(_test_settings(RESOLVE_COOLDOWN_DAYS=30))

    with (
        patch.object(service._token_manager, "get_valid_token", new_callable=AsyncMock, return_value="token"),
        patch("collector.resolve.SpotifyClient") as mock_cls,
    ):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client

        resolved = await service.resolve(async_session)

    assert resolved == 0
    # Search should not have been called
    mock_client.search.assert_not_called()


async def test_resolve_retries_after_cooldown(async_session: AsyncSession) -> None:
    """Tracks attempted beyond cooldown period are retried."""
    await _create_user_with_token(async_session)
    old = datetime.now(UTC) - timedelta(days=60)
    track = await _create_local_track(
        async_session, "Old Track", "Old Artist", "local:eee", resolution_attempted_at=old
    )

    service = LocalTrackResolutionService(_test_settings(RESOLVE_COOLDOWN_DAYS=30))

    search_response = _make_search_response(
        SpotifyTrack(
            id="resolved123",
            name="Old Track",
            artists=[SpotifyArtistSimplified(id="a1", name="Old Artist")],
        )
    )

    with (
        patch.object(service._token_manager, "get_valid_token", new_callable=AsyncMock, return_value="token"),
        patch("collector.resolve.SpotifyClient") as mock_cls,
    ):
        mock_client = AsyncMock()
        mock_client.search = AsyncMock(return_value=search_response)
        mock_cls.return_value = mock_client

        resolved = await service.resolve(async_session)

    assert resolved == 1

    result = await async_session.execute(select(Track).where(Track.id == track.id))
    updated = result.scalar_one()
    assert updated.spotify_track_id == "resolved123"


async def test_resolve_disabled(async_session: AsyncSession) -> None:
    """When disabled, returns 0 immediately."""
    service = LocalTrackResolutionService(_test_settings(RESOLVE_LOCAL_TRACKS_ENABLED=False))
    resolved = await service.resolve(async_session)
    assert resolved == 0


async def test_resolve_no_active_users(async_session: AsyncSession) -> None:
    """When no users have Spotify tokens, skip resolution."""
    await _create_local_track(async_session, "Track", "Artist", "local:fff")

    service = LocalTrackResolutionService(_test_settings())
    resolved = await service.resolve(async_session)
    assert resolved == 0


async def test_resolve_skips_already_resolved_tracks(async_session: AsyncSession) -> None:
    """Tracks that already have a spotify_track_id are not queried."""
    await _create_user_with_token(async_session)

    # Track with both local and spotify ID (already resolved)
    track = Track(
        local_track_id="local:ggg",
        spotify_track_id="already_resolved",
        name="Already Resolved",
        source=TrackSource.RESOLVED,
    )
    async_session.add(track)
    await async_session.flush()

    service = LocalTrackResolutionService(_test_settings())

    with (
        patch.object(service._token_manager, "get_valid_token", new_callable=AsyncMock, return_value="token"),
        patch("collector.resolve.SpotifyClient") as mock_cls,
    ):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client

        resolved = await service.resolve(async_session)

    assert resolved == 0
    mock_client.search.assert_not_called()


async def test_resolve_skips_track_without_artist(async_session: AsyncSession) -> None:
    """Tracks with no associated artist are marked attempted but not searched."""
    await _create_user_with_token(async_session)

    # Track with no artist association
    track = Track(
        local_track_id="local:hhh",
        spotify_track_id=None,
        name="Orphan Track",
        source=TrackSource.IMPORT_ZIP,
    )
    async_session.add(track)
    await async_session.flush()

    service = LocalTrackResolutionService(_test_settings())

    with (
        patch.object(service._token_manager, "get_valid_token", new_callable=AsyncMock, return_value="token"),
        patch("collector.resolve.SpotifyClient") as mock_cls,
    ):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client

        resolved = await service.resolve(async_session)

    assert resolved == 0
    mock_client.search.assert_not_called()

    # But track should be marked as attempted
    result = await async_session.execute(select(Track).where(Track.id == track.id))
    updated = result.scalar_one()
    assert updated.resolution_attempted_at is not None


async def test_resolve_enriches_metadata(async_session: AsyncSession) -> None:
    """Resolution fills in duration_ms, album_name, album_spotify_id when missing."""
    await _create_user_with_token(async_session)
    track = await _create_local_track(async_session, "Test Track", "Test Artist", "local:iii")

    service = LocalTrackResolutionService(_test_settings())

    from shared.spotify.models import SpotifyAlbumSimplified

    search_response = _make_search_response(
        SpotifyTrack(
            id="spotify123",
            name="Test Track",
            duration_ms=240000,
            artists=[SpotifyArtistSimplified(id="a1", name="Test Artist")],
            album=SpotifyAlbumSimplified(id="album123", name="Test Album"),
        )
    )

    with (
        patch.object(service._token_manager, "get_valid_token", new_callable=AsyncMock, return_value="token"),
        patch("collector.resolve.SpotifyClient") as mock_cls,
    ):
        mock_client = AsyncMock()
        mock_client.search = AsyncMock(return_value=search_response)
        mock_cls.return_value = mock_client

        resolved = await service.resolve(async_session)

    assert resolved == 1

    result = await async_session.execute(select(Track).where(Track.id == track.id))
    updated = result.scalar_one()
    assert updated.duration_ms == 240000
    assert updated.album_name == "Test Album"
    assert updated.album_spotify_id == "album123"


async def test_resolve_multiple_tracks(async_session: AsyncSession) -> None:
    """Multiple tracks resolved in one cycle."""
    await _create_user_with_token(async_session)
    await _create_local_track(async_session, "Track A", "Artist A", "local:j1")
    await _create_local_track(async_session, "Track B", "Artist B", "local:j2")

    service = LocalTrackResolutionService(_test_settings())

    responses = [
        _make_search_response(
            SpotifyTrack(
                id="sp_a",
                name="Track A",
                artists=[SpotifyArtistSimplified(id="a1", name="Artist A")],
            )
        ),
        _make_search_response(
            SpotifyTrack(
                id="sp_b",
                name="Track B",
                artists=[SpotifyArtistSimplified(id="a2", name="Artist B")],
            )
        ),
    ]

    with (
        patch.object(service._token_manager, "get_valid_token", new_callable=AsyncMock, return_value="token"),
        patch("collector.resolve.SpotifyClient") as mock_cls,
    ):
        mock_client = AsyncMock()
        mock_client.search = AsyncMock(side_effect=responses)
        mock_cls.return_value = mock_client

        resolved = await service.resolve(async_session)

    assert resolved == 2

    result = await async_session.execute(select(JobRun).where(JobRun.job_type == JobType.RESOLVE_LOCAL))
    job = result.scalar_one()
    assert job.records_inserted == 2
    assert job.records_fetched == 2


async def test_resolve_search_error_continues(async_session: AsyncSession) -> None:
    """A search error for one track doesn't stop the batch; track is marked attempted."""
    await _create_user_with_token(async_session)
    track1 = await _create_local_track(async_session, "Good Track", "Good Artist", "local:k1")
    track2 = await _create_local_track(async_session, "Bad Track", "Bad Artist", "local:k2")

    service = LocalTrackResolutionService(_test_settings())

    good_response = _make_search_response(
        SpotifyTrack(
            id="sp_good",
            name="Good Track",
            artists=[SpotifyArtistSimplified(id="a1", name="Good Artist")],
        )
    )

    with (
        patch.object(service._token_manager, "get_valid_token", new_callable=AsyncMock, return_value="token"),
        patch("collector.resolve.SpotifyClient") as mock_cls,
    ):
        mock_client = AsyncMock()
        # First search succeeds, second fails
        mock_client.search = AsyncMock(side_effect=[good_response, RuntimeError("API error")])
        mock_cls.return_value = mock_client

        resolved = await service.resolve(async_session)

    assert resolved == 1

    # Both tracks should be marked as attempted
    result = await async_session.execute(select(Track).where(Track.id == track1.id))
    assert result.scalar_one().resolution_attempted_at is not None
    result = await async_session.execute(select(Track).where(Track.id == track2.id))
    assert result.scalar_one().resolution_attempted_at is not None
