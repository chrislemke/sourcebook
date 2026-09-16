"""Contract tests for the profile-specific MCP servers."""

from pathlib import Path

import pytest
from mcp.types import CallToolResult

from policy_mcp.server import create_server


async def test_legislation_profile_exposes_stable_research_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POLICY_MCP_DATA_DIR", str(tmp_path))
    server = create_server("legislation", principal="local-test")

    assert server.name == "policy-legislation"
    tools = await server.list_tools()
    assert [tool.name for tool in tools] == [
        "legislation_search",
        "legislation_procedure",
        "legislation_records",
        "legislation_read",
        "legislation_changes",
        "legislation_capabilities",
    ]
    for tool in tools:
        assert tool.input_schema["additionalProperties"] is False
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert tool.annotations.idempotent_hint is True

    result = await server.call_tool("legislation_capabilities", {})
    assert isinstance(result, CallToolResult)
    assert result.structured_content is not None
    assert result.structured_content["status"] == "ok"
    assert {item["state"] for item in result.structured_content["sources"]} == {"not_configured"}


async def test_actor_profile_exposes_stable_research_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POLICY_MCP_DATA_DIR", str(tmp_path))
    server = create_server("actors", principal="local-test")

    tools = await server.list_tools()
    assert [tool.name for tool in tools] == [
        "actor_search",
        "actor_get",
        "actor_interests",
        "actor_capabilities",
    ]
    for tool in tools:
        assert tool.input_schema["additionalProperties"] is False
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.idempotent_hint is True

    result = await server.call_tool("actor_capabilities", {})
    assert isinstance(result, CallToolResult)
    assert result.structured_content is not None
    assert result.structured_content["status"] == "ok"
    assert {item["state"] for item in result.structured_content["sources"]} == {"not_configured"}


async def test_evidence_profile_exposes_stable_research_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POLICY_MCP_DATA_DIR", str(tmp_path))
    server = create_server("evidence", principal="local-test")

    tools = await server.list_tools()
    assert [tool.name for tool in tools] == [
        "evidence_search",
        "evidence_describe",
        "evidence_query",
        "evidence_get",
        "evidence_capabilities",
    ]
    for tool in tools:
        assert tool.input_schema["additionalProperties"] is False
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.idempotent_hint is True

    result = await server.call_tool("evidence_capabilities", {})
    assert isinstance(result, CallToolResult)
    assert result.structured_content is not None
    assert result.structured_content["status"] == "ok"
    assert {item["state"] for item in result.structured_content["sources"]} == {
        "not_configured",
        "unsupported",
    }
