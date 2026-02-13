"""Main FastAPI application for Spotify MCP Admin Frontend."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from frontend.api_client import AdminApiClient, build_auth_headers
from frontend.settings import get_settings


class FrontendApp:
    """Application container — configures templates, static files, routes, and lifespan."""

    app: FastAPI

    def __init__(self) -> None:
        self.app = FastAPI(
            title="Spotify MCP Admin Frontend",
            description="Management UI for users, sync status, analytics, logs",
            version="0.1.0",
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
        self.app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    def _setup_templates(self) -> None:
        templates_dir = Path(__file__).parent / "templates"
        self.app.state.templates = Jinja2Templates(directory=str(templates_dir))

    def _setup_routers(self) -> None:
        from frontend.routes import (
            dashboard_router,
            imports_router,
            jobs_router,
            logs_router,
            users_router,
        )

        self.app.include_router(dashboard_router)
        self.app.include_router(users_router, prefix="/users", tags=["users"])
        self.app.include_router(jobs_router, prefix="/jobs", tags=["jobs"])
        self.app.include_router(imports_router, prefix="/imports", tags=["imports"])
        self.app.include_router(logs_router, prefix="/logs", tags=["logs"])

        @self.app.get("/healthz")
        async def health_check() -> dict[str, str]:
            """Health check endpoint."""
            return {"status": "healthy"}


_application = FrontendApp()
app: FastAPI = _application.app
