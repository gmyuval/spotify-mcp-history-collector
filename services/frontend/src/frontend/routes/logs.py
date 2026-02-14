"""Logs page — class-based router for searchable log viewer with filtering and purge."""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from frontend.api_client import AdminApiClient, ApiError
from frontend.routes._helpers import safe_int


class LogsRouter:
    """Class-based router for logs pages."""

    def __init__(self) -> None:
        self.router = APIRouter()
        self.router.add_api_route("/", self.list_logs, methods=["GET"], response_class=HTMLResponse)
        self.router.add_api_route(
            "/partials/logs-table", self.logs_table_partial, methods=["GET"], response_class=HTMLResponse
        )
        self.router.add_api_route("/purge", self.purge_logs, methods=["POST"], response_class=HTMLResponse)

    async def list_logs(self, request: Request) -> HTMLResponse:
        """Render log viewer page."""
        api: AdminApiClient = request.app.state.api
        error: str | None = None
        data: dict[str, object] = {"items": [], "total": 0}

        params = self._extract_filters(request)

        try:
            data = await api.list_logs(**params)
        except ApiError as e:
            error = e.detail

        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            "logs.html",
            {
                "request": request,
                "active_page": "logs",
                "logs": data.get("items", []),
                "total": data.get("total", 0),
                "error": error,
                **params,
            },
        )

    async def logs_table_partial(self, request: Request) -> HTMLResponse:
        """HTMX partial — logs table body."""
        api: AdminApiClient = request.app.state.api
        params = self._extract_filters(request)

        try:
            data = await api.list_logs(**params)
        except ApiError:
            data = {"items": [], "total": 0}

        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            "partials/_logs_table.html",
            {
                "request": request,
                "logs": data.get("items", []),
                "total": data.get("total", 0),
                **params,
            },
        )

    async def purge_logs(self, request: Request) -> HTMLResponse:
        """Purge old logs — proxy to admin API."""
        api: AdminApiClient = request.app.state.api

        form = await request.form()
        days_str = str(form.get("days", "30"))

        try:
            days = int(days_str)
            if days < 1:
                raise ValueError("days must be positive")
            result = await api.purge_logs(older_than_days=days)
            return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
                "partials/_alert.html",
                {
                    "request": request,
                    "alert_type": "success",
                    "message": result.get("message", "Logs purged"),
                },
            )
        except ValueError:
            return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
                "partials/_alert.html",
                {
                    "request": request,
                    "alert_type": "danger",
                    "message": "Invalid number of days.",
                },
            )
        except ApiError as e:
            return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
                "partials/_alert.html",
                {"request": request, "alert_type": "danger", "message": e.detail},
            )

    @staticmethod
    def _extract_filters(request: Request) -> dict[str, Any]:
        """Extract filter query params from the request."""
        limit = safe_int(request.query_params.get("limit"), 50)
        offset = safe_int(request.query_params.get("offset"), 0)
        service = request.query_params.get("service", "")
        level = request.query_params.get("level", "")
        user_id_str = request.query_params.get("user_id", "")
        q = request.query_params.get("q", "")

        result: dict[str, Any] = {"limit": limit, "offset": offset}
        if service:
            result["service"] = service
        if level:
            result["level"] = level
        if user_id_str.strip():
            try:
                result["user_id"] = int(user_id_str)
            except ValueError:
                pass
        if q:
            result["q"] = q
        return result


_instance = LogsRouter()
router = _instance.router
