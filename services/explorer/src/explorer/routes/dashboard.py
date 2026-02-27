"""Dashboard page — listening stats overview."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from explorer.api_client import ApiError, ExplorerApiClient
from explorer.routes._helpers import require_login


class DashboardRouter:
    """Dashboard page showing user's listening stats."""

    def __init__(self) -> None:
        self.router = APIRouter()
        self.router.add_api_route("/", self.dashboard, methods=["GET"], response_class=HTMLResponse)

    async def dashboard(self, request: Request) -> HTMLResponse:
        """Render the main dashboard with stats, top artists, and top tracks."""
        token = require_login(request)
        if isinstance(token, RedirectResponse):
            return token  # type: ignore[return-value]

        api: ExplorerApiClient = request.app.state.api
        error: str | None = None
        dashboard_data: dict[str, object] = {}

        try:
            dashboard_data = await api.get_dashboard(token)
        except ApiError as e:
            if e.status_code == 401:
                return RedirectResponse(url="/login", status_code=303)  # type: ignore[return-value]
            error = e.detail

        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            "dashboard.html",
            {
                "request": request,
                "active_page": "dashboard",
                "data": dashboard_data,
                "error": error,
            },
        )


_instance = DashboardRouter()
router = _instance.router
