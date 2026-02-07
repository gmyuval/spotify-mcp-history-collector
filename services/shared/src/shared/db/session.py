"""Database session management via DatabaseManager class."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from shared.config.database import DatabaseSettings


class DatabaseManager:
    """Manages async database engine and session lifecycle.

    Usage:
        db = DatabaseManager.from_env()

        # As context manager
        async with db.session() as session:
            result = await session.execute(query)

        # As FastAPI dependency
        app.dependency_overrides[db.dependency] = ...

        # Cleanup
        await db.dispose()
    """

    def __init__(self, settings: DatabaseSettings) -> None:
        self._settings = settings
        self._engine = create_async_engine(
            settings.database_url,
            echo=settings.echo,
            poolclass=NullPool if settings.use_null_pool else None,
            pool_pre_ping=settings.pool_pre_ping,
        )
        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

    @classmethod
    def from_env(cls) -> Self:
        """Create a DatabaseManager from environment variables."""
        return cls(DatabaseSettings())

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession]:
        """Get a database session with automatic commit/rollback.

        Commits on success, rolls back on exception.
        """
        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    async def dependency(self) -> AsyncGenerator[AsyncSession]:
        """FastAPI Depends() compatible session provider."""
        async with self.session() as session:
            yield session

    async def dispose(self) -> None:
        """Dispose of the engine and release all connections."""
        await self._engine.dispose()
