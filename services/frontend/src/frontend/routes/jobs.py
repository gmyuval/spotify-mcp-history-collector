"""Job runs page — filterable, paginated job history."""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from frontend.api_client import AdminApiClient, ApiError

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def list_jobs(request: Request) -> HTMLResponse:
    """Render job runs list page."""
    api: AdminApiClient = request.app.state.api
    error: str | None = None
    data: dict[str, object] = {"items": [], "total": 0}

    params = _extract_filters(request)

    try:
        data = await api.list_job_runs(**params)
    except ApiError as e:
        error = e.detail

    return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
        "jobs.html",
        {
            "request": request,
            "active_page": "jobs",
            "jobs": data.get("items", []),
            "total": data.get("total", 0),
            "error": error,
            **params,
        },
    )


@router.get("/partials/jobs-table", response_class=HTMLResponse)
async def jobs_table_partial(request: Request) -> HTMLResponse:
    """HTMX partial — jobs table body."""
    api: AdminApiClient = request.app.state.api
    params = _extract_filters(request)

    try:
        data = await api.list_job_runs(**params)
    except ApiError:
        data = {"items": [], "total": 0}

    return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
        "partials/_jobs_table.html",
        {
            "request": request,
            "jobs": data.get("items", []),
            "total": data.get("total", 0),
            **params,
        },
    )


def _extract_filters(request: Request) -> dict[str, Any]:
    """Extract filter query params from the request."""
    limit = int(request.query_params.get("limit", "50"))
    offset = int(request.query_params.get("offset", "0"))
    user_id_str = request.query_params.get("user_id", "")
    job_type = request.query_params.get("job_type", "")
    status = request.query_params.get("status", "")

    result: dict[str, Any] = {"limit": limit, "offset": offset}
    if user_id_str.strip():
        try:
            result["user_id"] = int(user_id_str)
        except ValueError:
            pass
    if job_type:
        result["job_type"] = job_type
    if status:
        result["status"] = status
    return result
