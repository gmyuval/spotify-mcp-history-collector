"""Tests for admin ZIP upload endpoint."""

import io
import zipfile

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.dependencies import db_manager
from app.main import app
from app.settings import AppSettings, get_settings
from shared.db.base import Base
from shared.db.models.user import User

TEST_FERNET_KEY = Fernet.generate_key().decode()


def _test_settings() -> AppSettings:
    return AppSettings(
        SPOTIFY_CLIENT_ID="test-client-id",
        SPOTIFY_CLIENT_SECRET="test-client-secret",
        TOKEN_ENCRYPTION_KEY=TEST_FERNET_KEY,
        UPLOAD_DIR="./test_uploads",
        IMPORT_MAX_ZIP_SIZE_MB=1,
    )


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
def override_deps(async_engine):  # type: ignore[no-untyped-def]
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_session():  # type: ignore[no-untyped-def]
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[db_manager.dependency] = _override_session
    app.dependency_overrides[get_settings] = _test_settings
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client(override_deps) -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(app)


@pytest.fixture
async def test_user(async_engine) -> int:  # type: ignore[no-untyped-def]
    """Create a test user and return their ID."""
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        user = User(spotify_user_id="testuser", display_name="Test User")
        session.add(user)
        await session.flush()
        user_id = user.id
        await session.commit()
    return user_id


def _make_zip_bytes() -> bytes:
    """Create minimal valid ZIP file bytes."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("endsong_0.json", "[]")
    return buf.getvalue()


def test_upload_valid_zip(client: TestClient, test_user: int) -> None:
    """Upload a valid ZIP creates an ImportJob with PENDING status."""
    zip_bytes = _make_zip_bytes()
    response = client.post(
        f"/admin/users/{test_user}/import",
        files={"file": ("export.zip", zip_bytes, "application/zip")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == test_user
    assert data["status"] == "pending"
    assert data["file_size_bytes"] > 0


def test_upload_nonexistent_user(client: TestClient) -> None:
    """Upload to non-existent user returns 404."""
    zip_bytes = _make_zip_bytes()
    response = client.post(
        "/admin/users/9999/import",
        files={"file": ("export.zip", zip_bytes, "application/zip")},
    )
    assert response.status_code == 404


def test_upload_non_zip_file(client: TestClient, test_user: int) -> None:
    """Upload non-ZIP file returns 400."""
    response = client.post(
        f"/admin/users/{test_user}/import",
        files={"file": ("data.csv", b"not,a,zip", "text/csv")},
    )
    assert response.status_code == 400


def test_get_import_job_status(client: TestClient, test_user: int) -> None:
    """Upload then get status returns correct data."""
    zip_bytes = _make_zip_bytes()
    upload_response = client.post(
        f"/admin/users/{test_user}/import",
        files={"file": ("export.zip", zip_bytes, "application/zip")},
    )
    job_id = upload_response.json()["id"]

    response = client.get(f"/admin/import-jobs/{job_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pending"
    assert data["records_ingested"] == 0


def test_get_nonexistent_import_job(client: TestClient) -> None:
    """Get non-existent import job returns 404."""
    response = client.get("/admin/import-jobs/9999")
    assert response.status_code == 404
