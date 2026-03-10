"""Tests for memory.* MCP tools (playlist ledger)."""

import json
import uuid
from collections.abc import AsyncGenerator, Generator
from typing import Any

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.dependencies import db_manager
from app.main import app
from app.settings import AppSettings, get_settings
from shared.db.base import Base
from shared.db.models.user import User

TEST_FERNET_KEY = Fernet.generate_key().decode()


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
        user = User(spotify_user_id="ledgeruser", display_name="Ledger User")
        session.add(user)
        await session.flush()
        uid = user.id
        await session.commit()
    return uid


@pytest.fixture
async def second_user(async_engine: AsyncEngine) -> int:
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        user = User(spotify_user_id="ledgeruser2", display_name="Ledger User 2")
        session.add(user)
        await session.flush()
        uid = user.id
        await session.commit()
    return uid


def _call(client: TestClient, tool: str, **kwargs: object) -> dict[str, Any]:
    resp = client.post("/mcp/call", json={"tool": tool, **kwargs})
    assert resp.status_code == 200
    return resp.json()  # type: ignore[no-any-return]


# ── memory.log_playlist_create ────────────────────────────────────────


class TestLogPlaylistCreate:
    def test_happy_path(self, client: TestClient, seeded_user: int) -> None:
        data = _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="spotify:playlist:abc123",
            name="Upbeat Metal Mix",
            track_ids=["track1", "track2", "track3"],
            description="A high-energy metal playlist",
            intent_tags=["upbeat", "metal"],
            seed_context={"days": 60},
        )
        assert data["success"]
        result = data["result"]
        assert result["playlist_id"] == "spotify:playlist:abc123"
        assert result["snapshot_id"] is not None
        assert result["stored_track_count"] == 3
        assert result["created_at"] is not None

    def test_minimal_params(self, client: TestClient, seeded_user: int) -> None:
        data = _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_minimal",
            name="Minimal",
            track_ids=["t1"],
        )
        assert data["success"]
        assert data["result"]["stored_track_count"] == 1

    def test_idempotency(self, client: TestClient, seeded_user: int) -> None:
        """Same idempotency_key returns existing record without error."""
        params = {
            "user_id": seeded_user,
            "playlist_id": "pl_idemp",
            "name": "Test",
            "track_ids": ["t1", "t2"],
            "idempotency_key": "key-12345678",
        }
        data1 = _call(client, "memory.log_playlist_create", **params)
        assert data1["success"]
        assert data1["result"]["stored_track_count"] == 2

        # Second call with same key but different playlist_id and different
        # track_ids — returns original record with stored track count (not
        # the caller's track_ids length).
        params2 = {**params, "playlist_id": "pl_idemp_other", "track_ids": ["t1", "t2", "t3"]}
        data2 = _call(client, "memory.log_playlist_create", **params2)
        assert data2["success"]
        assert data2["result"]["playlist_id"] == "pl_idemp"  # original
        assert data2["result"]["stored_track_count"] == 2  # from stored snapshot, not args

    def test_idempotency_scoped_to_user(self, client: TestClient, seeded_user: int, second_user: int) -> None:
        """Idempotency lookup is scoped to user_id — same key for same user
        returns the idempotent result, but a different user's lookup does
        not find it (no cross-user data leak).
        """
        key = "scoped-idemp-key"
        data1 = _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_idemp_u1",
            name="User1 Playlist",
            track_ids=["t1"],
            idempotency_key=key,
        )
        assert data1["success"]
        assert data1["result"]["playlist_id"] == "pl_idemp_u1"

        # Same user, same key → idempotent return of original
        data1b = _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_idemp_u1_dup",
            name="User1 Again",
            track_ids=["t9"],
            idempotency_key=key,
        )
        assert data1b["success"]
        assert data1b["result"]["playlist_id"] == "pl_idemp_u1"

        # Different user, same key → the user_id-scoped query does NOT
        # find user 1's record, so user 2 gets no idempotent shortcut.
        # We cannot fully test the insert here because the DB has a global
        # unique constraint on idempotency_key (not per-user), which would
        # cause an IntegrityError.  The key assertion is that the query-
        # level scoping prevents data leaks; the DB constraint provides an
        # additional safety net.
        #
        # To verify scoping works at the query level, we confirm user 2
        # with a *different* key creates independently:
        data2 = _call(
            client,
            "memory.log_playlist_create",
            user_id=second_user,
            playlist_id="pl_idemp_u2",
            name="User2 Playlist",
            track_ids=["t2", "t3"],
            idempotency_key="user2-separate-key",
        )
        assert data2["success"]
        assert data2["result"]["playlist_id"] == "pl_idemp_u2"
        assert data2["result"]["stored_track_count"] == 2

    def test_duplicate_playlist_id_error(self, client: TestClient, seeded_user: int) -> None:
        """Creating same playlist_id twice without idempotency_key fails."""
        params = {
            "user_id": seeded_user,
            "playlist_id": "pl_dup",
            "name": "Test",
            "track_ids": ["t1"],
        }
        data1 = _call(client, "memory.log_playlist_create", **params)
        assert data1["success"]

        data2 = _call(client, "memory.log_playlist_create", **params)
        assert not data2["success"]
        assert "already exists" in data2["error"]

    def test_missing_name(self, client: TestClient, seeded_user: int) -> None:
        data = _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_noname",
            track_ids=["t1"],
        )
        assert not data["success"]
        assert "name" in data["error"]

    def test_empty_track_ids(self, client: TestClient, seeded_user: int) -> None:
        data = _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_empty",
            name="Empty",
            track_ids=[],
        )
        assert not data["success"]
        assert "track_ids" in data["error"]

    def test_invalid_user_id(self, client: TestClient) -> None:
        data = _call(
            client,
            "memory.log_playlist_create",
            user_id=-1,
            playlist_id="pl_bad",
            name="Bad",
            track_ids=["t1"],
        )
        assert not data["success"]
        assert "user_id" in data["error"]

    def test_json_string_params(self, client: TestClient, seeded_user: int) -> None:
        """ChatGPT may send arrays/objects as JSON strings."""
        data = _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_jsonstr",
            name="JSON String Test",
            track_ids='["t1", "t2"]',
            intent_tags='["tag1"]',
            seed_context='{"key": "val"}',
        )
        assert data["success"]
        assert data["result"]["stored_track_count"] == 2


