"""Tests for the project command-line entry point."""

import json
import stat
from pathlib import Path

import pytest

from policy_mcp import __version__
from policy_mcp.cli import build_parser, main
from policy_mcp.storage import open_database


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        main(["--version"])

    assert error.value.code == 0
    assert capsys.readouterr().out == f"policy-mcp {__version__}\n"


def test_serve_requires_a_profile() -> None:
    parser = build_parser()

    with pytest.raises(SystemExit) as error:
        parser.parse_args(["serve"])

    assert error.value.code == 2


def test_serve_accepts_each_profile() -> None:
    parser = build_parser()

    for profile in ("legislation", "actors", "evidence"):
        args = parser.parse_args(["serve", "--profile", profile])
        assert args.profile == profile


def test_package_command_builds_artifacts(tmp_path: Path) -> None:
    binary = tmp_path / "policy-mcp"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    output = tmp_path / "release"

    assert (
        main(
            [
                "package",
                "--binary",
                str(binary),
                "--output",
                str(output),
                "--target",
                "darwin-arm64",
            ]
        )
        == 0
    )

    assert (output / "claude-desktop" / "policy-legislation-0.1.0-darwin-arm64.mcpb").is_file()


def test_operator_can_verify_registry_and_back_up_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data = tmp_path / "live state"
    monkeypatch.setenv("POLICY_MCP_DATA_DIR", str(data))
    with open_database() as connection:
        connection.execute(
            "INSERT INTO sources(source_id, status) VALUES ('dip', 'not_configured')"
        )
    backup = tmp_path / "backup"

    assert main(["verify-schemas", "--registry", "config/sources.yaml"]) == 0
    verification = json.loads(capsys.readouterr().out)
    assert verification == {"registry_version": 1, "issues": []}

    assert main(["backup", "--output", str(backup)]) == 0
    backup_report = json.loads(capsys.readouterr().out)
    assert backup_report["backup_version"] == 1
    assert (backup / "manifest.json").is_file()


def test_sync_and_backfill_fail_closed_for_unconfigured_source(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["sync", "--source", "dip", "--registry", "config/sources.yaml"]) == 2
    sync = json.loads(capsys.readouterr().out)
    assert sync["status"] == "not_configured"

    assert (
        main(
            [
                "backfill",
                "--source",
                "dip",
                "--from-date",
                "2026-01-01",
                "--to-date",
                "2026-01-31",
                "--registry",
                "config/sources.yaml",
            ]
        )
        == 2
    )
    backfill = json.loads(capsys.readouterr().out)
    assert backfill["status"] == "not_configured"


def test_measure_tool_tokens_reports_each_host_visible_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("POLICY_MCP_DATA_DIR", str(tmp_path))

    assert main(["measure-tool-tokens", "--profile", "legislation"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["profile"] == "legislation"
    assert len(report["tools"]) == 6
    assert report["schema_bytes"] > 0
    assert report["estimated_tokens"] == (report["schema_bytes"] + 3) // 4
