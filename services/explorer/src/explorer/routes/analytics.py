"""Analytics page — listening pattern visualizations."""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from explorer.api_client import ApiError, ExplorerApiClient
from explorer.routes._helpers import require_login, safe_int

logger = logging.getLogger(__name__)


class AnalyticsRouter:
    """Analytics page with ECharts visualizations."""

    def __init__(self) -> None:
        self.router = APIRouter()
        self.router.add_api_route("/analytics", self.analytics, methods=["GET"], response_class=HTMLResponse)
        self.router.add_api_route(
            "/analytics/partials/heatmap", self.heatmap_partial, methods=["GET"], response_class=HTMLResponse
        )
        self.router.add_api_route(
            "/analytics/partials/timeline", self.timeline_partial, methods=["GET"], response_class=HTMLResponse
        )

    async def analytics(self, request: Request) -> HTMLResponse:
        """Render the analytics page — charts load via HTMX partials."""
        token = require_login(request)
        if isinstance(token, RedirectResponse):
            return token  # type: ignore[return-value]

        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            request,
            "analytics.html",
            {
                "active_page": "analytics",
                "days": 90,
            },
        )

    async def heatmap_partial(self, request: Request) -> HTMLResponse:
        """HTMX partial — weekday x hour heatmap chart."""
        token = require_login(request)
        if isinstance(token, RedirectResponse):
            return token  # type: ignore[return-value]

        api: ExplorerApiClient = request.app.state.api
        days = safe_int(request.query_params.get("days"), 90)
        data: dict[str, object] = {}

        try:
            data = await api.get_heatmap(token, days=days)
        except ApiError as e:
            if e.status_code == 401:
                return RedirectResponse(url="/login", status_code=303)  # type: ignore[return-value]
            logger.warning("heatmap fetch failed: %s", e.detail)

        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            request,
            "partials/_heatmap_chart.html",
            {"data": data, "days": days},
        )

    async def timeline_partial(self, request: Request) -> HTMLResponse:
        """HTMX partial — plays over time bar chart."""
        token = require_login(request)
        if isinstance(token, RedirectResponse):
            return token  # type: ignore[return-value]

        api: ExplorerApiClient = request.app.state.api
        days = safe_int(request.query_params.get("days"), 90)
        bucket = request.query_params.get("bucket", "week")
        if bucket not in ("day", "week", "month"):
            bucket = "week"
        data: dict[str, object] = {}

        try:
            data = await api.get_timeline(token, days=days, bucket=bucket)
        except ApiError as e:
            if e.status_code == 401:
                return RedirectResponse(url="/login", status_code=303)  # type: ignore[return-value]
            logger.warning("timeline fetch failed: %s", e.detail)

        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            request,
            "partials/_timeline_chart.html",
            {"data": data, "days": days, "bucket": bucket},
        )


_instance = AnalyticsRouter()
router = _instance.router