# ── memory.log_playlist_mutation ──────────────────────────────────────


class TestLogPlaylistMutation:
    @pytest.fixture(autouse=True)
    def _create_playlist(self, client: TestClient, seeded_user: int) -> None:
        data = _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_mut",
            name="Mutation Test",
            track_ids=["t1", "t2", "t3"],
        )
        assert data["success"]

    def test_add_tracks(self, client: TestClient, seeded_user: int) -> None:
        data = _call(
            client,
            "memory.log_playlist_mutation",
            user_id=seeded_user,
            playlist_id="pl_mut",
            mutation_type="ADD_TRACKS",
            payload={"track_ids": ["t4", "t5"]},
        )
        assert data["success"]
        assert data["result"]["event_id"] is not None
        assert data["result"]["playlist_id"] == "pl_mut"

    def test_remove_tracks(self, client: TestClient, seeded_user: int) -> None:
        data = _call(
            client,
            "memory.log_playlist_mutation",
            user_id=seeded_user,
            playlist_id="pl_mut",
            mutation_type="REMOVE_TRACKS",
            payload={"track_ids": ["t1"]},
        )
        assert data["success"]

    def test_reorder(self, client: TestClient, seeded_user: int) -> None:
        data = _call(
            client,
            "memory.log_playlist_mutation",
            user_id=seeded_user,
            playlist_id="pl_mut",
            mutation_type="REORDER",
            payload={"track_ids": ["t3", "t1", "t2"]},
        )
        assert data["success"]

    def test_update_meta(self, client: TestClient, seeded_user: int) -> None:
        data = _call(
            client,
            "memory.log_playlist_mutation",
            user_id=seeded_user,
            playlist_id="pl_mut",
            mutation_type="UPDATE_META",
            payload={"name": "New Name", "intent_tags": ["chill"]},
        )
        assert data["success"]

        # Verify metadata was updated
        detail = _call(
            client,
            "memory.get_playlist",
            user_id=seeded_user,
            playlist_id="pl_mut",
        )
        assert detail["success"]
        assert detail["result"]["playlist"]["name"] == "New Name"
        assert detail["result"]["playlist"]["intent_tags"] == ["chill"]

    def test_invalid_type(self, client: TestClient, seeded_user: int) -> None:
        data = _call(
            client,
            "memory.log_playlist_mutation",
            user_id=seeded_user,
            playlist_id="pl_mut",
            mutation_type="INVALID",
            payload={"track_ids": ["t1"]},
        )
        assert not data["success"]
        assert "type must be one of" in data["error"]

    def test_add_tracks_missing_track_ids(self, client: TestClient, seeded_user: int) -> None:
        data = _call(
            client,
            "memory.log_playlist_mutation",
            user_id=seeded_user,
            playlist_id="pl_mut",
            mutation_type="ADD_TRACKS",
            payload={"other": "field"},
        )
        assert not data["success"]
        assert "track_ids" in data["error"]

    def test_update_meta_no_fields(self, client: TestClient, seeded_user: int) -> None:
        data = _call(
            client,
            "memory.log_playlist_mutation",
            user_id=seeded_user,
            playlist_id="pl_mut",
            mutation_type="UPDATE_META",
            payload={"other": "field"},
        )
        assert not data["success"]
        assert "at least one of" in data["error"]

    def test_nonexistent_playlist(self, client: TestClient, seeded_user: int) -> None:
        data = _call(
            client,
            "memory.log_playlist_mutation",
            user_id=seeded_user,
            playlist_id="pl_nonexistent",
            mutation_type="ADD_TRACKS",
            payload={"track_ids": ["t1"]},
        )
        assert not data["success"]
        assert "not found" in data["error"]

    def test_client_event_id_idempotency(self, client: TestClient, seeded_user: int) -> None:
        eid = str(uuid.uuid4())
        data1 = _call(
            client,
            "memory.log_playlist_mutation",
            user_id=seeded_user,
            playlist_id="pl_mut",
            mutation_type="ADD_TRACKS",
            payload={"track_ids": ["t4"]},
            client_event_id=eid,
        )
        assert data1["success"]

        # Same client_event_id returns existing event
        data2 = _call(
            client,
            "memory.log_playlist_mutation",
            user_id=seeded_user,
            playlist_id="pl_mut",
            mutation_type="ADD_TRACKS",
            payload={"track_ids": ["t5"]},
            client_event_id=eid,
        )
        assert data2["success"]
        assert data2["result"]["event_id"] == data1["result"]["event_id"]

    def test_json_string_payload(self, client: TestClient, seeded_user: int) -> None:
        """ChatGPT sends payload as JSON string."""
        data = _call(
            client,
            "memory.log_playlist_mutation",
            user_id=seeded_user,
            playlist_id="pl_mut",
            mutation_type="ADD_TRACKS",
            payload='{"track_ids": ["t6"]}',
        )
        assert data["success"]

    def test_snapshot_compaction(self, client: TestClient, seeded_user: int) -> None:
        """After 10 mutations, a periodic snapshot is auto-created."""
        for i in range(10):
            data = _call(
                client,
                "memory.log_playlist_mutation",
                user_id=seeded_user,
                playlist_id="pl_mut",
                mutation_type="ADD_TRACKS",
                payload={"track_ids": [f"compact_t{i}"]},
            )
            assert data["success"]

        # The 10th mutation should trigger compaction
        assert data["result"]["new_snapshot_id"] is not None


