"""Profile-specific MCP server construction."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from policy_mcp import __version__
from policy_mcp.actors import FrozenActorCatalog, LiveActorCatalog, register_actor_tools
from policy_mcp.adapters.govdata import LiveGovDataService
from policy_mcp.evidence import FrozenEvidenceCatalog, register_evidence_tools
from policy_mcp.legislation import FrozenLegislationCatalog, register_legislation_tools
from policy_mcp.profiles import Profile
from policy_mcp.references import SQLiteReferenceStore
from policy_mcp.storage import open_database


def create_server(
    profile: Profile | str,
    *,
    principal: str = "local-installation",
    legislation_catalog: FrozenLegislationCatalog | None = None,
    actor_catalog: FrozenActorCatalog | None = None,
) -> MCPServer[None]:
    """Build the server for one deployment profile."""
    selected = Profile(profile)
    open_database().close()
    server: MCPServer[None] = MCPServer(
        name=selected.server_name,
        title=f"Sourcebook {selected.value}",
        description="Local, read-only German federal and EU political research.",
        version=__version__,
    )

    if selected == Profile.LEGISLATION:
        register_legislation_tools(
            server,
            legislation_catalog or FrozenLegislationCatalog.from_database(),
            SQLiteReferenceStore(principal=principal),
        )
        return server
    if selected == Profile.ACTORS:
        register_actor_tools(
            server,
            actor_catalog or LiveActorCatalog(),
            SQLiteReferenceStore(principal=principal),
        )
        return server
    if selected == Profile.EVIDENCE:
        register_evidence_tools(
            server,
            FrozenEvidenceCatalog.empty(),
            SQLiteReferenceStore(principal=principal),
            govdata_service=LiveGovDataService(),
        )
        return server

    raise AssertionError(f"Unhandled profile: {selected}")
