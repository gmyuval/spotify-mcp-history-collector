"""Tests for ZipImportService."""

import json
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from collector.settings import CollectorSettings
from collector.zip_import import ZipImportService
from shared.db.base import Base
from shared.db.enums import ImportStatus
from shared.db.models.music import Play
from shared.db.models.operations import ImportJob
from shared.db.models.user import User
from shared.db.session import DatabaseManager

TEST_FERNET_KEY = Fernet.generate_key().decode()


def _test_settings(**overrides: object) -> CollectorSettings:
    defaults: dict[str, object] = {
        "SPOTIFY_CLIENT_ID": "test-id",
        "SPOTIFY_CLIENT_SECRET": "test-secret",
        "TOKEN_ENCRYPTION_KEY": TEST_FERNET_KEY,
        "IMPORT_MAX_ZIP_SIZE_MB": 500,
        "IMPORT_MAX_RECORDS": 5_000_000,
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


@pytest.fixture
def db_manager(async_engine):  # type: ignore[no-untyped-def]
    """Create a mock DatabaseManager that yields real sessions."""
    from contextlib import asynccontextmanager

    manager = AsyncMock(spec=DatabaseManager)
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def _mock_session():  # type: ignore[no-untyped-def]
        async with session_factory() as s:
            yield s
            await s.commit()

    manager.session = _mock_session
    return manager


def _create_test_zip(tmp_path: Path, records: list[dict[str, object]], filename: str = "endsong_0.json") -> Path:
    """Create a test ZIP file with the given records."""
    zip_path = tmp_path / "test_export.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(filename, json.dumps(records))
    return zip_path


async def test_process_no_pending_jobs(db_manager: AsyncMock) -> None:
    """Returns 0 when no pending import jobs exist."""
    service = ZipImportService(_test_settings())
    result = await service.process_pending_imports(db_manager)
    assert result == 0


async def test_process_pending_import_success(
    async_session: AsyncSession,
    db_manager: AsyncMock,
    tmp_path: Path,
) -> None:
    """Processes a pending import job to completion."""
    # Create user
    user = User(spotify_user_id="testuser", display_name="Test")
    async_session.add(user)
    await async_session.flush()

    # Create test ZIP
    records = [
        {
            "ts": "2023-06-15T10:30:00Z",
            "ms_played": 180000,
            "master_metadata_track_name": "Track A",
            "master_metadata_album_artist_name": "Artist A",
            "master_metadata_album_album_name": "Album A",
            "spotify_track_uri": "spotify:track:AAA",
        },
        {
            "ts": "2023-06-15T11:00:00Z",
            "ms_played": 200000,
            "master_metadata_track_name": "Track B",
            "master_metadata_album_artist_name": "Artist B",
            "master_metadata_album_album_name": "Album B",
        },
    ]
    zip_path = _create_test_zip(tmp_path, records)

    # Create import job
    import_job = ImportJob(
        user_id=user.id,
        status=ImportStatus.PENDING,
        file_path=str(zip_path),
        file_size_bytes=zip_path.stat().st_size,
    )
    async_session.add(import_job)
    await async_session.commit()

    # Process
    service = ZipImportService(_test_settings())
    processed = await service.process_pending_imports(db_manager)
    assert processed == 1

    # Verify job status
    async with db_manager.session() as session:
        result = await session.execute(select(ImportJob).where(ImportJob.id == import_job.id))
        job = result.scalar_one()
        assert job.status == ImportStatus.SUCCESS
        assert job.records_ingested == 2
        assert job.format_detected == "extended"
        assert job.earliest_played_at is not None
        assert job.latest_played_at is not None

    # Verify plays were inserted
    async with db_manager.session() as session:
        result = await session.execute(select(Play).where(Play.user_id == user.id))
        plays = result.scalars().all()
        assert len(plays) == 2


async def test_process_import_file_not_found(
    async_session: AsyncSession,
    db_manager: AsyncMock,
) -> None:
    """Marks job as ERROR when ZIP file doesn't exist."""
    user = User(spotify_user_id="testuser", display_name="Test")
    async_session.add(user)
    await async_session.flush()

    import_job = ImportJob(
        user_id=user.id,
        status=ImportStatus.PENDING,
        file_path="/nonexistent/path.zip",
        file_size_bytes=0,
    )
    async_session.add(import_job)
    await async_session.commit()

    service = ZipImportService(_test_settings())
    processed = await service.process_pending_imports(db_manager)
    assert processed == 1

    async with db_manager.session() as session:
        result = await session.execute(select(ImportJob).where(ImportJob.id == import_job.id))
        job = result.scalar_one()
        assert job.status == ImportStatus.ERROR
        assert "not found" in (job.error_message or "").lower()


async def test_process_import_bad_format(
    async_session: AsyncSession,
    db_manager: AsyncMock,
    tmp_path: Path,
) -> None:
    """Marks job as ERROR when ZIP has no recognizable format."""
    user = User(spotify_user_id="testuser", display_name="Test")
    async_session.add(user)
    await async_session.flush()

    # Create ZIP with unrecognizable content
    zip_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("readme.txt", "not spotify data")

    import_job = ImportJob(
        user_id=user.id,
        status=ImportStatus.PENDING,
        file_path=str(zip_path),
        file_size_bytes=zip_path.stat().st_size,
    )
    async_session.add(import_job)
    await async_session.commit()

    service = ZipImportService(_test_settings())
    processed = await service.process_pending_imports(db_manager)
    assert processed == 1

    async with db_manager.session() as session:
        result = await session.execute(select(ImportJob).where(ImportJob.id == import_job.id))
        job = result.scalar_one()
        assert job.status == ImportStatus.ERROR
        assert "no recognizable" in (job.error_message or "").lower()