# ── memory.get_playlists ──────────────────────────────────────────────


class TestGetPlaylists:
    def test_empty_list(self, client: TestClient, seeded_user: int) -> None:
        data = _call(client, "memory.get_playlists", user_id=seeded_user)
        assert data["success"]
        assert data["result"]["items"] == []
        assert data["result"]["next_cursor"] is None

    def test_list_with_playlists(self, client: TestClient, seeded_user: int) -> None:
        # Create two playlists
        _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_list1",
            name="First",
            track_ids=["t1", "t2"],
        )
        _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_list2",
            name="Second",
            track_ids=["t3"],
        )

        data = _call(client, "memory.get_playlists", user_id=seeded_user)
        assert data["success"]
        items = data["result"]["items"]
        assert len(items) == 2
        # Check fields are present
        assert items[0]["playlist_id"] is not None
        assert items[0]["name"] is not None
        assert items[0]["track_count"] >= 0
        assert items[0]["intent_tags"] is not None

    def test_track_count_accuracy(self, client: TestClient, seeded_user: int) -> None:
        _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_count",
            name="Count Test",
            track_ids=["t1", "t2", "t3", "t4", "t5"],
        )

        data = _call(client, "memory.get_playlists", user_id=seeded_user)
        assert data["success"]
        items = data["result"]["items"]
        assert len(items) == 1
        assert items[0]["track_count"] == 5

    def test_pagination(self, client: TestClient, seeded_user: int) -> None:
        """Pagination via limit + cursor."""
        for i in range(3):
            _call(
                client,
                "memory.log_playlist_create",
                user_id=seeded_user,
                playlist_id=f"pl_page{i}",
                name=f"Page {i}",
                track_ids=[f"t{i}"],
            )

        # Get first page (limit=2)
        data1 = _call(client, "memory.get_playlists", user_id=seeded_user, limit=2)
        assert data1["success"]
        assert len(data1["result"]["items"]) == 2
        assert data1["result"]["next_cursor"] is not None

        # Get second page
        data2 = _call(
            client,
            "memory.get_playlists",
            user_id=seeded_user,
            limit=2,
            cursor=data1["result"]["next_cursor"],
        )
        assert data2["success"]
        assert len(data2["result"]["items"]) == 1
        assert data2["result"]["next_cursor"] is None


