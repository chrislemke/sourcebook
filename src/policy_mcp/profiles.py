"""Deployment profiles exposed by the policy-mcp executable."""

from __future__ import annotations

from enum import StrEnum


class Profile(StrEnum):
    """One independently connectable policy research domain."""

    LEGISLATION = "legislation"
    ACTORS = "actors"
    EVIDENCE = "evidence"

    @property
    def server_name(self) -> str:
        """Return the stable MCP server name for this profile."""
        return f"policy-{self.value}"
