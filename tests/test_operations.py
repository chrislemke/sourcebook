"""Public recovery and route-health tests for operator workflows."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from policy_mcp.operations import (
    BackupVerificationError,
    backup_state,
    restore_state,
    summarize_route_health,
    verify_backup,
)
from policy_mcp.registry import RouteState, load_registry
from policy_mcp.storage import DocumentStore, open_database


def seed_state(data_directory: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    monkeypatch.setenv("POLICY_MCP_DATA_DIR", str(data_directory))
    with open_database() as connection:
        connection.execute("INSERT INTO sources(source_id, status) VALUES ('dip', 'healthy')")
        connection.execute(
            "INSERT INTO sync_state(source_id, completed_watermark, window_start) "
            "VALUES ('dip', '2026-09-16T12:00:00Z', '2026-09-16T11:30:00Z')"
        )
    documents = {
        hashlib.sha256(content).hexdigest(): content
        for content in (b"first immutable document", b"second immutable document")
    }
    store = DocumentStore(data_directory / "documents")
    for content in documents.values():
        store.put(content)
    return documents


def test_backup_checkpoints_database_and_hashes_database_and_documents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_directory = tmp_path / "live state"
    documents = seed_state(data_directory, monkeypatch)
    destination = tmp_path / "backup"

    manifest = backup_state(destination)
    verified = verify_backup(destination)

    assert manifest == verified
    assert {entry.path for entry in manifest.files} == {
        "sourcebook.sqlite3",
        *(f"documents/{digest}" for digest in documents),
    }
    for entry in manifest.files:
        content = (destination / entry.path).read_bytes()
        assert entry.sha256 == hashlib.sha256(content).hexdigest()
        assert entry.size == len(content)
    with sqlite3.connect(destination / "sourcebook.sqlite3") as connection:
        assert connection.execute(
            "SELECT completed_watermark, window_start FROM sync_state WHERE source_id = 'dip'"
        ).fetchone() == ("2026-09-16T12:00:00Z", "2026-09-16T11:30:00Z")


def test_verify_backup_detects_content_corruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    documents = seed_state(tmp_path / "live", monkeypatch)
    destination = tmp_path / "backup"
    backup_state(destination)
    corrupted = destination / "documents" / next(iter(documents))
    corrupted.write_bytes(b"changed after backup")

    with pytest.raises(BackupVerificationError, match="Hash mismatch"):
        verify_backup(destination)


def test_restore_verifies_first_preserves_sync_state_and_replaces_only_when_requested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    documents = seed_state(tmp_path / "live", monkeypatch)
    backup = tmp_path / "backup"
    backup_state(backup)
    restored = tmp_path / "restored state"

    assert restore_state(backup, restored) == restored
    with sqlite3.connect(restored / "sourcebook.sqlite3") as connection:
        assert connection.execute(
            "SELECT completed_watermark FROM sync_state WHERE source_id = 'dip'"
        ).fetchone() == ("2026-09-16T12:00:00Z",)
    assert {
        path.name: path.read_bytes() for path in (restored / "documents").iterdir()
    } == documents

    marker = restored / "operator-note.txt"
    marker.write_text("keep until replacement is explicit")
    with pytest.raises(FileExistsError, match="non-empty"):
        restore_state(backup, restored)
    assert marker.is_file()

    restore_state(backup, restored, replace=True)
    assert not marker.exists()
    assert not list(tmp_path.glob(".restored state-restore-*"))


def test_restore_does_not_touch_destination_when_backup_is_corrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_state(tmp_path / "live", monkeypatch)
    backup = tmp_path / "backup"
    backup_state(backup)
    manifest = json.loads((backup / "manifest.json").read_text())
    manifest["files"][0]["sha256"] = "0" * 64
    (backup / "manifest.json").write_text(json.dumps(manifest))
    destination = tmp_path / "existing"
    destination.mkdir()
    marker = destination / "keep.txt"
    marker.write_text("untouched")

    with pytest.raises(BackupVerificationError):
        restore_state(backup, destination, replace=True)

    assert marker.read_text() == "untouched"


def test_route_health_summary_preserves_distinct_failure_states(tmp_path: Path) -> None:
    registry_path = tmp_path / "sources.yaml"
    registry_path.write_text(
        """
registry_version: 1
policy:
  no_fee_sources_only: true
  public_read_only: true
  default_search_limit: 5
  interactive_max_provider_requests: 6
sources:
  example:
    adapter: ExampleAdapter
    transport: rest
    allowed_hosts: [example.test]
    credential_transport: none
    fixture_hashes: {}
    licence: {name: public, url: "https://example.test/licence"}
    attribution: Example publisher
    date_bases: [published_at]
    pagination: {kind: cursor, stable: true}
    refresh_policy: {cadence: hourly, freshness_threshold: PT2H}
    supported_languages: [en]
    language_fallback: explicit_only
    coverage_limits: Test fixture only.
    parser_version: "1"
    routes:
      missing_credentials:
        state: not_configured
        allowed_operations: [search]
        enable_after: [credentials]
      provider_outage:
        state: temporarily_unavailable
        allowed_operations: [get]
        enable_after: []
      changed_contract:
        state: healthy
        allowed_operations: [list]
        enable_after: []
        unknown_field: rejected
""".strip()
        + "\n"
    )
    registry = load_registry(registry_path)

    summary = summarize_route_health(registry)

    assert summary.total_routes == 3
    assert summary.counts == {
        RouteState.NOT_CONFIGURED: 1,
        RouteState.SCHEMA_CHANGED: 1,
        RouteState.TEMPORARILY_UNAVAILABLE: 1,
    }
    assert {(route.route_id, route.state) for route in summary.routes} == {
        ("missing_credentials", RouteState.NOT_CONFIGURED),
        ("changed_contract", RouteState.SCHEMA_CHANGED),
        ("provider_outage", RouteState.TEMPORARILY_UNAVAILABLE),
    }
