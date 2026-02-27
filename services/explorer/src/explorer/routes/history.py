"""History page — paginated play history with search."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from explorer.api_client import ApiError, ExplorerApiClient
from explorer.routes._helpers import require_login, safe_int


class HistoryRouter:
    """Paginated play history with search."""

    def __init__(self) -> None:
        self.router = APIRouter()
        self.router.add_api_route("/", self.history, methods=["GET"], response_class=HTMLResponse)
        self.router.add_api_route(
            "/partials/history-table", self.history_table_partial, methods=["GET"], response_class=HTMLResponse
        )

    async def history(self, request: Request) -> HTMLResponse:
        """Render the full history page."""
        token = require_login(request)
        if isinstance(token, RedirectResponse):
            return token  # type: ignore[return-value]

        api: ExplorerApiClient = request.app.state.api
        error: str | None = None
        data: dict[str, object] = {"items": [], "total": 0, "limit": 50, "offset": 0}

        limit = safe_int(request.query_params.get("limit"), 50)
        offset = safe_int(request.query_params.get("offset"), 0)
        q = request.query_params.get("q", "")

        try:
            data = await api.get_history(token, limit=limit, offset=offset, q=q or None)
        except ApiError as e:
            if e.status_code == 401:
                return RedirectResponse(url="/login", status_code=303)  # type: ignore[return-value]
            error = e.detail

        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            "history.html",
            {
                "request": request,
                "active_page": "history",
                "items": data.get("items", []),
                "total": data.get("total", 0),
                "limit": limit,
                "offset": offset,
                "q": q,
                "error": error,
            },
        )

    async def history_table_partial(self, request: Request) -> HTMLResponse:
        """HTMX partial — history table body with pagination."""
        token = require_login(request)
        if isinstance(token, RedirectResponse):
            return token  # type: ignore[return-value]

        api: ExplorerApiClient = request.app.state.api
        limit = safe_int(request.query_params.get("limit"), 50)
        offset = safe_int(request.query_params.get("offset"), 0)
        q = request.query_params.get("q", "")

        try:
            data = await api.get_history(token, limit=limit, offset=offset, q=q or None)
        except ApiError:
            data = {"items": [], "total": 0}

        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            "partials/_history_table.html",
            {
                "request": request,
                "items": data.get("items", []),
                "total": data.get("total", 0),
                "limit": limit,
                "offset": offset,
                "q": q,
            },
        )


_instance = HistoryRouter()
router = _instance.router
