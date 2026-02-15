"""MCP protocol request/response models."""

from typing import Any

from pydantic import BaseModel, Field, model_validator


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
    """Incoming tool invocation request.

    Accepts both nested and flat arg formats for ChatGPT compatibility:
      {"tool": "...", "args": {"user_id": 1}}   (nested — preferred)
      {"tool": "...", "user_id": 1}              (flat — auto-merged into args)
    """

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def merge_flat_args(cls, data: Any) -> Any:
        """Move top-level extra fields into ``args`` so both formats work."""
        if not isinstance(data, dict):
            return data
        known = {"tool", "args"}
        extra = {k: v for k, v in data.items() if k not in known}
        if extra:
            args = data.get("args") or {}
            # Extra fields are lower priority — explicit args win
            merged = {**extra, **args}
            data = {"tool": data.get("tool"), "args": merged}
        return data


class MCPCallResponse(BaseModel):
    """Tool invocation response (errors are wrapped, not raised)."""

    tool: str
    success: bool
    result: Any = None
    error: str | None = None
