"""Main FastAPI application for Spotify MCP Explorer Frontend."""

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TypedDict

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from explorer.api_client import ExplorerApiClient
from explorer.middleware import GoogleAuthMiddleware
from explorer.settings import get_settings

# Explorer has no access to the shared package — read version from env var set by docker-compose/CI.
__version__ = os.environ.get("APP_VERSION", "0.2.0")


class HealthResponse(TypedDict):
    """Schema for health check responses."""

    status: str
    version: str


class ExplorerApp:
    """Application container — configures templates, static files, routes, and lifespan."""

    app: FastAPI

    def __init__(self) -> None:
        self.app = FastAPI(
            title="Spotify MCP Explorer",
            description="User-facing listening data exploration UI",
            version=__version__,
            lifespan=self._lifespan,
        )
        self._setup_static_files()
        self._setup_templates()
        self._setup_routers()
        self._setup_middleware()

    @staticmethod
    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
        """Application lifespan: create/destroy API client."""
        settings = get_settings()
        api = ExplorerApiClient(base_url=settings.API_BASE_URL)
        app.state.api = api
        app.state.settings = settings
        try:
            yield
        finally:
            await api.close()

    def _setup_static_files(self) -> None:
        static_dir = Path(__file__).parent / "static"
        self.app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    def _setup_templates(self) -> None:
        templates_dir = Path(__file__).parent / "templates"
        templates = Jinja2Templates(directory=str(templates_dir))
        templates.env.globals["version"] = __version__
        self.app.state.templates = templates

    def _setup_routers(self) -> None:
        from explorer.routes import (
            auth_router,
            dashboard_router,
            history_router,
            landing_router,
            memory_playlists_router,
            playlists_router,
            profile_router,
            taste_router,
        )

        self.app.include_router(landing_router)
        self.app.include_router(auth_router)
        self.app.include_router(dashboard_router)
        self.app.include_router(history_router, prefix="/history", tags=["history"])
        # memory_playlists must come before playlists to avoid /{spotify_playlist_id} match
        self.app.include_router(memory_playlists_router, prefix="/playlists/memory", tags=["memory-playlists"])
        self.app.include_router(playlists_router, prefix="/playlists", tags=["playlists"])
        self.app.include_router(profile_router)
        self.app.include_router(taste_router)

        @self.app.get("/healthz")
        async def health_check() -> HealthResponse:
            """Health check endpoint."""
            return {"status": "healthy", "version": __version__}

    def _setup_middleware(self) -> None:
        self.app.add_middleware(GoogleAuthMiddleware)


_application = ExplorerApp()
app: FastAPI = _application.app
