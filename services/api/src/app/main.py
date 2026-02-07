"""Main FastAPI application for Spotify MCP API."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import router as auth_router
from app.dependencies import db_manager


class SpotifyMCPApp:
    """Application container — configures middleware, routers, and lifespan."""

    app: FastAPI

    def __init__(self) -> None:
        self.app = FastAPI(
            title="Spotify MCP API",
            description="Spotify OAuth, MCP tool endpoints, and admin APIs",
            version="0.1.0",
            lifespan=self._lifespan,
        )
        self._setup_middleware()
        self._setup_routers()

    @staticmethod
    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
        """Application lifespan: clean up database connections on shutdown."""
        yield
        await db_manager.dispose()

    def _setup_middleware(self) -> None:
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],  # Configure appropriately for production
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def _setup_routers(self) -> None:
        self.app.include_router(auth_router, prefix="/auth", tags=["auth"])

        @self.app.get("/healthz")
        async def health_check() -> dict[str, str]:
            """Health check endpoint."""
            return {"status": "healthy"}

        @self.app.get("/")
        async def root() -> dict[str, str]:
            """Root endpoint."""
            return {"message": "Spotify MCP API", "version": "0.1.0"}


_application = SpotifyMCPApp()
app: FastAPI = _application.app
