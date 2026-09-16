"""Generate client package trees from one binary and one shared skill."""

from __future__ import annotations

import json
import shutil
import stat
import zipfile
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Final

from policy_mcp import __version__
from policy_mcp.contracts import DIAGNOSTIC_TOOL_DESCRIPTION, DIAGNOSTIC_TOOL_NAME
from policy_mcp.profiles import Profile

PLUGIN_NAME: Final = "policy-research"
DESCRIPTION: Final = "Local, read-only German federal and EU public-source research."
AUTHOR: Final = {"name": "Sourcebook"}
FIXED_ZIP_TIMESTAMP: Final = (2026, 1, 1, 0, 0, 0)
TARGET_PLATFORMS: Final = {
    "darwin-arm64": ("darwin", "policy-mcp"),
    "windows-x64": ("win32", "policy-mcp.exe"),
}


@dataclass(frozen=True)
class PackageBuildReport:
    """Paths produced by a package build."""

    mcp_bundles: dict[str, Path]
    claude_code_plugin: Path
    openai_agent_plugin: Path


def _shared_skill_bytes() -> bytes:
    skill = files("policy_mcp").joinpath("package_templates", "skills", PLUGIN_NAME, "SKILL.md")
    return skill.read_bytes()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2) + "\n").encode()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(value))


def _copy_binary(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    destination.chmod(0o755)


def _copy_skill(plugin_root: Path) -> None:
    destination = plugin_root / "skills" / PLUGIN_NAME / "SKILL.md"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(_shared_skill_bytes())


def _mcp_server(command: str, profile: Profile, *, portable: bool) -> dict[str, object]:
    server: dict[str, object] = {
        "command": command,
        "args": ["serve", "--profile", profile.value],
    }
    if portable:
        server = {"type": "stdio", **server}
    return server


def _mcpb_manifest(profile: Profile, platform: str) -> dict[str, object]:
    description = f"Local, read-only diagnostics for the {profile.value} research profile."
    binary_name = "policy-mcp.exe" if platform == "win32" else "policy-mcp"
    entry_point = f"server/{binary_name}"
    return {
        "manifest_version": "0.3",
        "name": profile.server_name,
        "display_name": f"Sourcebook {profile.value.title()}",
        "version": __version__,
        "description": description,
        "author": AUTHOR,
        "server": {
            "type": "binary",
            "entry_point": entry_point,
            "mcp_config": {
                "command": f"${{__dirname}}/{entry_point}",
                "args": ["serve", "--profile", profile.value],
                "env": {},
            },
        },
        "tools": [
            {
                "name": DIAGNOSTIC_TOOL_NAME,
                "description": DIAGNOSTIC_TOOL_DESCRIPTION,
            }
        ],
        "compatibility": {"platforms": [platform]},
    }


def _zip_entry(name: str, content: bytes, mode: int) -> tuple[zipfile.ZipInfo, bytes]:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | mode) << 16
    return info, content


def _build_mcpb(
    binary: Path,
    output: Path,
    profile: Profile,
    target: str,
    platform: str,
) -> Path:
    bundle = output / f"{profile.server_name}-{__version__}-{target}.mcpb"
    bundle.parent.mkdir(parents=True, exist_ok=True)
    manifest = _json_bytes(_mcpb_manifest(profile, platform))
    binary_name = "server/policy-mcp.exe" if platform == "win32" else "server/policy-mcp"
    entries = [
        _zip_entry("manifest.json", manifest, 0o644),
        _zip_entry(binary_name, binary.read_bytes(), 0o755),
    ]
    with zipfile.ZipFile(bundle, "w") as archive:
        for info, content in entries:
            archive.writestr(info, content)
    return bundle


