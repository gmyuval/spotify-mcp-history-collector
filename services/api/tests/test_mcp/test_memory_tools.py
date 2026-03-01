"""Tests for memory.* MCP tools (taste profile + preference events)."""

from collections.abc import AsyncGenerator, Generator

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
        user = User(spotify_user_id="memuser", display_name="Memory User")
        session.add(user)
        await session.flush()
        uid = user.id
        await session.commit()
    return uid


@pytest.fixture
async def second_user(async_engine: AsyncEngine) -> int:
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        user = User(spotify_user_id="memuser2", display_name="Memory User 2")
        session.add(user)
        await session.flush()
        uid = user.id
        await session.commit()
    return uid


# ── memory.get_profile ──────────────────────────────────────────────


def test_get_profile_empty(client: TestClient, seeded_user: int) -> None:
    """No profile exists yet — returns empty profile with version 0."""
    resp = client.post("/mcp/call", json={"tool": "memory.get_profile", "user_id": seeded_user})
    data = resp.json()
    assert data["success"]
    result = data["result"]
    assert result["user_id"] == seeded_user
    assert result["profile"] == {}
    assert result["version"] == 0
    assert result["updated_at"] is None


def test_get_profile_invalid_user_id(client: TestClient) -> None:
    """Invalid user_id returns error via ValueError."""
    resp = client.post("/mcp/call", json={"tool": "memory.get_profile", "user_id": -1})
    data = resp.json()
    assert not data["success"]
    assert "user_id must be a positive integer" in data["error"]


# ── memory.update_profile ──────────────────────────────────────────


def test_update_profile_creates_new(client: TestClient, seeded_user: int) -> None:
    """First update creates the profile."""
    patch = {"core_genres": ["symphonic metal"], "energy_preferences": {"default": "upbeat"}}
    resp = client.post(
        "/mcp/call",
        json={
            "tool": "memory.update_profile",
            "user_id": seeded_user,
            "patch": patch,
            "reason": "Initial taste setup",
        },
    )
    data = resp.json()
    assert data["success"]
    result = data["result"]
    assert result["version"] == 1
    assert result["profile"]["core_genres"] == ["symphonic metal"]
    assert result["profile"]["energy_preferences"]["default"] == "upbeat"


def test_update_profile_increments_version(client: TestClient, seeded_user: int) -> None:
    """Each update increments the version."""
    # First update
    client.post(
        "/mcp/call",
        json={"tool": "memory.update_profile", "user_id": seeded_user, "patch": {"core_genres": ["metal"]}},
    )
    # Second update
    resp = client.post(
        "/mcp/call",
        json={"tool": "memory.update_profile", "user_id": seeded_user, "patch": {"avoid": ["pop"]}},
    )
    data = resp.json()
    assert data["success"]
    assert data["result"]["version"] == 2


def test_update_profile_merge_patch(client: TestClient, seeded_user: int) -> None:
    """Patch merges with existing profile (shallow merge)."""
    # Create
    client.post(
        "/mcp/call",
        json={
            "tool": "memory.update_profile",
            "user_id": seeded_user,
            "patch": {"core_genres": ["metal"], "mood": "energetic"},
        },
    )
    # Update — only changes mood, core_genres should persist
    resp = client.post(
        "/mcp/call",
        json={"tool": "memory.update_profile", "user_id": seeded_user, "patch": {"mood": "chill"}},
    )
    result = resp.json()["result"]
    assert result["profile"]["core_genres"] == ["metal"]
    assert result["profile"]["mood"] == "chill"


def test_update_profile_create_if_missing_false(client: TestClient, seeded_user: int) -> None:
    """create_if_missing=false returns error when no profile exists."""
    resp = client.post(
        "/mcp/call",
        json={
            "tool": "memory.update_profile",
            "user_id": seeded_user,
            "patch": {"foo": "bar"},
            "create_if_missing": False,
        },
    )
    data = resp.json()
    assert not data["success"]
    assert "No taste profile exists" in data["error"]


def test_update_profile_empty_patch(client: TestClient, seeded_user: int) -> None:
    """Empty patch returns error."""
    resp = client.post(
        "/mcp/call",
        json={"tool": "memory.update_profile", "user_id": seeded_user, "patch": {}},
    )
    data = resp.json()
    assert not data["success"]
    assert "patch must be a non-empty object" in data["error"]