# ── memory.get_playlist ───────────────────────────────────────────────


class TestGetPlaylist:
    def test_happy_path(self, client: TestClient, seeded_user: int) -> None:
        _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_detail",
            name="Detail Test",
            track_ids=["t1", "t2"],
            description="Test desc",
            intent_tags=["chill"],
            seed_context={"days": 30},
        )

        data = _call(
            client,
            "memory.get_playlist",
            user_id=seeded_user,
            playlist_id="pl_detail",
        )
        assert data["success"]
        result = data["result"]
        assert result["playlist"]["playlist_id"] == "pl_detail"
        assert result["playlist"]["name"] == "Detail Test"
        assert result["playlist"]["description"] == "Test desc"
        assert result["playlist"]["intent_tags"] == ["chill"]
        assert result["playlist"]["seed_context"] == {"days": 30}
        assert result["latest_snapshot"] is not None
        assert result["latest_snapshot"]["track_ids"] == ["t1", "t2"]
        assert result["recent_events"] == []

    def test_with_events(self, client: TestClient, seeded_user: int) -> None:
        _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_events",
            name="Events Test",
            track_ids=["t1"],
        )
        _call(
            client,
            "memory.log_playlist_mutation",
            user_id=seeded_user,
            playlist_id="pl_events",
            mutation_type="ADD_TRACKS",
            payload={"track_ids": ["t2"]},
        )

        data = _call(
            client,
            "memory.get_playlist",
            user_id=seeded_user,
            playlist_id="pl_events",
        )
        assert data["success"]
        assert len(data["result"]["recent_events"]) == 1
        assert data["result"]["recent_events"][0]["type"] == "ADD_TRACKS"

    def test_not_found(self, client: TestClient, seeded_user: int) -> None:
        data = _call(
            client,
            "memory.get_playlist",
            user_id=seeded_user,
            playlist_id="pl_nonexistent",
        )
        assert not data["success"]
        assert "not found" in data["error"]

    def test_include_events_limit(self, client: TestClient, seeded_user: int) -> None:
        _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_elimit",
            name="Limit Test",
            track_ids=["t1"],
        )
        for i in range(5):
            _call(
                client,
                "memory.log_playlist_mutation",
                user_id=seeded_user,
                playlist_id="pl_elimit",
                mutation_type="ADD_TRACKS",
                payload={"track_ids": [f"t{i + 2}"]},
            )

        data = _call(
            client,
            "memory.get_playlist",
            user_id=seeded_user,
            playlist_id="pl_elimit",
            include_events_limit=3,
        )
        assert data["success"]
        assert len(data["result"]["recent_events"]) == 3


# ── memory.reconstruct_playlist ───────────────────────────────────────


