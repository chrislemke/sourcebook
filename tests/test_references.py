"""Persistent opaque reference and cursor contracts."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from policy_mcp.references import (
    MAX_SNAPSHOT_ITEMS,
    ExpiredCursorError,
    ForgedCursorError,
    ForgedReferenceError,
    SQLiteReferenceStore,
)


def test_reference_is_stable_across_process_instances_and_principal_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POLICY_MCP_DATA_DIR", str(tmp_path))
    first = SQLiteReferenceStore(principal="installation-a")
    reference = first.reference_for(principal="installation-a", kind="procedure", key="dip:123")

    restarted = SQLiteReferenceStore(principal="installation-a")

    assert (
        restarted.reference_for(principal="installation-a", kind="procedure", key="dip:123")
        == reference
    )
    assert (
        restarted.resolve(reference, principal="installation-a", expected_kinds=("procedure",))
        == "dip:123"
    )
    with pytest.raises(ForgedReferenceError):
        restarted.resolve(reference, principal="installation-b", expected_kinds=("procedure",))

    with sqlite3.connect(tmp_path / "sourcebook.sqlite3") as connection:
        stored = connection.execute("SELECT token_digest FROM opaque_references").fetchone()[0]
    assert reference not in stored


def test_cursor_survives_restart_and_remains_query_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POLICY_MCP_DATA_DIR", str(tmp_path))
    now = datetime(2026, 9, 16, tzinfo=UTC)
    first = SQLiteReferenceStore(principal="installation-a", clock=lambda: now)
    page = first.first_page(
        ["one", "two", "three"],
        principal="installation-a",
        query_hash="query-a",
        limit=1,
    )
    assert page.keys == ("one",)
    assert page.cursor is not None

    restarted = SQLiteReferenceStore(principal="installation-a", clock=lambda: now)
    second = restarted.next_page(
        page.cursor,
        principal="installation-a",
        query_hash="query-a",
        limit=1,
    )
    assert second.keys == ("two",)
    with pytest.raises(ForgedCursorError):
        restarted.next_page(
            page.cursor,
            principal="installation-a",
            query_hash="different-query",
            limit=1,
        )


def test_expired_persistent_cursor_requires_search_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POLICY_MCP_DATA_DIR", str(tmp_path))
    now = datetime(2026, 9, 16, tzinfo=UTC)
    store = SQLiteReferenceStore(
        principal="installation-a",
        clock=lambda: now,
        cursor_ttl=timedelta(seconds=1),
    )
    page = store.first_page(["one", "two"], principal="installation-a", query_hash="query", limit=1)
    assert page.cursor is not None

    expired = SQLiteReferenceStore(
        principal="installation-a",
        clock=lambda: now + timedelta(seconds=2),
    )
    with pytest.raises(ExpiredCursorError):
        expired.next_page(
            page.cursor,
            principal="installation-a",
            query_hash="query",
            limit=1,
        )

    with pytest.raises(ForgedCursorError):
        expired.next_page(
            page.cursor,
            principal="installation-a",
            query_hash="query",
            limit=1,
        )


def test_persistent_snapshot_rejects_unbounded_result_sets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POLICY_MCP_DATA_DIR", str(tmp_path))
    store = SQLiteReferenceStore(principal="installation-a")

    with pytest.raises(ValueError, match="item limit"):
        store.first_page(
            [str(index) for index in range(MAX_SNAPSHOT_ITEMS + 1)],
            principal="installation-a",
            query_hash="query",
            limit=5,
        )
