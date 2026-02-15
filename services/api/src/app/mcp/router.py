"""MCP dispatcher — class-based router for tool catalog and invocation."""

import logging
import re
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

# Trigger tool registration by importing the tools package
import app.mcp.tools  # noqa: F401
from app.admin.auth import require_admin
from app.dependencies import db_manager
from app.mcp.registry import registry
from app.mcp.schemas import MCPCallRequest, MCPCallResponse, MCPToolDefinition

logger = logging.getLogger(__name__)

_SENSITIVE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"Bearer\s+[A-Za-z0-9._-]+"), "Bearer [redacted]"),
    (re.compile(r"(?i)refresh_token=\S+"), "refresh_token=[redacted]"),
    (re.compile(r"(?i)access_token=\S+"), "access_token=[redacted]"),
    (re.compile(r'(?i)"refresh_token"\s*:\s*"[^"]*"'), '"refresh_token": "[redacted]"'),
    (re.compile(r'(?i)"access_token"\s*:\s*"[^"]*"'), '"access_token": "[redacted]"'),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[redacted email]"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[redacted ip]"),
    (re.compile(r"(?i)([0-9a-f]{1,4}:){7}[0-9a-f]{1,4}"), "[redacted ipv6]"),
]


def _redact_sensitive(message: str) -> str:
    """Strip tokens, emails, and IPs from error messages before returning to clients."""
    for pattern, replacement in _SENSITIVE_PATTERNS:
        message = pattern.sub(replacement, message)
    return message


class MCPRouter:
    """Class-based router for MCP tool catalog and invocation."""

    def __init__(self) -> None:
        self.router = APIRouter()
        self.router.add_api_route(
            "/tools",
            self.list_tools,
            methods=["GET"],
            response_model=list[MCPToolDefinition],
            dependencies=[Depends(require_admin)],
        )
        self.router.add_api_route(
            "/call",
            self.call_tool,
            methods=["POST"],
            response_model=MCPCallResponse,
            dependencies=[Depends(require_admin)],
        )

    async def list_tools(self) -> list[MCPToolDefinition]:
        """Return the full MCP tool catalog."""
        return registry.get_catalog()

    async def call_tool(
        self,
        request: MCPCallRequest,
        session: Annotated[AsyncSession, Depends(db_manager.dependency)],
    ) -> MCPCallResponse:
        """Invoke an MCP tool by name. Errors are wrapped in the response body."""
        logger.info("MCP call: tool=%s arguments=%s", request.tool, request.arguments)
        if not registry.is_registered(request.tool):
            return MCPCallResponse(tool=request.tool, success=False, error=f"Unknown tool: {request.tool}")
        try:
            result = await registry.invoke(request.tool, request.arguments, session)
            return MCPCallResponse(tool=request.tool, success=True, result=result)
        except ValueError as exc:
            logger.warning("MCP tool %s validation error: %s", request.tool, exc)
            return MCPCallResponse(tool=request.tool, success=False, error=_redact_sensitive(str(exc)))
        except Exception as exc:
            logger.exception("MCP tool %s failed", request.tool)
            error_type = type(exc).__name__
            safe_message = _redact_sensitive(str(exc))
            return MCPCallResponse(
                tool=request.tool,
                success=False,
                error=f"{error_type}: {safe_message}",
            )


_instance = MCPRouter()
router = _instance.router
