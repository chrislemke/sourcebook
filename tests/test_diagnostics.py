"""Tests for non-model-facing configuration and health checks."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from policy_mcp.cli import main
from policy_mcp.diagnostics import run_doctor


def test_doctor_reports_shared_store_without_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("POLICY_MCP_DATA_DIR", str(tmp_path / "operator data"))
    monkeypatch.setenv("DIP_API_KEY", "seeded-test-secret")

    assert main(["doctor", "--format", "json"]) == 0

    output = capsys.readouterr().out
    assert "seeded-test-secret" not in output
    report = json.loads(output)
    assert report["status"] == "ok"
    assert [check["name"] for check in report["checks"]] == [
        "executable",
        "data_directory",
        "database",
        "credential_store",
        "route_registry",
        "index_state",
        "sync_state",
    ]
    assert report["checks"][2]["detail"] == "SQLite WAL, busy timeout 5000 ms"


def test_configure_stores_a_secret_without_printing_it(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stored: list[tuple[str, str, str]] = []
    monkeypatch.setattr("policy_mcp.diagnostics.getpass", lambda _prompt: "seeded-test-secret")
    monkeypatch.setattr(
        "policy_mcp.diagnostics.keyring.set_password",
        lambda service, username, value: stored.append((service, username, value)),
    )

    assert main(["configure", "--credential", "DIP_API_KEY"]) == 0

    assert stored == [("sourcebook", "DIP_API_KEY", "seeded-test-secret")]
    assert "seeded-test-secret" not in capsys.readouterr().out


def test_doctor_reports_a_broken_database_instead_of_crashing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POLICY_MCP_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        "policy_mcp.diagnostics.database_health",
        lambda: (_ for _ in ()).throw(sqlite3.DatabaseError("malformed")),
    )

    report = run_doctor()

    assert report.status == "error"
    assert report.checks[2].name == "database"
    assert report.checks[2].detail == "Database failed: malformed"