def test_update_profile_invalid_source(client: TestClient, seeded_user: int) -> None:
    """Invalid source returns error."""
    resp = client.post(
        "/mcp/call",
        json={
            "tool": "memory.update_profile",
            "user_id": seeded_user,
            "patch": {"foo": "bar"},
            "source": "unknown",
        },
    )
    data = resp.json()
    assert not data["success"]
    assert "source must be one of" in data["error"]


def test_update_profile_with_reason_appends_event(client: TestClient, seeded_user: int) -> None:
    """When reason is provided, a preference event is also appended."""
    client.post(
        "/mcp/call",
        json={
            "tool": "memory.update_profile",
            "user_id": seeded_user,
            "patch": {"core_genres": ["metal"]},
            "reason": "User said they like metal",
        },
    )
    # Verify we can get the profile
    resp = client.post("/mcp/call", json={"tool": "memory.get_profile", "user_id": seeded_user})
    data = resp.json()
    assert data["success"]
    assert data["result"]["version"] == 1


# ── memory.append_preference_event ─────────────────────────────────


def test_append_preference_event(client: TestClient, seeded_user: int) -> None:
    """Append a preference event successfully."""
    resp = client.post(
        "/mcp/call",
        json={
            "tool": "memory.append_preference_event",
            "user_id": seeded_user,
            "type": "rule",
            "payload": {"raw_text": "max 3 tracks per artist in a playlist"},
            "source": "user",
        },
    )
    data = resp.json()
    assert data["success"]
    result = data["result"]
    assert result["user_id"] == seeded_user
    assert "event_id" in result
    assert "timestamp" in result


def test_append_preference_event_all_types(client: TestClient, seeded_user: int) -> None:
    """All valid event types are accepted."""
    for event_type in ("like", "dislike", "rule", "feedback", "note"):
        resp = client.post(
            "/mcp/call",
            json={
                "tool": "memory.append_preference_event",
                "user_id": seeded_user,
                "type": event_type,
                "payload": {"raw_text": f"test {event_type}"},
            },
        )
        data = resp.json()
        assert data["success"], f"Failed for type={event_type}"


def test_append_preference_event_invalid_type(client: TestClient, seeded_user: int) -> None:
    """Invalid event type returns error."""
    resp = client.post(
        "/mcp/call",
        json={
            "tool": "memory.append_preference_event",
            "user_id": seeded_user,
            "type": "invalid_type",
            "payload": {"raw_text": "test"},
        },
    )
    data = resp.json()
    assert not data["success"]
    assert "type must be one of" in data["error"]


def test_append_preference_event_invalid_payload(client: TestClient, seeded_user: int) -> None:
    """Non-object payload returns error."""
    resp = client.post(
        "/mcp/call",
        json={
            "tool": "memory.append_preference_event",
            "user_id": seeded_user,
            "type": "note",
            "payload": "not valid json",
        },
    )
    data = resp.json()
    assert not data["success"]
    assert "payload must be valid JSON" in data["error"]

    # Valid JSON but not an object (e.g. array) also rejected
    resp = client.post(
        "/mcp/call",
        json={
            "tool": "memory.append_preference_event",
            "user_id": seeded_user,
            "type": "note",
            "payload": 42,
        },
    )
    data = resp.json()
    assert not data["success"]
    assert "payload must be an object" in data["error"]


def test_append_preference_event_with_timestamp(client: TestClient, seeded_user: int) -> None:
    """Custom timestamp is accepted and stored."""
    resp = client.post(
        "/mcp/call",
        json={
            "tool": "memory.append_preference_event",
            "user_id": seeded_user,
            "type": "like",
            "payload": {"artist": "Nightwish"},
            "timestamp": "2026-01-15T10:00:00Z",
        },
    )
    data = resp.json()
    assert data["success"]
    assert "2026-01-15" in data["result"]["timestamp"]


def test_append_preference_event_invalid_timestamp(client: TestClient, seeded_user: int) -> None:
    """Invalid timestamp returns error."""
    resp = client.post(
        "/mcp/call",
        json={
            "tool": "memory.append_preference_event",
            "user_id": seeded_user,
            "type": "like",
            "payload": {"artist": "Nightwish"},
            "timestamp": "not-a-date",
        },
    )
    data = resp.json()
    assert not data["success"]
    assert "timestamp must be a valid ISO datetime string" in data["error"]


# ── ChatGPT compatibility (JSON strings + event_type alias) ────────


