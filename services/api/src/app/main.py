"""Main FastAPI application for Spotify MCP API."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.admin import router as admin_router
from app.auth import router as auth_router
from app.auth.middleware import JWTAuthMiddleware
from app.constants import APP_DESCRIPTION, APP_TITLE, APP_VERSION, Routes, ServiceName
from app.dependencies import db_manager
from app.explorer.router import router as explorer_router
from app.history import router as history_router
from app.logging import DBLogHandler, configure_logging
from app.mcp import router as mcp_router
from app.middleware import (
    RateLimitMiddleware,
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
)
from app.settings import get_settings


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

    @staticmethod
    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
        """Application lifespan: start DB log handler, clean up on shutdown."""
        db_log_handler = DBLogHandler(db_manager, service=ServiceName.API)
        await db_log_handler.start()
        logging.getLogger().addHandler(db_log_handler)
        try:
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

        @self.app.get(Routes.HEALTH)
        async def health_check() -> dict[str, str]:
            """Health check endpoint."""
            return {"status": "healthy"}

        @self.app.get("/")
        async def root() -> dict[str, str]:
            """Root endpoint."""
            return {"message": APP_TITLE, "version": APP_VERSION}


_application = SpotifyMCPApp()
app: FastAPI = _application.app
