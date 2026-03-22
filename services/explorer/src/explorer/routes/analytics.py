"""Analytics page — listening pattern visualizations."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from explorer.routes._helpers import require_login


class AnalyticsRouter:
    """Analytics page with ECharts visualizations."""

    def __init__(self) -> None:
        self.router = APIRouter()
        self.router.add_api_route("/analytics", self.analytics, methods=["GET"], response_class=HTMLResponse)

    async def analytics(self, request: Request) -> HTMLResponse:
        """Render the analytics page with chart placeholders."""
        token = require_login(request)
        if isinstance(token, RedirectResponse):
            return token  # type: ignore[return-value]

        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            "analytics.html",
            {
                "request": request,
                "active_page": "analytics",
                "days": 90,
            },
        )


_instance = AnalyticsRouter()
router = _instance.router
