"""Explorer route modules."""

from explorer.routes.albums import router as albums_router
from explorer.routes.artists import router as artists_router
from explorer.routes.auth import router as auth_router
from explorer.routes.dashboard import router as dashboard_router
from explorer.routes.history import router as history_router
from explorer.routes.landing import router as landing_router
from explorer.routes.memory_playlists import router as memory_playlists_router
from explorer.routes.playlists import router as playlists_router
from explorer.routes.profile import router as profile_router
from explorer.routes.settings import router as settings_router
from explorer.routes.taste import router as taste_router
from explorer.routes.tracks import router as tracks_router

__all__ = [
    "albums_router",
    "artists_router",
    "auth_router",
    "dashboard_router",
    "history_router",
    "landing_router",
    "memory_playlists_router",
    "playlists_router",
    "profile_router",
    "settings_router",
    "taste_router",
    "tracks_router",
]
