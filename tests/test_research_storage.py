"""Storage contract tests for versioned source ingestion."""

from __future__ import annotations

from pathlib import Path

import pytest

from policy_mcp.storage import (
    DocumentStore,
    SyncRecord,
    database_ingestion_lock,
    open_database,
    persist_sync_window,
)


def test_database_has_versioned_research_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POLICY_MCP_DATA_DIR", str(tmp_path))

    with open_database() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            )
        }

    assert {
        "sources",
        "records",
        "record_versions",
        "relations",
        "text_sections",
        "dataset_schemas",
        "sync_state",
        "search_snapshots",
        "search_snapshot_items",
        "record_search",
    } <= tables


def test_complete_sync_window_persists_versions_then_advances_watermark(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POLICY_MCP_DATA_DIR", str(tmp_path))
    records = [
        SyncRecord(
            provider_id="BT-20/123",
            provider_version="2026-09-01T10:00:00Z",
            entity_kind="procedure",
            content_hash="a" * 64,
            source_timestamp="2026-09-01T10:00:00Z",
            payload={"title": "Beispielgesetz"},
        )
    ]

    persisted = persist_sync_window(
        "dip",
        window_start="2026-08-31T00:00:00Z",
        window_end="2026-09-02T00:00:00Z",
        records=records,
    )

    assert persisted == 1
    with open_database() as connection:
        version = connection.execute(
            "SELECT provider_version, content_hash FROM record_versions"
        ).fetchone()
        search_match = connection.execute(
            "SELECT record_id FROM record_search WHERE record_search MATCH 'Beispielgesetz'"
        ).fetchone()
        sync = connection.execute(
            "SELECT completed_watermark, in_progress_cursor FROM sync_state WHERE source_id = ?",
            ("dip",),
        ).fetchone()
    assert version == ("2026-09-01T10:00:00Z", "a" * 64)
    assert search_match is not None
    assert sync == ("2026-09-02T00:00:00Z", None)


def test_failed_sync_window_does_not_advance_watermark(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POLICY_MCP_DATA_DIR", str(tmp_path))

    def broken_records():
        yield SyncRecord(
            provider_id="first",
            provider_version="1",
            entity_kind="procedure",
            content_hash="b" * 64,
            source_timestamp=None,
            payload={"title": "first"},
        )
        raise RuntimeError("provider page failed")

    with pytest.raises(RuntimeError, match="provider page failed"):
        persist_sync_window(
            "dip",
            window_start="2026-08-31T00:00:00Z",
            window_end="2026-09-02T00:00:00Z",
            records=broken_records(),
        )

    with open_database() as connection:
        assert connection.execute("SELECT COUNT(*) FROM record_versions").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM sync_state").fetchone() == (0,)


def test_only_one_process_can_hold_the_ingestion_lock(tmp_path: Path) -> None:
    with (
        database_ingestion_lock(tmp_path, timeout_ms=20),
        pytest.raises(TimeoutError, match="ingestion lock"),
        database_ingestion_lock(tmp_path, timeout_ms=20),
    ):
        pass


def test_ingestion_lock_ignores_stale_file_contents(tmp_path: Path) -> None:
    (tmp_path / ".ingestion.lock").write_text("999999999:stale")

    with database_ingestion_lock(tmp_path, timeout_ms=20):
        assert (tmp_path / ".ingestion.lock").exists()

    assert (tmp_path / ".ingestion.lock").exists()


def test_document_store_is_content_addressed_and_immutable(tmp_path: Path) -> None:
    store = DocumentStore(tmp_path / "documents", max_bytes=20)

    first = store.put(b"official bytes")
    repeated = store.put(b"official bytes")

    assert first == repeated
    assert first.name == "62dbe6d8f9a2196315f659ab2e1776b2f1283428daba85f89cdd22a950c6dc5a"
    assert store.read(first.name) == b"official bytes"
    assert [path.name for path in (tmp_path / "documents").iterdir()] == [first.name]
    with pytest.raises(ValueError, match="maximum size"):
        store.put(b"x" * 21)
    with pytest.raises(ValueError, match="content hash"):
        store.read("../sourcebook.sqlite3")


def test_duplicate_source_version_is_deduplicated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POLICY_MCP_DATA_DIR", str(tmp_path))
    record = SyncRecord(
        provider_id="same",
        provider_version="v1",
        entity_kind="document",
        content_hash="c" * 64,
        source_timestamp=None,
        payload={"title": "same"},
    )

    persist_sync_window("dip", window_start="1", window_end="2", records=[record])
    persist_sync_window("dip", window_start="1", window_end="3", records=[record])

    with open_database() as connection:
        assert connection.execute("SELECT COUNT(*) FROM records").fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM record_versions").fetchone() == (1,)
