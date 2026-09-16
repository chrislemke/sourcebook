"""Shared MCP contract metadata used by runtime and package manifests."""

from typing import Final

DIAGNOSTIC_TOOL_NAME: Final = "policy_diagnostic"
DIAGNOSTIC_TOOL_TITLE: Final = "Policy MCP diagnostic"
DIAGNOSTIC_TOOL_DESCRIPTION: Final = (
    "Check this local profile and its shared data store without reading records or contacting "
    "an upstream source."
)
