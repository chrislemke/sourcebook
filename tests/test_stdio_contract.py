"""MCP contract tests through the same stdio boundary used by client hosts."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters, stdio_client


async def read_contract(
    profile: str, data_directory: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
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
        result = await session.call_tool("policy_diagnostic", {})
    return (
        tools.tools[0].model_dump(by_alias=True, exclude_none=True),
        result.model_dump(by_alias=True, exclude_none=True),
    )


async def test_two_clients_share_the_same_store_over_stdio(tmp_path: Path) -> None:
    data_directory = tmp_path / "shared user data"

    legislation, actors = await asyncio.gather(
        read_contract("legislation", data_directory),
        read_contract("actors", data_directory),
    )

    legislation_tool, legislation_result = legislation
    actors_tool, actors_result = actors
    assert legislation_tool == actors_tool
    assert legislation_result["structuredContent"]["profile"] == "legislation"
    assert actors_result["structuredContent"]["profile"] == "actors"
    assert legislation_result["structuredContent"]["data_directory"] == str(data_directory)
    assert actors_result["structuredContent"]["database"]["journal_mode"] == "wal"
    assert os.path.isfile(data_directory / "sourcebook.sqlite3")
