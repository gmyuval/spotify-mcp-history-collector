"""MCP tool registry — decorator-based registration and invocation."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.schemas import MCPToolDefinition, MCPToolParam

logger = logging.getLogger(__name__)

ToolHandler = Callable[[dict[str, Any], AsyncSession], Awaitable[Any]]


class MCPToolRegistry:
    """Central registry for all MCP tools.

    Usage::

        registry = MCPToolRegistry()

        @registry.register(
            name="history.top_artists",
            description="Top artists by play count",
            category="history",
            parameters=[MCPToolParam(name="user_id", type="int", ...)],
        )
        async def handle_top_artists(args: dict, session: AsyncSession) -> Any:
            ...
    """

    def __init__(self) -> None:
        self._handlers: dict[str, ToolHandler] = {}
        self._definitions: dict[str, MCPToolDefinition] = {}

    def register(
        self,
        *,
        name: str,
        description: str,
        category: str,
        parameters: list[MCPToolParam],
    ) -> Callable[[ToolHandler], ToolHandler]:
        """Decorator that registers a tool handler."""

        def decorator(fn: ToolHandler) -> ToolHandler:
            self._handlers[name] = fn
            self._definitions[name] = MCPToolDefinition(
                name=name,
                description=description,
                category=category,
                parameters=parameters,
            )
            return fn

        return decorator

    def get_catalog(self) -> list[MCPToolDefinition]:
        """Return all registered tool definitions, sorted by name."""
        return sorted(self._definitions.values(), key=lambda d: d.name)

    async def invoke(self, tool_name: str, args: dict[str, Any], session: AsyncSession) -> Any:
        """Invoke a registered tool handler by name."""
        handler = self._handlers.get(tool_name)
        if handler is None:
            raise KeyError(f"Unknown tool: {tool_name}")
        return await handler(args, session)

    def is_registered(self, tool_name: str) -> bool:
        return tool_name in self._handlers


# Global singleton — tool modules register against this instance at import time.
registry = MCPToolRegistry()
