"""Tests for reproducible client package generation."""

from __future__ import annotations

import json
import stat
import zipfile
from pathlib import Path
from typing import Any

from policy_mcp.packaging import build_packages


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
    for profile, bundle in report.mcp_bundles.items():
        assert bundle.name == f"policy-{profile}-0.1.0-darwin-arm64.mcpb"
        with zipfile.ZipFile(bundle) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            assert manifest["manifest_version"] == "0.3"
            assert manifest["name"] == f"policy-{profile}"
            assert manifest["compatibility"]["platforms"] == ["darwin"]
            assert manifest["server"]["type"] == "binary"
            assert manifest["server"]["mcp_config"] == {
                "command": "${__dirname}/server/policy-mcp",
                "args": ["serve", "--profile", profile],
                "env": {},
            }
            binary_info = archive.getinfo("server/policy-mcp")
            assert binary_info.external_attr >> 16 & stat.S_IXUSR

    claude_plugin = output / "claude-code-plugin" / "policy-research"
    claude_mcp = load_json(claude_plugin / ".mcp.json")
    assert list(claude_mcp) == ["policy-legislation", "policy-actors", "policy-evidence"]
    assert claude_mcp["policy-legislation"] == {
        "command": "${CLAUDE_PLUGIN_ROOT}/bin/policy-mcp",
        "args": ["serve", "--profile", "legislation"],
    }

    openai_plugin = output / "openai-agent-plugin" / "policy-research"
    assert load_json(openai_plugin / "plugin.json")["$schema"] == (
        "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
    )
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


def test_package_archives_are_reproducible_and_contain_no_secrets(tmp_path: Path) -> None:
    binary = tmp_path / "policy-mcp"
    make_binary(binary)
    first = build_packages(binary, tmp_path / "first", target="windows-x64")
    second = build_packages(binary, tmp_path / "second", target="windows-x64")

    for profile in first.mcp_bundles:
        first_bytes = first.mcp_bundles[profile].read_bytes()
        second_bytes = second.mcp_bundles[profile].read_bytes()
        assert first_bytes == second_bytes
        assert b"seeded-test-secret" not in first_bytes
        assert b"DIP_API_KEY" not in first_bytes
