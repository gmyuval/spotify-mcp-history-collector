"""Frontend route modules."""

from frontend.routes.dashboard import router as dashboard_router
from frontend.routes.imports import router as imports_router
from frontend.routes.jobs import router as jobs_router
from frontend.routes.logs import router as logs_router
from frontend.routes.roles import router as roles_router
from frontend.routes.users import router as users_router

__all__ = [
    "dashboard_router",
    "imports_router",
    "jobs_router",
    "logs_router",
    "roles_router",
    "users_router",
]
