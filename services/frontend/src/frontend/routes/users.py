"""User management pages — list, detail, and actions."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from frontend.api_client import AdminApiClient, ApiError

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def list_users(request: Request) -> HTMLResponse:
    """Render users list page."""
    api: AdminApiClient = request.app.state.api
    error: str | None = None
    data: dict[str, object] = {"items": [], "total": 0, "limit": 50, "offset": 0}

    limit = int(request.query_params.get("limit", "50"))
    offset = int(request.query_params.get("offset", "0"))

    try:
        data = await api.list_users(limit=limit, offset=offset)
    except ApiError as e:
        error = e.detail

    return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
        "users.html",
        {
            "request": request,
            "active_page": "users",
            "users": data.get("items", []),
            "total": data.get("total", 0),
            "limit": limit,
            "offset": offset,
            "error": error,
        },
    )


@router.get("/partials/users-table", response_class=HTMLResponse)
async def users_table_partial(request: Request) -> HTMLResponse:
    """HTMX partial — users table body with pagination."""
    api: AdminApiClient = request.app.state.api
    limit = int(request.query_params.get("limit", "50"))
    offset = int(request.query_params.get("offset", "0"))

    try:
        data = await api.list_users(limit=limit, offset=offset)
    except ApiError:
        data = {"items": [], "total": 0}

    return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
        "partials/_users_table.html",
        {
            "request": request,
            "users": data.get("items", []),
            "total": data.get("total", 0),
            "limit": limit,
            "offset": offset,
        },
    )


@router.get("/{user_id}", response_class=HTMLResponse)
async def user_detail(request: Request, user_id: int) -> HTMLResponse:
    """Render user detail page."""
    api: AdminApiClient = request.app.state.api
    error: str | None = None
    user: dict[str, object] = {}
    recent_jobs: list[object] = []
    recent_imports: list[object] = []

    try:
        user = await api.get_user(user_id)
        jobs_data = await api.list_job_runs(user_id=user_id, limit=10)
        recent_jobs = jobs_data.get("items", [])
        imports_data = await api.list_import_jobs(user_id=user_id, limit=10)
        recent_imports = imports_data.get("items", [])
    except ApiError as e:
        error = e.detail

    return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
        "user_detail.html",
        {
            "request": request,
            "active_page": "users",
            "user": user,
            "recent_jobs": recent_jobs,
            "recent_imports": recent_imports,
            "error": error,
        },
    )


@router.post("/{user_id}/pause", response_class=HTMLResponse)
async def pause_user(request: Request, user_id: int) -> HTMLResponse:
    """Pause sync for a user — returns action result partial."""
    return await _user_action(request, user_id, "pause")


@router.post("/{user_id}/resume", response_class=HTMLResponse)
async def resume_user(request: Request, user_id: int) -> HTMLResponse:
    """Resume sync for a user — returns action result partial."""
    return await _user_action(request, user_id, "resume")


@router.post("/{user_id}/trigger-sync", response_class=HTMLResponse)
async def trigger_sync(request: Request, user_id: int) -> HTMLResponse:
    """Trigger re-sync for a user — returns action result partial."""
    return await _user_action(request, user_id, "trigger_sync")


@router.delete("/{user_id}", response_class=HTMLResponse)
async def delete_user(request: Request, user_id: int) -> HTMLResponse:
    """Delete a user — returns action result partial."""
    api: AdminApiClient = request.app.state.api
    try:
        result = await api.delete_user(user_id)
        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            "partials/_alert.html",
            {
                "request": request,
                "alert_type": "success",
                "message": result.get("message", "User deleted"),
            },
        )
    except ApiError as e:
        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            "partials/_alert.html",
            {"request": request, "alert_type": "danger", "message": e.detail},
        )


async def _user_action(request: Request, user_id: int, action: str) -> HTMLResponse:
    """Execute a user action and return an alert partial."""
    api: AdminApiClient = request.app.state.api
    try:
        method = getattr(api, f"{action}_user" if action != "trigger_sync" else "trigger_sync")
        result = await method(user_id)
        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            "partials/_user_actions.html",
            {
                "request": request,
                "alert_type": "success",
                "message": result.get("message", f"Action '{action}' succeeded"),
                "user_id": user_id,
            },
        )
    except ApiError as e:
        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            "partials/_user_actions.html",
            {
                "request": request,
                "alert_type": "danger",
                "message": e.detail,
                "user_id": user_id,
            },
        )
