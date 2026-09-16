"""Tests for client registration setup."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from policy_mcp.client_setup import registration_command, removal_command, setup_client
from policy_mcp.profiles import Profile


def test_claude_registration_uses_user_scoped_stdio(tmp_path: Path) -> None:
    server = tmp_path / "path with spaces" / "policy-mcp"

    command = registration_command("claude-code", "/usr/bin/claude", server, Profile.ACTORS)

    assert command == [
        "/usr/bin/claude",
        "mcp",
        "add",
        "--transport",
        "stdio",
        "--scope",
        "user",
        "policy-actors",
        "--",
        str(server.resolve()),
        "serve",
        "--profile",
        "actors",
    ]


def test_codex_registration_keeps_server_path_as_one_argument(tmp_path: Path) -> None:
    server = tmp_path / "path with spaces" / "policy-mcp"

    command = registration_command("codex-cli", "/usr/bin/codex", server, Profile.EVIDENCE)

    assert command == [
        "/usr/bin/codex",
        "mcp",
        "add",
        "policy-evidence",
        "--",
        str(server.resolve()),
        "serve",
        "--profile",
        "evidence",
    ]


def test_removal_targets_only_the_user_scoped_sourcebook_registration() -> None:
    assert removal_command("claude-code", "/usr/bin/claude", Profile.LEGISLATION) == [
        "/usr/bin/claude",
        "mcp",
        "remove",
        "--scope",
        "user",
        "policy-legislation",
    ]
    assert removal_command("codex-cli", "/usr/bin/codex", Profile.EVIDENCE) == [
        "/usr/bin/codex",
        "mcp",
        "remove",
        "policy-evidence",
    ]


def test_dry_run_plans_all_profiles_without_running_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = tmp_path / "policy-mcp"
    server.write_text("binary")
    monkeypatch.setattr("policy_mcp.client_setup.shutil.which", lambda _name: "/usr/bin/codex")
    monkeypatch.setattr(
        "policy_mcp.client_setup.subprocess.run",
        lambda *_args, **_kwargs: pytest.fail("dry-run must not execute host commands"),
    )

    report = setup_client("codex-cli", server, dry_run=True)

    assert report.status == "planned"
    assert [step.profile for step in report.steps] == ["legislation", "actors", "evidence"]
    assert {step.status for step in report.steps} == {"planned"}


def test_setup_registers_every_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = tmp_path / "policy-mcp"
    server.write_text("binary")
    commands: list[list[str]] = []
    monkeypatch.setattr("policy_mcp.client_setup.shutil.which", lambda _name: "/usr/bin/claude")

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("policy_mcp.client_setup.subprocess.run", run)

    report = setup_client("claude-code", server)

    assert report.status == "ok"
    add_commands = [command for command in commands if command[2] == "add"]
    assert [command[7] for command in add_commands] == [
        "policy-legislation",
        "policy-actors",
        "policy-evidence",
    ]
    assert len(commands) == 6
    assert {step.status for step in report.steps} == {"installed"}


def test_setup_stops_and_reports_host_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = tmp_path / "policy-mcp"
    server.write_text("binary")
    monkeypatch.setattr("policy_mcp.client_setup.shutil.which", lambda _name: "/usr/bin/codex")

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[2] == "remove":
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="not found")
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="registration failed",
        )

    monkeypatch.setattr("policy_mcp.client_setup.subprocess.run", run)

    report = setup_client("codex-cli", server)

    assert report.status == "error"
    assert len(report.steps) == 1
    assert report.steps[0].detail == "registration failed"


def test_setup_reports_a_missing_server_executable(tmp_path: Path) -> None:
    server = tmp_path / "missing-policy-mcp"

    report = setup_client("codex-cli", server)

    assert report.status == "error"
    assert report.steps[0].profile == "executable"
    assert str(server) in report.steps[0].detail
