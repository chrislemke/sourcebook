"""Paths for versioned resources in source checkouts and frozen builds."""

from importlib.resources import files
from pathlib import Path


def bundled_resource(name: str, development_path: Path) -> Path:
    """Resolve an installed package resource with a checkout fallback."""
    candidate = Path(str(files("policy_mcp").joinpath("resources", name)))
    return candidate if candidate.is_file() else development_path
