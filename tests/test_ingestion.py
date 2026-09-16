"""Tests for bounded live-source ingestion."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from policy_mcp.adapters.dip import DipProcedure, DipProcedurePage
from policy_mcp.ingestion import dip_sync_record, sync_dip_window
from policy_mcp.storage import open_database


def _procedure(provider_id: str, modified_at: str) -> DipProcedure:
    return DipProcedure(
        provider_id=provider_id,
        procedure_type="Gesetzgebung",
        provider_status="Beratung",
        title=f"Digitalgesetz {provider_id}",
        parliamentary_term=21,
        initiatives=("Bundesregierung",),
        document_date="2026-09-15",
        source_modified_at=modified_at,
        abstract="Digitale Verwaltung",
        provider_labels=("Digitalisierung",),
        gesta=None,
        consent_labels=(),
        events=(),
        documents=(),
        related_procedures=(),
    )


class _Pages:
    def __init__(self, pages: list[DipProcedurePage]) -> None:
        self.pages = pages
        self.cursors: list[str | None] = []
        self.ends: list[datetime | None] = []

    async def fetch_modifications(
        self,
        since: datetime,
        *,
        until: datetime | None = None,
        overlap: timedelta,
        cursor: str | None = None,
    ) -> DipProcedurePage:
        del since, overlap
        self.cursors.append(cursor)
        self.ends.append(until)
        return self.pages[len(self.cursors) - 1]


def test_dip_record_is_stable_and_does_not_claim_unparsed_documents() -> None:
    record = dip_sync_record(_procedure("334562", "2026-09-15T12:00:00Z"))

    assert record.provider_id == "334562"
    assert record.payload["key"] == "dip:vorgang:334562"
    assert record.payload["document_keys"] == []
    assert len(record.content_hash) == 64


async def test_dip_window_is_paginated_filtered_and_persisted_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POLICY_MCP_DATA_DIR", str(tmp_path))
    pages = _Pages(
        [
            DipProcedurePage(
                items=(_procedure("2", "2026-09-15T12:00:00Z"),),
                total_found=3,
                next_cursor="second-page",
                window_start="2026-09-15T00:00:00+00:00",
            ),
            DipProcedurePage(
                items=(
                    _procedure("1", "2026-09-15T10:00:00Z"),
                    _procedure("3", "2026-09-17T10:00:00Z"),
                ),
                total_found=3,
                next_cursor=None,
                window_start="2026-09-15T00:00:00+00:00",
            ),
        ]
    )

    report = await sync_dip_window(
        pages,
        since=datetime(2026, 9, 15, tzinfo=UTC),
        until=datetime(2026, 9, 16, tzinfo=UTC),
    )

    assert pages.cursors == [None, "second-page"]
    assert pages.ends == [
        datetime(2026, 9, 16, tzinfo=UTC),
        datetime(2026, 9, 16, tzinfo=UTC),
    ]
    assert report.fetched == 2
    assert report.persisted == 2
    with open_database() as connection:
        assert connection.execute("SELECT COUNT(*) FROM records").fetchone() == (2,)
        assert connection.execute(
            "SELECT completed_watermark FROM sync_state WHERE source_id = 'dip'"
        ).fetchone() == ("2026-09-16T00:00:00+00:00",)


async def test_failed_dip_page_does_not_persist_or_advance_watermark(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POLICY_MCP_DATA_DIR", str(tmp_path))

    class _BrokenPages(_Pages):
        async def fetch_modifications(
            self,
            since: datetime,
            *,
            until: datetime | None = None,
            overlap: timedelta,
            cursor: str | None = None,
        ) -> DipProcedurePage:
            if cursor is not None:
                raise RuntimeError("provider failed")
            return await super().fetch_modifications(
                since,
                until=until,
                overlap=overlap,
                cursor=cursor,
            )

    pages = _BrokenPages(
        [
            DipProcedurePage(
                items=(_procedure("1", "2026-09-15T10:00:00Z"),),
                total_found=2,
                next_cursor="second-page",
                window_start="2026-09-15T00:00:00+00:00",
            )
        ]
    )

    with pytest.raises(RuntimeError, match="provider failed"):
        await sync_dip_window(
            pages,
            since=datetime(2026, 9, 15, tzinfo=UTC),
            until=datetime(2026, 9, 16, tzinfo=UTC),
        )

    with open_database() as connection:
        assert connection.execute("SELECT COUNT(*) FROM records").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM sync_state").fetchone() == (0,)
