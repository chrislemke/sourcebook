"""Tests for reproducible client package generation."""

from __future__ import annotations

import json
import stat
import zipfile
from pathlib import Path
from typing import Any

import pytest

from policy_mcp.contracts import PROFILE_TOOL_NAMES, tool_description
from policy_mcp.packaging import build_packages
from policy_mcp.profiles import Profile


def make_binary(path: Path) -> None:
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def test_builds_all_package_families_from_one_binary_and_skill(tmp_path: Path) -> None:
    binary = tmp_path / "build path with spaces" / "policy-mcp"
    binary.parent.mkdir()
    make_binary(binary)
    output = tmp_path / "packages"

    report = build_packages(binary, output, target="darwin-arm64")

    assert len(report.mcp_bundles) == 3
    assert (output / "bin" / "policy-mcp").read_bytes() == binary.read_bytes()
    assert (output / "bin" / "policy-mcp").stat().st_mode & stat.S_IXUSR
    for profile, bundle in report.mcp_bundles.items():
        assert bundle.name == f"policy-{profile}-0.1.0-darwin-arm64.mcpb"
        with zipfile.ZipFile(bundle) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            assert manifest["manifest_version"] == "0.3"
            assert manifest["name"] == f"policy-{profile}"
            assert manifest["compatibility"]["platforms"] == ["darwin"]
            assert manifest["server"]["type"] == "binary"
            asks_for_dip_key = profile == "legislation"
            assert manifest["server"]["mcp_config"] == {
                "command": "${__dirname}/server/policy-mcp",
                "args": ["serve", "--profile", profile],
                "env": ({"DIP_API_KEY": "${user_config.dip_api_key}"} if asks_for_dip_key else {}),
            }
            if asks_for_dip_key:
                option = manifest["user_config"]["dip_api_key"]
                assert option["type"] == "string"
                assert option["sensitive"] is True
                assert option["required"] is False
            else:
                assert "user_config" not in manifest
            binary_info = archive.getinfo("server/policy-mcp")
            assert binary_info.external_attr >> 16 & stat.S_IXUSR

    claude_plugin = output / "claude-code-plugin" / "policy-research"
    claude_manifest = load_json(claude_plugin / ".claude-plugin" / "plugin.json")
    assert claude_manifest["repository"] == "https://github.com/chrislemke/sourcebook"
    assert claude_manifest["userConfig"]["dip_api_key"]["sensitive"] is True
    assert claude_manifest["userConfig"]["dip_api_key"]["required"] is False
    claude_mcp = load_json(claude_plugin / ".mcp.json")["mcpServers"]
    assert list(claude_mcp) == ["policy-legislation", "policy-actors", "policy-evidence"]
    assert claude_mcp["policy-legislation"] == {
        "command": "${CLAUDE_PLUGIN_ROOT}/bin/policy-mcp",
        "args": ["serve", "--profile", "legislation"],
        "env": {"DIP_API_KEY": "${user_config.dip_api_key}"},
    }
    assert "env" not in claude_mcp["policy-actors"]

    openai_plugin = output / "openai-agent-plugin" / "policy-research"
    openai_manifest = load_json(openai_plugin / "plugin.json")
    assert openai_manifest["$schema"] == (
        "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
    )
    assert openai_manifest["repository"] == "https://github.com/chrislemke/sourcebook"
    openai_mcp = load_json(openai_plugin / "mcp.json")
    assert openai_mcp["mcpServers"]["policy-evidence"] == {
        "type": "stdio",
        "command": "./bin/policy-mcp",
        "args": ["serve", "--profile", "evidence"],
    }

    claude_skill = claude_plugin / "skills" / "policy-research" / "SKILL.md"
    openai_skill = openai_plugin / "skills" / "policy-research" / "SKILL.md"
    assert claude_skill.read_bytes() == openai_skill.read_bytes()
    assert len(claude_skill.read_text().split()) < 400
    assert (
        output / "marketplaces" / "openai" / "plugins" / "policy-research" / "plugin.json"
    ).is_file()


def tree_snapshot(root: Path) -> dict[str, tuple[int, bytes]]:
    return {
        str(path.relative_to(root)): (stat.S_IMODE(path.stat().st_mode), path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.mark.parametrize(
    ("target", "platform", "binary_name"),
    [
        ("darwin-arm64", "darwin", "policy-mcp"),
        ("windows-x64", "win32", "policy-mcp.exe"),
    ],
)
def test_package_families_are_reproducible_and_contain_no_secrets(
    tmp_path: Path,
    target: str,
    platform: str,
    binary_name: str,
) -> None:
    binary = tmp_path / "policy-mcp"
    make_binary(binary)
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first = build_packages(binary, first_root, target=target)
    build_packages(binary, second_root, target=target)

    assert tree_snapshot(first_root) == tree_snapshot(second_root)

    for profile in first.mcp_bundles:
        with zipfile.ZipFile(first.mcp_bundles[profile]) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            expected_path = f"server/{binary_name}"
            assert manifest["compatibility"]["platforms"] == [platform]
            assert manifest["server"]["entry_point"] == expected_path
            assert manifest["server"]["mcp_config"]["command"] == (
                f"${{__dirname}}/{expected_path}"
            )
            selected = Profile(profile)
            assert manifest["tools"] == [
                {"name": name, "description": tool_description(name)}
                for name in PROFILE_TOOL_NAMES[selected]
            ]
            for member in archive.namelist():
                content = archive.read(member)
                assert b"seeded-test-secret" not in content
            # Packages may name the key but only ever carry the client's placeholder.
            assert set(manifest["server"]["mcp_config"]["env"].values()) <= {
                "${user_config.dip_api_key}"
            }
