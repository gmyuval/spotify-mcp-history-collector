"""Tests for MCP SDK adapter — tool listing and schema building."""

from app.mcp.mcp_server import (
    _build_input_schema,
    _current_user_id,
)
from app.mcp.schemas import MCPToolParam


class TestBuildInputSchema:
    def test_basic_params(self) -> None:
        params = [
            MCPToolParam(name="days", type="int", description="Number of days", required=True),
            MCPToolParam(name="limit", type="int", description="Max results", required=False, default=10),
        ]
        schema = _build_input_schema(params)
        assert schema["type"] == "object"
        assert "days" in schema["properties"]
        assert "limit" in schema["properties"]
        assert schema["required"] == ["days"]
        assert schema["properties"]["limit"]["default"] == 10

    def test_user_id_excluded(self) -> None:
        """user_id should be stripped — it's injected from auth context."""
        params = [
            MCPToolParam(name="user_id", type="int", description="User ID", required=True),
            MCPToolParam(name="days", type="int", description="Days", required=True),
        ]
        schema = _build_input_schema(params)
        assert "user_id" not in schema["properties"]
        assert "days" in schema["properties"]

    def test_type_mapping(self) -> None:
        params = [
            MCPToolParam(name="a", type="str", description="A", required=True),
            MCPToolParam(name="b", type="float", description="B", required=True),
            MCPToolParam(name="c", type="bool", description="C", required=True),
        ]
        schema = _build_input_schema(params)
        assert schema["properties"]["a"]["type"] == "string"
        assert schema["properties"]["b"]["type"] == "number"
        assert schema["properties"]["c"]["type"] == "boolean"

    def test_empty_params(self) -> None:
        schema = _build_input_schema([])
        assert schema == {"type": "object", "properties": {}}

    def test_no_required_when_all_optional(self) -> None:
        params = [
            MCPToolParam(name="days", type="int", description="Days", required=False, default=30),
        ]
        schema = _build_input_schema(params)
        assert "required" not in schema


class TestCurrentUserIdContextVar:
    def test_default_is_none(self) -> None:
        assert _current_user_id.get() is None

    def test_set_and_reset(self) -> None:
        token = _current_user_id.set(42)
        assert _current_user_id.get() == 42
        _current_user_id.reset(token)
        assert _current_user_id.get() is None
