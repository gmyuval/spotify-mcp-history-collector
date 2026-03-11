"""Main FastAPI application for Spotify MCP Admin Frontend."""

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TypedDict

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from frontend.api_client import AdminApiClient, build_auth_headers
from frontend.settings import get_settings

# Frontend has no access to the shared package — read version from env var set by docker-compose/CI.
__version__ = os.environ.get("APP_VERSION", "0.2.0")


class HealthResponse(TypedDict):
    """Schema for health check responses."""

    status: str
    version: str


class FrontendApp:
    """Application container — configures templates, static files, routes, and lifespan."""

    app: FastAPI

    def __init__(self) -> None:
        self.app = FastAPI(
            title="Spotify MCP Admin Frontend",
            description="Management UI for users, sync status, analytics, logs",
            version=__version__,
            lifespan=self._lifespan,
        )
        self._setup_static_files()
        self._setup_templates()
        self._setup_routers()

    @staticmethod
    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
        """Application lifespan: create/destroy API client."""
        settings = get_settings()
        auth_headers = build_auth_headers(
            auth_mode=settings.FRONTEND_AUTH_MODE,
            token=settings.ADMIN_TOKEN,
            username=settings.ADMIN_USERNAME,
            password=settings.ADMIN_PASSWORD,
        )
        api = AdminApiClient(
            base_url=settings.API_BASE_URL,
            auth_headers=auth_headers,
        )
        app.state.api = api
        try:
            yield
        finally:
            await api.close()

    def _setup_static_files(self) -> None:
        static_dir = Path(__file__).parent / "static"
        settings = get_settings()
        self.app.mount(f"{settings.BASE_PATH}/static", StaticFiles(directory=str(static_dir)), name="static")

    def _setup_templates(self) -> None:
        templates_dir = Path(__file__).parent / "templates"
        templates = Jinja2Templates(directory=str(templates_dir))
        settings = get_settings()
        templates.env.globals["base_path"] = settings.BASE_PATH
        templates.env.globals["version"] = __version__
        self.app.state.templates = templates

    def _setup_routers(self) -> None:
        from frontend.routes import (
            dashboard_router,
            imports_router,
            jobs_router,
            logs_router,
            roles_router,
            settings_router,
            users_router,
        )

        settings = get_settings()
        bp = settings.BASE_PATH

        self.app.include_router(dashboard_router, prefix=bp)
        self.app.include_router(users_router, prefix=f"{bp}/users", tags=["users"])
        self.app.include_router(roles_router, prefix=f"{bp}/roles", tags=["roles"])
        self.app.include_router(jobs_router, prefix=f"{bp}/jobs", tags=["jobs"])
        self.app.include_router(imports_router, prefix=f"{bp}/imports", tags=["imports"])
        self.app.include_router(logs_router, prefix=f"{bp}/logs", tags=["logs"])
        self.app.include_router(settings_router, prefix=f"{bp}/settings", tags=["settings"])

        @self.app.get("/healthz")
        async def health_check() -> HealthResponse:
            """Health check endpoint."""
            return {"status": "healthy", "version": __version__}


_application = FrontendApp()
app: FastAPI = _application.app
