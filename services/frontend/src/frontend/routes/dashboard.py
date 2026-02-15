"""Dashboard page — class-based router for system health overview."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from frontend.api_client import AdminApiClient, ApiError


class DashboardRouter:
    """Class-based router for the dashboard page."""

    def __init__(self) -> None:
        self.router = APIRouter()
        self.router.add_api_route("/", self.dashboard, methods=["GET"], response_class=HTMLResponse)
        self.router.add_api_route(
            "/partials/sync-status", self.sync_status_partial, methods=["GET"], response_class=HTMLResponse
        )
        self.router.add_api_route(
            "/partials/active-operations", self.active_operations_partial, methods=["GET"], response_class=HTMLResponse
        )

    async def _fetch_active_operations(self, api: AdminApiClient) -> tuple[list[object], list[object]]:
        """Fetch currently active imports and jobs."""
        active_imports: list[object] = []
        active_jobs: list[object] = []
        try:
            processing = await api.list_import_jobs(status="processing", limit=10)
            active_imports = processing.get("items", [])
            running = await api.list_job_runs(status="running", limit=10)
            active_jobs = running.get("items", [])
        except ApiError:
            pass
        return active_imports, active_jobs

    async def dashboard(self, request: Request) -> HTMLResponse:
        """Render the main dashboard page."""
        api: AdminApiClient = request.app.state.api
        error: str | None = None
        sync_status: dict[str, object] = {}
        recent_jobs: list[object] = []
        recent_imports: list[object] = []

        try:
            sync_status = await api.get_sync_status()
            jobs_data = await api.list_job_runs(limit=5)
            recent_jobs = jobs_data.get("items", [])
            imports_data = await api.list_import_jobs(limit=5)
            recent_imports = imports_data.get("items", [])
        except ApiError as e:
            error = e.detail

        active_imports, active_jobs = await self._fetch_active_operations(api)

        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            "dashboard.html",
            {
                "request": request,
                "active_page": "dashboard",
                "sync_status": sync_status,
                "recent_jobs": recent_jobs,
                "recent_imports": recent_imports,
                "active_imports": active_imports,
                "active_jobs": active_jobs,
                "error": error,
            },
        )

    async def sync_status_partial(self, request: Request) -> HTMLResponse:
        """HTMX partial — sync status cards (polled every 30s)."""
        api: AdminApiClient = request.app.state.api
        try:
            sync_status = await api.get_sync_status()
        except ApiError:
            sync_status = {}

        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            "partials/_sync_status.html",
            {"request": request, "sync_status": sync_status},
        )

    async def active_operations_partial(self, request: Request) -> HTMLResponse:
        """HTMX partial — active operations (polled every 10s)."""
        api: AdminApiClient = request.app.state.api
        active_imports, active_jobs = await self._fetch_active_operations(api)

        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            "partials/_active_operations.html",
            {
                "request": request,
                "active_imports": active_imports,
                "active_jobs": active_jobs,
            },
        )


_instance = DashboardRouter()
router = _instance.router