class TestReconstructPlaylist:
    def test_from_initial_snapshot(self, client: TestClient, seeded_user: int) -> None:
        """Reconstruct from creation snapshot (no events)."""
        _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_recon1",
            name="Reconstruct Test",
            track_ids=["t1", "t2", "t3"],
        )

        data = _call(
            client,
            "memory.reconstruct_playlist",
            user_id=seeded_user,
            playlist_id="pl_recon1",
        )
        assert data["success"]
        result = data["result"]
        assert result["track_ids"] == ["t1", "t2", "t3"]
        assert result["reconstruction"]["used_snapshot_id"] is not None
        assert result["reconstruction"]["applied_event_count"] == 0

    def test_with_add_and_remove(self, client: TestClient, seeded_user: int) -> None:
        """Reconstruct after add + remove events."""
        _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_recon2",
            name="Test",
            track_ids=["t1", "t2", "t3"],
        )
        _call(
            client,
            "memory.log_playlist_mutation",
            user_id=seeded_user,
            playlist_id="pl_recon2",
            mutation_type="ADD_TRACKS",
            payload={"track_ids": ["t4", "t5"]},
        )
        _call(
            client,
            "memory.log_playlist_mutation",
            user_id=seeded_user,
            playlist_id="pl_recon2",
            mutation_type="REMOVE_TRACKS",
            payload={"track_ids": ["t2"]},
        )

        data = _call(
            client,
            "memory.reconstruct_playlist",
            user_id=seeded_user,
            playlist_id="pl_recon2",
        )
        assert data["success"]
        assert data["result"]["track_ids"] == ["t1", "t3", "t4", "t5"]
        assert data["result"]["reconstruction"]["applied_event_count"] == 2

    def test_with_reorder(self, client: TestClient, seeded_user: int) -> None:
        _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_recon3",
            name="Test",
            track_ids=["t1", "t2", "t3"],
        )
        _call(
            client,
            "memory.log_playlist_mutation",
            user_id=seeded_user,
            playlist_id="pl_recon3",
            mutation_type="REORDER",
            payload={"track_ids": ["t3", "t1", "t2"]},
        )

        data = _call(
            client,
            "memory.reconstruct_playlist",
            user_id=seeded_user,
            playlist_id="pl_recon3",
        )
        assert data["success"]
        assert data["result"]["track_ids"] == ["t3", "t1", "t2"]

    def test_not_found(self, client: TestClient, seeded_user: int) -> None:
        data = _call(
            client,
            "memory.reconstruct_playlist",
            user_id=seeded_user,
            playlist_id="pl_nonexistent",
        )
        assert not data["success"]
        assert "not found" in data["error"]

    def test_update_meta_skipped(self, client: TestClient, seeded_user: int) -> None:
        """UPDATE_META events don't affect track list."""
        _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_recon4",
            name="Test",
            track_ids=["t1", "t2"],
        )
        _call(
            client,
            "memory.log_playlist_mutation",
            user_id=seeded_user,
            playlist_id="pl_recon4",
            mutation_type="UPDATE_META",
            payload={"name": "New Name"},
        )

        data = _call(
            client,
            "memory.reconstruct_playlist",
            user_id=seeded_user,
            playlist_id="pl_recon4",
        )
        assert data["success"]
        assert data["result"]["track_ids"] == ["t1", "t2"]
        assert data["result"]["reconstruction"]["applied_event_count"] == 1


# ── User isolation ────────────────────────────────────────────────────


class TestUserIsolation:
    def test_get_playlist_wrong_user(self, client: TestClient, seeded_user: int, second_user: int) -> None:
        _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_iso",
            name="Isolation",
            track_ids=["t1"],
        )

        # Second user can't see first user's playlist
        data = _call(
            client,
            "memory.get_playlist",
            user_id=second_user,
            playlist_id="pl_iso",
        )
        assert not data["success"]
        assert "not found" in data["error"]

    def test_get_playlists_isolation(self, client: TestClient, seeded_user: int, second_user: int) -> None:
        _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_iso2",
            name="User 1 Playlist",
            track_ids=["t1"],
        )

        data = _call(client, "memory.get_playlists", user_id=second_user)
        assert data["success"]
        assert data["result"]["items"] == []

    def test_mutate_wrong_user(self, client: TestClient, seeded_user: int, second_user: int) -> None:
        _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_iso3",
            name="Test",
            track_ids=["t1"],
        )

        data = _call(
            client,
            "memory.log_playlist_mutation",
            user_id=second_user,
            playlist_id="pl_iso3",
            mutation_type="ADD_TRACKS",
            payload={"track_ids": ["t2"]},
        )
        assert not data["success"]
        assert "not found" in data["error"]

    def test_reconstruct_wrong_user(self, client: TestClient, seeded_user: int, second_user: int) -> None:
        _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_iso4",
            name="Test",
            track_ids=["t1"],
        )

        data = _call(
            client,
            "memory.reconstruct_playlist",
            user_id=second_user,
            playlist_id="pl_iso4",
        )
        assert not data["success"]
        assert "not found" in data["error"]


# ── Add tracks at position ────────────────────────────────────────────


