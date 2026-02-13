"""Logs page — searchable log viewer with filtering and purge."""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from frontend.api_client import AdminApiClient, ApiError

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def list_logs(request: Request) -> HTMLResponse:
    """Render log viewer page."""
    api: AdminApiClient = request.app.state.api
    error: str | None = None
    data: dict[str, object] = {"items": [], "total": 0}

    params = _extract_filters(request)

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


@router.get("/partials/logs-table", response_class=HTMLResponse)
async def logs_table_partial(request: Request) -> HTMLResponse:
    """HTMX partial — logs table body."""
    api: AdminApiClient = request.app.state.api
    params = _extract_filters(request)

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


@router.post("/purge", response_class=HTMLResponse)
async def purge_logs(request: Request) -> HTMLResponse:
    """Purge old logs — proxy to admin API."""
    api: AdminApiClient = request.app.state.api

    form = await request.form()
    days_str = str(form.get("days", "30"))

    try:
        days = int(days_str)
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


def _extract_filters(request: Request) -> dict[str, Any]:
    """Extract filter query params from the request."""
    limit = int(request.query_params.get("limit", "50"))
    offset = int(request.query_params.get("offset", "0"))
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
