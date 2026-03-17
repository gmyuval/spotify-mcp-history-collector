"""Tests for ApiTokenService — token CRUD operations."""

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.auth.api_tokens import ApiTokenService, _hash_token
from shared.db.base import Base
from shared.db.models import ApiToken
from shared.db.models.user import User


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
async def session(async_engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess


@pytest.fixture
async def user_id(session: AsyncSession) -> int:
    user = User(spotify_user_id="tokenuser", display_name="Token User")
    session.add(user)
    await session.flush()
    return user.id


class TestCreateToken:
    async def test_create_returns_plaintext_and_prefix(self, session: AsyncSession, user_id: int) -> None:
        result = await ApiTokenService.create(user_id, "My Token", session)
        assert result.name == "My Token"
        assert result.token.startswith("smcp_")
        assert result.prefix == result.token[:8]
        assert result.token_id > 0

    async def test_create_stores_hash_not_plaintext(self, session: AsyncSession, user_id: int) -> None:
        result = await ApiTokenService.create(user_id, "Test", session)
        await session.commit()

        # Verify the DB row has a hash, not the raw token
        from sqlalchemy import select

        row = (await session.execute(select(ApiToken).where(ApiToken.id == result.token_id))).scalar_one()
        assert row.token_hash == _hash_token(result.token)
        assert row.token_hash != result.token

    async def test_duplicate_names_allowed(self, session: AsyncSession, user_id: int) -> None:
        t1 = await ApiTokenService.create(user_id, "Same Name", session)
        t2 = await ApiTokenService.create(user_id, "Same Name", session)
        assert t1.token_id != t2.token_id
        assert t1.token != t2.token


class TestValidateToken:
    async def test_valid_token_returns_user_id(self, session: AsyncSession, user_id: int) -> None:
        created = await ApiTokenService.create(user_id, "Valid", session)
        await session.commit()

        result = await ApiTokenService.validate(created.token, session)
        assert result == user_id

    async def test_revoked_token_returns_none(self, session: AsyncSession, user_id: int) -> None:
        created = await ApiTokenService.create(user_id, "Revoked", session)
        await session.commit()

        await ApiTokenService.revoke(created.token_id, user_id, session)
        await session.commit()

        result = await ApiTokenService.validate(created.token, session)
        assert result is None

    async def test_unknown_token_returns_none(self, session: AsyncSession) -> None:
        result = await ApiTokenService.validate("smcp_nonexistent_token_12345678901234567890", session)
        assert result is None

    async def test_validate_updates_last_used_at(self, session: AsyncSession, user_id: int) -> None:
        created = await ApiTokenService.create(user_id, "Track Usage", session)
        await session.commit()

        # Before validation, last_used_at should be None
        from sqlalchemy import select

        row = (await session.execute(select(ApiToken).where(ApiToken.id == created.token_id))).scalar_one()
        assert row.last_used_at is None

        await ApiTokenService.validate(created.token, session)
        await session.commit()

        await session.refresh(row)
        assert row.last_used_at is not None


class TestListTokens:
    async def test_list_returns_only_active(self, session: AsyncSession, user_id: int) -> None:
        await ApiTokenService.create(user_id, "Active 1", session)
        revoked = await ApiTokenService.create(user_id, "To Revoke", session)
        await ApiTokenService.create(user_id, "Active 2", session)
        await session.commit()

        await ApiTokenService.revoke(revoked.token_id, user_id, session)
        await session.commit()

        tokens = await ApiTokenService.list_tokens(user_id, session)
        assert len(tokens) == 2
        names = {t.name for t in tokens}
        assert names == {"Active 1", "Active 2"}

    async def test_list_scoped_to_user(self, session: AsyncSession, user_id: int) -> None:
        user2 = User(spotify_user_id="otheruser", display_name="Other")
        session.add(user2)
        await session.flush()

        await ApiTokenService.create(user_id, "User 1 Token", session)
        await ApiTokenService.create(user2.id, "User 2 Token", session)
        await session.commit()

        tokens = await ApiTokenService.list_tokens(user_id, session)
        assert len(tokens) == 1
        assert tokens[0].name == "User 1 Token"


class TestRevokeToken:
    async def test_revoke_returns_true(self, session: AsyncSession, user_id: int) -> None:
        created = await ApiTokenService.create(user_id, "To Revoke", session)
        await session.commit()

        result = await ApiTokenService.revoke(created.token_id, user_id, session)
        assert result is True

    async def test_revoke_nonexistent_returns_false(self, session: AsyncSession, user_id: int) -> None:
        result = await ApiTokenService.revoke(99999, user_id, session)
        assert result is False

    async def test_revoke_wrong_user_returns_false(self, session: AsyncSession, user_id: int) -> None:
        created = await ApiTokenService.create(user_id, "Protected", session)
        await session.commit()

        result = await ApiTokenService.revoke(created.token_id, user_id + 999, session)
        assert result is False

    async def test_double_revoke_returns_false(self, session: AsyncSession, user_id: int) -> None:
        created = await ApiTokenService.create(user_id, "Once", session)
        await session.commit()

        assert await ApiTokenService.revoke(created.token_id, user_id, session) is True
        await session.commit()
        assert await ApiTokenService.revoke(created.token_id, user_id, session) is False
