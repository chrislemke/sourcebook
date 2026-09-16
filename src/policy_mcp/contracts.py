"""Shared MCP contract metadata used by runtime and package manifests."""

from typing import Final

from policy_mcp.profiles import Profile

TOOL_DESCRIPTIONS: Final[dict[str, str]] = {
    "legislation_search": (
        "Search bounded German procedure metadata or resolve an official identifier."
    ),
    "legislation_procedure": (
        "Inspect one selected procedure, its dated events, and linked documents."
    ),
    "legislation_records": (
        "Find supported parliamentary records without inventing provider filters."
    ),
    "legislation_read": "Read an outline or bounded whole passages from a selected document.",
    "legislation_changes": "List observed source changes when a route supports change history.",
    "legislation_capabilities": (
        "Report filtered source readiness, coverage, freshness, and limitations."
    ),
    "actor_search": (
        "Find public officeholders, institutional bodies, or disclosed interest representatives "
        "without assessing influence or alignment."
    ),
    "actor_get": "Get one actor's requested published view with dates and evidence.",
    "actor_interests": (
        "Find disclosed interests or regulatory projects while distinguishing explicit links "
        "from candidate text matches."
    ),
    "actor_capabilities": "Report actor source readiness, freshness, coverage, and limitations.",
    "evidence_search": "Search bounded metadata cards across configured evidence sources.",
    "evidence_describe": "Describe a selected dataset and its permitted dimensions and members.",
    "evidence_query": "Query a typed bounded dataset slice or validate a budget aggregation.",
    "evidence_get": "Retrieve one selected evidence record without embedding search results.",
    "evidence_capabilities": (
        "Report enabled evidence routes and disabled collection limits honestly."
    ),
}

PROFILE_TOOL_NAMES: Final[dict[Profile, tuple[str, ...]]] = {
    Profile.LEGISLATION: (
        "legislation_search",
        "legislation_procedure",
        "legislation_records",
        "legislation_read",
        "legislation_changes",
        "legislation_capabilities",
    ),
    Profile.ACTORS: ("actor_search", "actor_get", "actor_interests", "actor_capabilities"),
    Profile.EVIDENCE: (
        "evidence_search",
        "evidence_describe",
        "evidence_query",
        "evidence_get",
        "evidence_capabilities",
    ),
}


def tool_description(name: str) -> str:
    """Return the shared runtime and package description for one stable tool."""
    return TOOL_DESCRIPTIONS[name]
