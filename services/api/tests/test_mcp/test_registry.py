"""Tests for MCPToolRegistry."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.registry import MCPToolRegistry
from app.mcp.schemas import MCPToolParam


@pytest.fixture
def fresh_registry() -> MCPToolRegistry:
    return MCPToolRegistry()


def test_register_and_catalog(fresh_registry: MCPToolRegistry) -> None:
    @fresh_registry.register(
        name="test.echo",
        description="Echoes args",
        category="test",
        parameters=[MCPToolParam(name="msg", type="str", description="Message")],
    )
    async def echo(args: dict, session: AsyncSession) -> str:
        return args["msg"]

    catalog = fresh_registry.get_catalog()
    assert len(catalog) == 1
    assert catalog[0].name == "test.echo"
    assert catalog[0].category == "test"


def test_is_registered(fresh_registry: MCPToolRegistry) -> None:
    @fresh_registry.register(
        name="test.ping",
        description="Ping",
        category="test",
        parameters=[],
    )
    async def ping(args: dict, session: AsyncSession) -> str:
        return "pong"

    assert fresh_registry.is_registered("test.ping")
    assert not fresh_registry.is_registered("test.missing")


async def test_invoke_success(fresh_registry: MCPToolRegistry) -> None:
    @fresh_registry.register(
        name="test.add",
        description="Add two numbers",
        category="test",
        parameters=[],
    )
    async def add(args: dict, session: AsyncSession) -> int:
        return args["a"] + args["b"]

    # Pass None as session since handler doesn't use it
    result = await fresh_registry.invoke("test.add", {"a": 2, "b": 3}, None)  # type: ignore[arg-type]
    assert result == 5


async def test_invoke_unknown_tool(fresh_registry: MCPToolRegistry) -> None:
    with pytest.raises(KeyError, match="Unknown tool"):
        await fresh_registry.invoke("nonexistent", {}, None)  # type: ignore[arg-type]


def test_catalog_sorted(fresh_registry: MCPToolRegistry) -> None:
    for name in ["c.tool", "a.tool", "b.tool"]:

        @fresh_registry.register(name=name, description=name, category="test", parameters=[])
        async def handler(args: dict, session: AsyncSession) -> None:
            pass

    names = [t.name for t in fresh_registry.get_catalog()]
    assert names == ["a.tool", "b.tool", "c.tool"]