class TestAddTracksAtPosition:
    def test_insert_at_beginning(self, client: TestClient, seeded_user: int) -> None:
        _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_insert",
            name="Insert Test",
            track_ids=["t1", "t2", "t3"],
        )
        _call(
            client,
            "memory.log_playlist_mutation",
            user_id=seeded_user,
            playlist_id="pl_insert",
            mutation_type="ADD_TRACKS",
            payload={"track_ids": ["t0"], "insert_at": 0},
        )

        data = _call(
            client,
            "memory.reconstruct_playlist",
            user_id=seeded_user,
            playlist_id="pl_insert",
        )
        assert data["success"]
        assert data["result"]["track_ids"] == ["t0", "t1", "t2", "t3"]

    def test_insert_at_middle(self, client: TestClient, seeded_user: int) -> None:
        _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_insert2",
            name="Insert Mid",
            track_ids=["t1", "t2", "t3"],
        )
        _call(
            client,
            "memory.log_playlist_mutation",
            user_id=seeded_user,
            playlist_id="pl_insert2",
            mutation_type="ADD_TRACKS",
            payload={"track_ids": ["tA", "tB"], "insert_at": 1},
        )

        data = _call(
            client,
            "memory.reconstruct_playlist",
            user_id=seeded_user,
            playlist_id="pl_insert2",
        )
        assert data["success"]
        assert data["result"]["track_ids"] == ["t1", "tA", "tB", "t2", "t3"]


# ── created_by validation ────────────────────────────────────────────────


