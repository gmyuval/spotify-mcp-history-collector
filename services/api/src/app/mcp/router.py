"""MCP dispatcher — class-based router for tool catalog and invocation."""

import logging
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
        except Exception as exc:
            logger.exception("MCP tool %s failed", request.tool)
            error_type = type(exc).__name__
            error_detail = str(exc) if str(exc) else "tool execution failed"
            return MCPCallResponse(tool=request.tool, success=False, error=f"{error_type}: {error_detail}")


_instance = MCPRouter()
router = _instance.router
