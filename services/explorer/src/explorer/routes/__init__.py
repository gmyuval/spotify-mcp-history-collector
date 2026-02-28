"""Explorer route modules."""

from explorer.routes.auth import router as auth_router
from explorer.routes.dashboard import router as dashboard_router
from explorer.routes.history import router as history_router
from explorer.routes.landing import router as landing_router
from explorer.routes.playlists import router as playlists_router
from explorer.routes.profile import router as profile_router

__all__ = [
    "auth_router",
    "dashboard_router",
    "history_router",
    "landing_router",
    "playlists_router",
    "profile_router",
]