def test_update_profile_patch_as_json_string(client: TestClient, seeded_user: int) -> None:
    """ChatGPT sends patch as a JSON string — should be parsed."""
    resp = client.post(
        "/mcp/call",
        json={
            "tool": "memory.update_profile",
            "user_id": seeded_user,
            "patch": '{"core_genres": ["metal"], "mood": "dark"}',
        },
    )
    data = resp.json()
    assert data["success"]
    assert data["result"]["profile"]["core_genres"] == ["metal"]
    assert data["result"]["profile"]["mood"] == "dark"


def test_append_event_payload_as_json_string(client: TestClient, seeded_user: int) -> None:
    """ChatGPT sends payload as a JSON string — should be parsed."""
    resp = client.post(
        "/mcp/call",
        json={
            "tool": "memory.append_preference_event",
            "user_id": seeded_user,
            "type": "like",
            "payload": '{"raw_text": "I love Nightwish"}',
        },
    )
    data = resp.json()
    assert data["success"]
    assert "event_id" in data["result"]


def test_append_event_event_type_alias(client: TestClient, seeded_user: int) -> None:
    """ChatGPT sends event_type instead of type — should be aliased."""
    resp = client.post(
        "/mcp/call",
        json={
            "tool": "memory.append_preference_event",
            "user_id": seeded_user,
            "event_type": "dislike",
            "payload": {"raw_text": "too much pop"},
        },
    )
    data = resp.json()
    assert data["success"]
    assert "event_id" in data["result"]


# ── Integration: full workflow ──────────────────────────────────────


def test_full_taste_workflow(client: TestClient, seeded_user: int) -> None:
    """End-to-end: create profile, update, append events, get profile."""
    # 1. Get empty profile
    resp = client.post("/mcp/call", json={"tool": "memory.get_profile", "user_id": seeded_user})
    result = resp.json()["result"]
    assert result["version"] == 0

    # 2. Create profile
    resp = client.post(
        "/mcp/call",
        json={
            "tool": "memory.update_profile",
            "user_id": seeded_user,
            "patch": {
                "core_genres": ["symphonic metal", "power metal"],
                "playlist_rules": {"max_tracks_per_artist": 3},
            },
            "reason": "Initial taste setup",
        },
    )
    assert resp.json()["success"]

    # 3. Append a preference event
    resp = client.post(
        "/mcp/call",
        json={
            "tool": "memory.append_preference_event",
            "user_id": seeded_user,
            "type": "rule",
            "payload": {"raw_text": "don't overweight one artist"},
            "source": "user",
        },
    )
    assert resp.json()["success"]

    # 4. Update profile with another patch
    resp = client.post(
        "/mcp/call",
        json={
            "tool": "memory.update_profile",
            "user_id": seeded_user,
            "patch": {"avoid": ["over-weighting a single artist"]},
            "reason": "User feedback",
        },
    )
    result = resp.json()["result"]
    assert result["version"] == 2
    assert "core_genres" in result["profile"]
    assert "avoid" in result["profile"]
    assert "playlist_rules" in result["profile"]

    # 5. Get final profile
    resp = client.post("/mcp/call", json={"tool": "memory.get_profile", "user_id": seeded_user})
    result = resp.json()["result"]
    assert result["version"] == 2
    assert result["profile"]["core_genres"] == ["symphonic metal", "power metal"]
    assert result["profile"]["avoid"] == ["over-weighting a single artist"]


# ── User isolation ──────────────────────────────────────────────────


def test_user_isolation(client: TestClient, seeded_user: int, second_user: int) -> None:
    """User A's profile is not visible to user B (real second user)."""
    # Create profile for seeded_user
    resp = client.post(
        "/mcp/call",
        json={
            "tool": "memory.update_profile",
            "user_id": seeded_user,
            "patch": {"core_genres": ["metal"]},
        },
    )
    assert resp.json()["success"]

    # Second user should have an empty profile, not seeded_user's data
    resp = client.post("/mcp/call", json={"tool": "memory.get_profile", "user_id": second_user})
    result = resp.json()["result"]
    assert result["user_id"] == second_user
    assert result["profile"] == {}
    assert result["version"] == 0

    # Verify seeded_user's profile is still intact
    resp = client.post("/mcp/call", json={"tool": "memory.get_profile", "user_id": seeded_user})
    result = resp.json()["result"]
    assert result["profile"] == {"core_genres": ["metal"]}
    assert result["version"] == 1
