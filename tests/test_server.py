"""Contract tests for the profile-specific MCP servers."""

from pathlib import Path

import pytest
from mcp.types import CallToolResult

from policy_mcp.server import create_server


@pytest.mark.parametrize(
    ("profile", "server_name"),
    [
        ("legislation", "policy-legislation"),
        ("actors", "policy-actors"),
        ("evidence", "policy-evidence"),
    ],
)
async def test_profile_exposes_only_its_read_only_diagnostic(
    profile: str,
    server_name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POLICY_MCP_DATA_DIR", str(tmp_path / "shared state"))
    server = create_server(profile)

    assert server.name == server_name
    tools = await server.list_tools()
    assert [tool.name for tool in tools] == ["policy_diagnostic"]
    assert tools[0].input_schema == {
        "properties": {},
        "title": "policy_diagnosticArguments",
        "type": "object",
    }
    assert tools[0].annotations is not None
    assert tools[0].annotations.read_only_hint is True
    assert tools[0].annotations.destructive_hint is False
    assert tools[0].annotations.idempotent_hint is True
    assert tools[0].annotations.open_world_hint is False

    result = await server.call_tool("policy_diagnostic", {})

    assert isinstance(result, CallToolResult)
    assert result.is_error is not True
    assert result.structured_content == {
        "profile": profile,
        "server_name": server_name,
        "transport": "stdio",
        "read_only": True,
        "data_directory": str(tmp_path / "shared state"),
        "database": {
            "journal_mode": "wal",
            "busy_timeout_ms": 5000,
            "readable": True,
            "writable": True,
        },
    }
