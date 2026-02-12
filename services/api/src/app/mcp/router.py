"""MCP dispatcher — tool catalog and invocation endpoints."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

# Trigger tool registration by importing the tools package
import app.mcp.tools  # noqa: F401
from app.dependencies import db_manager
from app.mcp.registry import registry
from app.mcp.schemas import MCPCallRequest, MCPCallResponse, MCPToolDefinition

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/tools", response_model=list[MCPToolDefinition])
async def list_tools() -> list[MCPToolDefinition]:
    """Return the full MCP tool catalog."""
    return registry.get_catalog()


@router.post("/call", response_model=MCPCallResponse)
async def call_tool(
    request: MCPCallRequest,
    session: Annotated[AsyncSession, Depends(db_manager.dependency)],
) -> MCPCallResponse:
    """Invoke an MCP tool by name. Errors are wrapped in the response body."""
    if not registry.is_registered(request.tool):
        return MCPCallResponse(tool=request.tool, success=False, error=f"Unknown tool: {request.tool}")
    try:
        result = await registry.invoke(request.tool, request.args, session)
        return MCPCallResponse(tool=request.tool, success=True, result=result)
    except Exception as exc:
        logger.exception("MCP tool %s failed", request.tool)
        return MCPCallResponse(tool=request.tool, success=False, error=str(exc))