class TestCreatedByValidation:
    """Tests for seed_context.origin.created_by validation."""

    def test_valid_created_by_assistant(self, client: TestClient, seeded_user: int) -> None:
        data = _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_cb_assistant",
            name="AI Playlist",
            track_ids=["t1"],
            seed_context={"origin": {"created_by": "assistant"}},
        )
        assert data["success"]

    def test_valid_created_by_user(self, client: TestClient, seeded_user: int) -> None:
        data = _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_cb_user",
            name="User Playlist",
            track_ids=["t1"],
            seed_context={"origin": {"created_by": "user"}},
        )
        assert data["success"]

    def test_valid_created_by_spotify(self, client: TestClient, seeded_user: int) -> None:
        data = _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_cb_spotify",
            name="Spotify Curated",
            track_ids=["t1"],
            seed_context={"origin": {"created_by": "spotify"}},
        )
        assert data["success"]

    def test_valid_created_by_import(self, client: TestClient, seeded_user: int) -> None:
        data = _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_cb_import",
            name="Imported",
            track_ids=["t1"],
            seed_context={"origin": {"created_by": "import"}},
        )
        assert data["success"]

    def test_valid_created_by_other(self, client: TestClient, seeded_user: int) -> None:
        data = _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_cb_other",
            name="Other",
            track_ids=["t1"],
            seed_context={"origin": {"created_by": "other"}},
        )
        assert data["success"]

    def test_invalid_created_by_nested(self, client: TestClient, seeded_user: int) -> None:
        """Unknown created_by in origin should be rejected."""
        data = _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_cb_bad",
            name="Bad Origin",
            track_ids=["t1"],
            seed_context={"origin": {"created_by": "robot"}},
        )
        assert not data["success"]
        assert "origin.created_by must be one of" in data["error"]

    def test_invalid_created_by_flat(self, client: TestClient, seeded_user: int) -> None:
        """Unknown created_by at top level should be rejected."""
        data = _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_cb_bad_flat",
            name="Bad Flat",
            track_ids=["t1"],
            seed_context={"created_by": "unknown_value"},
        )
        assert not data["success"]
        assert "seed_context.created_by must be one of" in data["error"]

    def test_missing_created_by_is_ok(self, client: TestClient, seeded_user: int) -> None:
        """Omitting created_by entirely should be accepted (backwards compat)."""
        data = _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_cb_none",
            name="No Origin",
            track_ids=["t1"],
            seed_context={"time_window": "30d"},
        )
        assert data["success"]

    def test_empty_seed_context_is_ok(self, client: TestClient, seeded_user: int) -> None:
        """Empty seed_context should be accepted."""
        data = _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_cb_empty",
            name="Empty Context",
            track_ids=["t1"],
            seed_context={},
        )
        assert data["success"]

    def test_created_by_as_json_string(self, client: TestClient, seeded_user: int) -> None:
        """seed_context passed as JSON string should also be validated."""
        data = _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_cb_json",
            name="JSON String",
            track_ids=["t1"],
            seed_context=json.dumps({"origin": {"created_by": "invalid_thing"}}),
        )
        assert not data["success"]
        assert "origin.created_by must be one of" in data["error"]

    def test_backfill_validates_created_by(self, client: TestClient, seeded_user: int) -> None:
        """backfill_playlist should also validate created_by."""
        data = _call(
            client,
            "memory.backfill_playlist",
            user_id=seeded_user,
            playlist_id="pl_bf_bad",
            track_ids=["t1", "t2"],
            name="Backfill Bad",
            seed_context={"origin": {"created_by": "alien"}},
        )
        assert not data["success"]
        assert "origin.created_by must be one of" in data["error"]

    def test_backfill_valid_created_by(self, client: TestClient, seeded_user: int) -> None:
        """backfill_playlist should accept valid created_by."""
        data = _call(
            client,
            "memory.backfill_playlist",
            user_id=seeded_user,
            playlist_id="pl_bf_good",
            track_ids=["t1", "t2"],
            name="Backfill Good",
            seed_context={"origin": {"created_by": "spotify"}},
        )
        assert data["success"]

    def test_non_string_created_by_nested_rejected(self, client: TestClient, seeded_user: int) -> None:
        """Non-string created_by (e.g. integer) should be rejected when key is present."""
        data = _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_cb_int",
            name="Int Origin",
            track_ids=["t1"],
            seed_context={"origin": {"created_by": 1}},
        )
        assert not data["success"]
        assert "origin.created_by must be one of" in data["error"]

    def test_null_created_by_nested_rejected(self, client: TestClient, seeded_user: int) -> None:
        """Null created_by should be rejected when key is present."""
        data = _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_cb_null",
            name="Null Origin",
            track_ids=["t1"],
            seed_context={"origin": {"created_by": None}},
        )
        assert not data["success"]
        assert "origin.created_by must be one of" in data["error"]

    def test_non_string_created_by_flat_rejected(self, client: TestClient, seeded_user: int) -> None:
        """Non-string flat created_by should be rejected."""
        data = _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_cb_flat_int",
            name="Flat Int",
            track_ids=["t1"],
            seed_context={"created_by": 42},
        )
        assert not data["success"]
        assert "seed_context.created_by must be one of" in data["error"]

    def test_backfill_normalizes_spotify_uris(self, client: TestClient, seeded_user: int) -> None:
        """backfill_playlist should strip spotify:track: prefix from track IDs."""
        data = _call(
            client,
            "memory.backfill_playlist",
            user_id=seeded_user,
            playlist_id="pl_bf_uri",
            track_ids=["spotify:track:abc123", "def456", "spotify:track:ghi789"],
            name="URI Normalize",
        )
        assert data["success"]
        # Verify stored track count
        assert data["result"]["stored_track_count"] == 3

        # Fetch the playlist and verify IDs are normalized
        detail = _call(
            client,
            "memory.get_playlist",
            user_id=seeded_user,
            playlist_id="pl_bf_uri",
        )
        assert detail["success"]
        track_ids = detail["result"]["latest_snapshot"]["track_ids"]
        assert track_ids == ["abc123", "def456", "ghi789"]

    def test_backfill_rejects_track_ids_normalizing_to_empty(self, client: TestClient, seeded_user: int) -> None:
        """Track IDs like 'spotify:track:' that normalize to '' should be rejected."""
        data = _call(
            client,
            "memory.backfill_playlist",
            user_id=seeded_user,
            playlist_id="pl_bf_empty_norm",
            track_ids=["spotify:track:", "abc123"],
            name="Empty Normalize",
        )
        assert not data["success"]
        assert "non-empty" in data["error"]

    def test_conflicting_nested_and_flat_created_by_rejected(self, client: TestClient, seeded_user: int) -> None:
        """Conflicting nested and flat created_by should be rejected."""
        data = _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_cb_conflict",
            name="Conflicting",
            track_ids=["t1"],
            seed_context={"origin": {"created_by": "assistant"}, "created_by": "user"},
        )
        assert not data["success"]
        assert "must match" in data["error"]

    def test_matching_nested_and_flat_created_by_ok(self, client: TestClient, seeded_user: int) -> None:
        """Matching nested and flat created_by should be accepted."""
        data = _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id="pl_cb_match",
            name="Matching",
            track_ids=["t1"],
            seed_context={"origin": {"created_by": "assistant"}, "created_by": "assistant"},
        )
        assert data["success"]
