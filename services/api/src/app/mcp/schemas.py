"""MCP protocol request/response models."""

from typing import Any

from pydantic import BaseModel, Field


class MCPToolParam(BaseModel):
    """Parameter definition for an MCP tool."""

    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None


class MCPToolDefinition(BaseModel):
    """Tool catalog entry returned by GET /mcp/tools."""

    name: str
    description: str
    category: str
    parameters: list[MCPToolParam]


class MCPCallRequest(BaseModel):
    """Incoming tool invocation request."""

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


class MCPCallResponse(BaseModel):
    """Tool invocation response (errors are wrapped, not raised)."""

    tool: str
    success: bool
    result: Any = None
    error: str | None = None
