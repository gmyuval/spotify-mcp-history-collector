"""Import jobs page — list, upload, and status."""

from typing import Any

from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import HTMLResponse

from frontend.api_client import AdminApiClient, ApiError
from frontend.routes._helpers import safe_int

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def list_imports(request: Request) -> HTMLResponse:
    """Render imports list page with upload form."""
    api: AdminApiClient = request.app.state.api
    error: str | None = None
    data: dict[str, object] = {"items": [], "total": 0}
    users: list[object] = []

    params = _extract_filters(request)

    try:
        data = await api.list_import_jobs(**params)
        users_data = await api.list_users(limit=200)
        users = users_data.get("items", [])
    except ApiError as e:
        error = e.detail

    return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
        "imports.html",
        {
            "request": request,
            "active_page": "imports",
            "imports": data.get("items", []),
            "total": data.get("total", 0),
            "users": users,
            "error": error,
            **params,
        },
    )


@router.get("/partials/imports-table", response_class=HTMLResponse)
async def imports_table_partial(request: Request) -> HTMLResponse:
    """HTMX partial — imports table body."""
    api: AdminApiClient = request.app.state.api
    params = _extract_filters(request)

    try:
        data = await api.list_import_jobs(**params)
    except ApiError:
        data = {"items": [], "total": 0}

    return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
        "partials/_imports_table.html",
        {
            "request": request,
            "imports": data.get("items", []),
            "total": data.get("total", 0),
            **params,
        },
    )


@router.post("/upload", response_class=HTMLResponse)
async def upload_import(request: Request) -> HTMLResponse:
    """Handle ZIP file upload — proxy to admin API."""
    api: AdminApiClient = request.app.state.api

    form = await request.form()
    user_id_str = str(form.get("user_id", ""))
    file: UploadFile | None = form.get("file")  # type: ignore[assignment]

    if not user_id_str or not file or not file.filename:
        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            "partials/_alert.html",
            {
                "request": request,
                "alert_type": "danger",
                "message": "User ID and ZIP file are required.",
            },
        )

    try:
        user_id = int(user_id_str)
        content = await file.read()
        result = await api.upload_import(user_id, content, file.filename)
        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            "partials/_alert.html",
            {
                "request": request,
                "alert_type": "success",
                "message": f"Import job #{result.get('id')} created successfully.",
            },
        )
    except ValueError:
        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            "partials/_alert.html",
            {
                "request": request,
                "alert_type": "danger",
                "message": "Invalid user ID.",
            },
        )
    except ApiError as e:
        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            "partials/_alert.html",
            {"request": request, "alert_type": "danger", "message": e.detail},
        )


def _extract_filters(request: Request) -> dict[str, Any]:
    """Extract filter query params from the request."""
    limit = safe_int(request.query_params.get("limit"), 50)
    offset = safe_int(request.query_params.get("offset"), 0)
    user_id_str = request.query_params.get("user_id", "")
    status = request.query_params.get("status", "")

    result: dict[str, Any] = {"limit": limit, "offset": offset}
    if user_id_str.strip():
        try:
            result["user_id"] = int(user_id_str)
        except ValueError:
            pass
    if status:
        result["status"] = status
    return result
