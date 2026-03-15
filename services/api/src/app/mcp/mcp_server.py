"""MCP SDK adapter — bridges MCPToolRegistry to the official mcp Python SDK."""

import json
import logging
from contextvars import ContextVar
from typing import Any
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import TextContent, Tool
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.mcp.registry import registry
from app.mcp.router import _redact_sensitive
from app.mcp.schemas import MCPToolParam

logger = logging.getLogger(__name__)

# Context var to pass user_id from ASGI middleware into MCP handlers
_current_user_id: ContextVar[int | None] = ContextVar("_current_user_id", default=None)


def _param_to_json_schema(param: MCPToolParam) -> dict[str, Any]:
    """Convert an MCPToolParam to a JSON Schema property definition."""
    type_map: dict[str, str] = {
        "int": "integer",
        "integer": "integer",
        "float": "number",
        "number": "number",
        "bool": "boolean",
        "boolean": "boolean",
        "str": "string",
        "string": "string",
        "array": "array",
        "list": "array",
        "object": "object",
        "dict": "object",
    }
    json_type = type_map.get(param.type)
    if json_type is None:
        logger.warning("Unmapped parameter type %r for param %r, falling back to 'string'", param.type, param.name)
        json_type = "string"
    schema: dict[str, Any] = {
        "type": json_type,
        "description": param.description,
    }
    if param.default is not None:
        schema["default"] = param.default
    return schema


def _build_input_schema(params: list[MCPToolParam]) -> dict[str, Any]:
    """Build a JSON Schema object from tool parameters."""
    properties: dict[str, Any] = {}
    required: list[str] = []
    for p in params:
        if p.name == "user_id":
            continue  # user_id is injected from auth context, not exposed to clients
        properties[p.name] = _param_to_json_schema(p)
        if p.required:
            required.append(p.name)
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _build_transport_security() -> TransportSecuritySettings:
    """Build transport security settings from CORS_ALLOWED_ORIGINS.

    The MCP SDK validates Host and Origin headers to prevent DNS rebinding.
    We derive allowed hosts/origins from the same CORS config used by FastAPI,
    plus the default localhost entries for local development.
    """
    from app.settings import get_settings

    settings = get_settings()
    cors_origins = [o.strip() for o in settings.CORS_ALLOWED_ORIGINS.split(",") if o.strip()]

    # Defaults: localhost variants (always allowed for dev)
    allowed_hosts: list[str] = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    allowed_origins: list[str] = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]

    for origin in cors_origins:
        if origin == "*":
            continue
        parsed = urlparse(origin)
        host = parsed.hostname or ""
        if not host:
            continue
        port = parsed.port
        if port:
            host_pattern = f"{host}:{port}"
        else:
            # No port: add both bare hostname (for proxied requests) and wildcard
            host_pattern = host
        if host_pattern not in allowed_hosts:
            allowed_hosts.append(host_pattern)
        if not port and f"{host}:*" not in allowed_hosts:
            allowed_hosts.append(f"{host}:*")
        if origin not in allowed_origins:
            allowed_origins.append(origin)

    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )


def create_mcp_server() -> FastMCP:
    """Create the MCP SDK FastMCP server with registry-backed handlers."""
    mcp = FastMCP(
        "spotify-mcp",
        stateless_http=True,
        json_response=True,
        transport_security=_build_transport_security(),
    )
    # Override the default streamable HTTP path so it serves at "/" when mounted
    mcp.settings.streamable_http_path = "/"

    # We use the low-level Server API (mcp._mcp_server) instead of the public
    # @mcp.tool() decorator because our tools are registered in a custom
    # MCPToolRegistry singleton — we need to inject user_id from auth context
    # and redact sensitive errors, which the high-level API doesn't support.
    # This couples us to FastMCP internals; treat SDK upgrades with care.
    @mcp._mcp_server.list_tools()  # type: ignore[no-untyped-call,untyped-decorator]
    async def handle_list_tools() -> list[Tool]:
        """Return all registered tools in MCP format."""
        catalog = registry.get_catalog()
        return [
            Tool(
                name=defn.name,
                description=defn.description,
                inputSchema=_build_input_schema(defn.parameters),
            )
            for defn in catalog
        ]

    @mcp._mcp_server.call_tool()  # type: ignore[untyped-decorator]
    async def handle_call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        """Dispatch a tool call to the registry, injecting user_id from auth context."""
        from app.dependencies import db_manager

        user_id = _current_user_id.get()
        if user_id is None:
            return [TextContent(type="text", text=json.dumps({"success": False, "error": "Authentication required"}))]

        args: dict[str, Any] = dict(arguments) if arguments else {}
        args["user_id"] = user_id

        try:
            async with db_manager.session() as session:
                result = await registry.invoke(name, args, session)
        except KeyError:
            return [TextContent(type="text", text=json.dumps({"success": False, "error": f"Unknown tool: {name}"}))]
        except ValueError as exc:
            return [TextContent(type="text", text=json.dumps({"success": False, "error": _redact_sensitive(str(exc))}))]
        except Exception:
            logger.exception("Tool %s failed", name)
            return [TextContent(type="text", text=json.dumps({"success": False, "error": "Internal server error"}))]

        # Wrap result as JSON text content
        if isinstance(result, str):
            text = result
        else:
            text = json.dumps(result, default=str)

        return [TextContent(type="text", text=text)]

    return mcp


class AuthContextMiddleware:
    """ASGI middleware that extracts user_id from request.state and sets the context var.

    This bridges FastAPI's JWTAuthMiddleware (which sets request.state.user_id)
    to the MCP SDK handlers (which read from _current_user_id context var).
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            request = Request(scope)
            user_id: int | None = getattr(request.state, "user_id", None)
            token = _current_user_id.set(user_id)
            try:
                await self._app(scope, receive, send)
            finally:
                _current_user_id.reset(token)
        else:
            await self._app(scope, receive, send)


def create_mcp_asgi_app(mcp: FastMCP) -> ASGIApp:
    """Create the ASGI app for the MCP server, wrapped with auth context middleware."""
    mcp_app: Starlette = mcp.streamable_http_app()
    return AuthContextMiddleware(mcp_app)
