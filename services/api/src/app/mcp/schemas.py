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


# ChatGPT schema uses "search_type" to avoid conflict with JSON Schema "type"
_FIELD_ALIASES: dict[str, str] = {"search_type": "type"}


class MCPCallRequest(BaseModel):
    """Incoming tool invocation request.

    Accepts multiple arg formats for ChatGPT compatibility:
      {"tool": "...", "arguments": {"user_id": 1}}  (preferred)
      {"tool": "...", "args": {"user_id": 1}}        (legacy alias)
      {"tool": "...", "user_id": 1}                   (flat — auto-merged)
    """

    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalise_args(cls, data: Any) -> Any:
        """Accept ``args``, ``arguments``, or flat top-level params."""
        if not isinstance(data, dict):
            return data
        known = {"tool", "args", "arguments"}
        extra = {k: v for k, v in data.items() if k not in known}
        # Accept both "arguments" and legacy "args"
        base = data.get("arguments") or data.get("args") or {}
        if extra:
            # Flat fields are lower priority — explicit args win
            base = {**extra, **base}
        # Apply field aliases (e.g. search_type → type)
        for alias, real in _FIELD_ALIASES.items():
            if alias in base and real not in base:
                base[real] = base.pop(alias)
        return {"tool": data.get("tool"), "arguments": base}


class MCPCallResponse(BaseModel):
    """Tool invocation response (errors are wrapped, not raised)."""

    tool: str
    success: bool
    result: Any = None
    error: str | None = None
