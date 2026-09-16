"""MCP contract tests through the same stdio boundary used by client hosts."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters, stdio_client, types

CAPABILITY_TOOLS = {
    "legislation": "legislation_capabilities",
    "actors": "actor_capabilities",
    "evidence": "evidence_capabilities",
}


async def read_contract(profile: str, data_directory: Path) -> tuple[list[str], dict[str, Any]]:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "policy_mcp", "serve", "--profile", profile],
        env={"POLICY_MCP_DATA_DIR": str(data_directory)},
    )
    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        result = await session.call_tool(CAPABILITY_TOOLS[profile], {})
    return (
        [tool.name for tool in tools.tools],
        result.model_dump(by_alias=True, exclude_none=True),
    )


async def test_two_clients_share_the_same_store_over_stdio(tmp_path: Path) -> None:
    data_directory = tmp_path / "shared user data"

    legislation, actors = await asyncio.gather(
        read_contract("legislation", data_directory),
        read_contract("actors", data_directory),
    )

    legislation_tools, legislation_result = legislation
    actor_tools, actors_result = actors
    assert legislation_tools == [
        "legislation_search",
        "legislation_procedure",
        "legislation_records",
        "legislation_read",
        "legislation_changes",
        "legislation_capabilities",
    ]
    assert actor_tools == ["actor_search", "actor_get", "actor_interests", "actor_capabilities"]
    assert legislation_result["structuredContent"]["status"] == "ok"
    assert actors_result["structuredContent"]["status"] == "ok"
    assert os.path.isfile(data_directory / "sourcebook.sqlite3")


async def test_server_negotiates_required_legacy_protocol(tmp_path: Path) -> None:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "policy_mcp", "serve", "--profile", "legislation"],
        env={"POLICY_MCP_DATA_DIR": str(tmp_path / "legacy")},
    )
    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        result = await session.send_request(
            types.InitializeRequest(
                params=types.InitializeRequestParams(
                    protocol_version="2024-11-05",
                    capabilities=types.ClientCapabilities(),
                    client_info=types.Implementation(name="sourcebook-tests", version="1"),
                )
            ),
            types.InitializeResult,
        )
        session.adopt(result)
        await session.send_notification(types.InitializedNotification())
        tools = await session.list_tools()

    assert result.protocol_version == "2024-11-05"
    assert [tool.name for tool in tools.tools] == [
        "legislation_search",
        "legislation_procedure",
        "legislation_records",
        "legislation_read",
        "legislation_changes",
        "legislation_capabilities",
    ]
