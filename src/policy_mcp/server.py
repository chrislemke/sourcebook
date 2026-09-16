"""Profile-specific MCP server construction."""

from __future__ import annotations

from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict

from policy_mcp import __version__
from policy_mcp.profiles import Profile
from policy_mcp.storage import data_directory, database_health


class DatabaseDiagnostic(BaseModel):
    """Non-sensitive SQLite status returned through MCP."""

    model_config = ConfigDict(extra="forbid")

    journal_mode: Literal["wal"]
    busy_timeout_ms: int
    readable: bool
    writable: bool


class PolicyDiagnostic(BaseModel):
    """Stable diagnostic response shared by every package family."""

    model_config = ConfigDict(extra="forbid")

    profile: Profile
    server_name: str
    transport: Literal["stdio"] = "stdio"
    read_only: Literal[True] = True
    data_directory: str
    database: DatabaseDiagnostic


def create_server(profile: Profile | str) -> MCPServer[None]:
    """Build the server for one deployment profile."""
    selected = Profile(profile)
    server: MCPServer[None] = MCPServer(
        name=selected.server_name,
        title=f"Sourcebook {selected.value}",
        description="Local, read-only political research diagnostics.",
        version=__version__,
    )

    @server.tool(
        name="policy_diagnostic",
        title="Policy MCP diagnostic",
        description=(
            "Check this local profile and its shared data store without reading records or "
            "contacting an upstream source."
        ),
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def policy_diagnostic() -> PolicyDiagnostic:
        health = database_health()
        return PolicyDiagnostic(
            profile=selected,
            server_name=selected.server_name,
            data_directory=str(data_directory()),
            database=DatabaseDiagnostic(
                journal_mode="wal",
                busy_timeout_ms=health.busy_timeout_ms,
                readable=health.readable,
                writable=health.writable,
            ),
        )

    return server