def _build_claude_code_plugin(binary: Path, output: Path, binary_name: str) -> Path:
    plugin = output / "claude-code-plugin" / PLUGIN_NAME
    _write_json(
        plugin / ".claude-plugin" / "plugin.json",
        {
            "name": PLUGIN_NAME,
            "version": __version__,
            "description": DESCRIPTION,
            "author": AUTHOR,
        },
    )
    command = f"${{CLAUDE_PLUGIN_ROOT}}/bin/{binary_name}"
    _write_json(
        plugin / ".mcp.json",
        {profile.server_name: _mcp_server(command, profile, portable=False) for profile in Profile},
    )
    _copy_binary(binary, plugin / "bin" / binary_name)
    _copy_skill(plugin)
    return plugin


def _build_openai_plugin(binary: Path, output: Path, binary_name: str) -> Path:
    plugin = output / "openai-agent-plugin" / PLUGIN_NAME
    _write_json(
        plugin / "plugin.json",
        {
            "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
            "name": PLUGIN_NAME,
            "version": __version__,
            "description": DESCRIPTION,
            "extensions": {
                "com.openai": {
                    "interface": {
                        "displayName": "Sourcebook",
                        "shortDescription": DESCRIPTION,
                        "developerName": "Sourcebook",
                        "category": "Productivity",
                        "capabilities": ["Read"],
                    }
                }
            },
        },
    )
    command = f"./bin/{binary_name}"
    _write_json(
        plugin / "mcp.json",
        {
            "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
            "mcpServers": {
                profile.server_name: _mcp_server(command, profile, portable=True)
                for profile in Profile
            },
        },
    )
    _copy_binary(binary, plugin / "bin" / binary_name)
    _copy_skill(plugin)
    return plugin


def _copy_tree(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, dirs_exist_ok=True)


def _build_marketplaces(output: Path, claude_plugin: Path, openai_plugin: Path) -> None:
    claude_root = output / "marketplaces" / "claude"
    _write_json(
        claude_root / ".claude-plugin" / "marketplace.json",
        {
            "name": "policy-tools",
            "owner": AUTHOR,
            "description": "Sourcebook client packages for local political research.",
            "plugins": [
                {
                    "name": PLUGIN_NAME,
                    "description": DESCRIPTION,
                    "source": f"./plugins/{PLUGIN_NAME}",
                }
            ],
        },
    )
    _copy_tree(claude_plugin, claude_root / "plugins" / PLUGIN_NAME)

    openai_marketplace = output / "marketplaces" / "openai"
    openai_root = openai_marketplace / ".agents" / "plugins"
    _write_json(
        openai_root / "marketplace.json",
        {
            "name": "policy-tools",
            "interface": {"displayName": "Policy tools"},
            "plugins": [
                {
                    "name": PLUGIN_NAME,
                    "source": {"source": "local", "path": f"./plugins/{PLUGIN_NAME}"},
                    "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                    "category": "Productivity",
                }
            ],
        },
    )
    _copy_tree(openai_plugin, openai_marketplace / "plugins" / PLUGIN_NAME)


def build_packages(binary: Path, output: Path, *, target: str) -> PackageBuildReport:
    """Build every package family for one native self-contained executable."""
    if target not in TARGET_PLATFORMS:
        supported = ", ".join(sorted(TARGET_PLATFORMS))
        raise ValueError(f"Unsupported target {target!r}; expected one of: {supported}")
    if not binary.is_file():
        raise FileNotFoundError(binary)
    platform, binary_name = TARGET_PLATFORMS[target]
    output.mkdir(parents=True, exist_ok=True)

    bundles = {
        profile.value: _build_mcpb(
            binary,
            output / "claude-desktop",
            profile,
            target,
            platform,
        )
        for profile in Profile
    }
    claude_plugin = _build_claude_code_plugin(binary, output, binary_name)
    openai_plugin = _build_openai_plugin(binary, output, binary_name)
    _build_marketplaces(output, claude_plugin, openai_plugin)
    return PackageBuildReport(
        mcp_bundles=bundles,
        claude_code_plugin=claude_plugin,
        openai_agent_plugin=openai_plugin,
    )
