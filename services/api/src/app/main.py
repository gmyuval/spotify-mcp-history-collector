"""Main FastAPI application for Spotify MCP API."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import TypedDict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.routing import Mount

from app.admin import router as admin_router
from app.auth import router as auth_router
from app.auth.middleware import JWTAuthMiddleware
from app.constants import APP_DESCRIPTION, APP_TITLE, Routes, ServiceName
from app.dependencies import db_manager
from app.explorer.router import router as explorer_router
from app.history import router as history_router
from app.logging import DBLogHandler, configure_logging
from app.mcp import router as mcp_router
from app.mcp.mcp_server import create_mcp_asgi_app, create_mcp_server
from app.middleware import (
    RateLimitMiddleware,
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
)
from app.settings import get_settings
from shared.version import __version__ as APP_VERSION


class HealthResponse(TypedDict):
    """Schema for health check responses."""

    status: str
    version: str


class SpotifyMCPApp:
    """Application container — configures middleware, routers, and lifespan."""

    app: FastAPI

    def __init__(self) -> None:
        configure_logging(ServiceName.API)
        self.app = FastAPI(
            title=APP_TITLE,
            description=APP_DESCRIPTION,
            version=APP_VERSION,
            lifespan=self._lifespan,
        )
        self._setup_middleware()
        self._setup_routers()

    @asynccontextmanager
    async def _lifespan(self, app: FastAPI) -> AsyncGenerator[None]:  # noqa: ARG002
        """Application lifespan: start DB log handler, MCP session manager, clean up on shutdown.

        A fresh FastMCP server is created on each lifespan entry because the
        MCP SDK's ``StreamableHTTPSessionManager.run()`` can only be called
        once per instance.  Re-creating it here allows tests (which re-enter
        the lifespan via multiple ``TestClient`` contexts) to work correctly.
        """
        mcp_fastmcp = create_mcp_server()
        mcp_asgi_app = create_mcp_asgi_app(mcp_fastmcp)
        # Update the mounted ASGI app so it points to the fresh instance
        self._mcp_mount.app = mcp_asgi_app

        db_log_handler = DBLogHandler(db_manager, service=ServiceName.API)
        await db_log_handler.start()
        logging.getLogger().addHandler(db_log_handler)
        try:
            async with mcp_fastmcp.session_manager.run():
                yield
        finally:
            logging.getLogger().removeHandler(db_log_handler)
            await db_log_handler.stop()
            await db_manager.dispose()

    def _setup_middleware(self) -> None:
        settings = get_settings()

        # Rate limiting (outermost — runs first)
        self.app.add_middleware(
            RateLimitMiddleware,
            auth_limit=settings.RATE_LIMIT_AUTH_PER_MINUTE,
            mcp_limit=settings.RATE_LIMIT_MCP_PER_MINUTE,
        )

        # JWT authentication (extracts user context from tokens)
        self.app.add_middleware(JWTAuthMiddleware)

        # Security headers
        self.app.add_middleware(SecurityHeadersMiddleware)

        # Request-ID (generates/propagates X-Request-ID)
        self.app.add_middleware(RequestIDMiddleware)

        # CORS
        origins = [o.strip() for o in settings.CORS_ALLOWED_ORIGINS.split(",") if o.strip()]
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def _setup_routers(self) -> None:
        self.app.include_router(auth_router, prefix=Routes.AUTH.prefix, tags=[Routes.AUTH.tag])
        self.app.include_router(admin_router, prefix=Routes.ADMIN.prefix, tags=[Routes.ADMIN.tag])
        self.app.include_router(history_router, prefix=Routes.HISTORY.prefix, tags=[Routes.HISTORY.tag])
        self.app.include_router(mcp_router, prefix=Routes.MCP.prefix, tags=[Routes.MCP.tag])
        self.app.include_router(explorer_router, prefix=Routes.EXPLORER.prefix, tags=[Routes.EXPLORER.tag])

        # Mount MCP SDK ASGI app at /mcp/v1 (standards-compliant JSON-RPC 2.0)
        # A placeholder app is used here; the real ASGI app is set in _lifespan
        # (fresh per entry, since StreamableHTTPSessionManager.run() is single-use).
        mcp_placeholder = create_mcp_server()
        self._mcp_mount = Mount("/mcp/v1", app=create_mcp_asgi_app(mcp_placeholder))
        self.app.routes.append(self._mcp_mount)

        @self.app.get(Routes.HEALTH)
        async def health_check() -> HealthResponse:
            """Health check endpoint."""
            return {"status": "healthy", "version": APP_VERSION}

        @self.app.get("/")
        async def root() -> dict[str, str]:
            """Root endpoint."""
            return {"message": APP_TITLE, "version": APP_VERSION}


_application = SpotifyMCPApp()
app: FastAPI = _application.app
