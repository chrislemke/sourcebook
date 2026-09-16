"""Bounded live-source ingestion into the shared research store."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from policy_mcp.adapters.dip import DipProcedure, DipProcedurePage
from policy_mcp.storage import SyncRecord, persist_sync_window


class DipWindowTooLargeError(RuntimeError):
    """One modification window holds more records or pages than a bounded sync allows."""


class DipPageClient(Protocol):
    """Small boundary used by the DIP worker and its contract tests."""

    async def fetch_modifications(
        self,
        since: datetime,
        *,
        until: datetime | None = None,
        overlap: timedelta,
        cursor: str | None = None,
    ) -> DipProcedurePage: ...


@dataclass(frozen=True)
class SyncReport:
    """Result of one complete bounded source window."""

    source_id: str
    window_start: str
    window_end: str
    fetched: int
    persisted: int


def dip_record_payload(procedure: DipProcedure) -> dict[str, object]:
    """Project one normalized DIP procedure into the stored legislation record shape."""
    return {
        "key": f"dip:vorgang:{procedure.provider_id}",
        "kind": "procedure",
        "jurisdiction": "DE",
        "source": "dip",
        "provider_id": procedure.provider_id,
        "identifier": procedure.gesta or procedure.provider_id,
        "title": procedure.title,
        "abstract": procedure.abstract or "",
        "subjects": list(procedure.provider_labels),
        "status": procedure.provider_status or procedure.procedure_type,
        "source_language": "de",
        "available_languages": ["de"],
        "official_url": f"https://dip.bundestag.de/vorgang/{procedure.provider_id}",
        "source_modified_at": procedure.source_modified_at,
        "events": [
            {"date": event.date, "label": event.label}
            for event in sorted(procedure.events, key=lambda item: (item.date, item.provider_id))
        ],
        # Linked files are intentionally not advertised as readable until a document
        # worker has fetched and parsed their official contents.
        "document_keys": [],
    }


def dip_sync_record(procedure: DipProcedure) -> SyncRecord:
    """Convert one normalized DIP procedure into the stable storage envelope."""
    payload = dip_record_payload(procedure)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return SyncRecord(
        provider_id=procedure.provider_id,
        provider_version=procedure.source_modified_at,
        entity_kind="procedure",
        content_hash=hashlib.sha256(encoded).hexdigest(),
        source_timestamp=procedure.source_modified_at,
        payload=payload,
    )


async def sync_dip_window(
    client: DipPageClient,
    *,
    since: datetime,
    until: datetime,
    overlap: timedelta = timedelta(hours=2),
    max_pages: int = 5,
    max_records: int = 100,
) -> SyncReport:
    """Fetch and atomically persist one bounded DIP modification window."""
    if since.tzinfo is None or since.utcoffset() is None:
        raise ValueError("DIP sync start must include a timezone")
    if until.tzinfo is None or until.utcoffset() is None:
        raise ValueError("DIP sync end must include a timezone")
    if since > until:
        raise ValueError("DIP sync start must not be after its end")
    if max_pages < 1 or max_records < 1:
        raise ValueError("DIP sync limits must be positive")

    procedures: dict[str, DipProcedure] = {}
    cursor: str | None = None
    for page_number in range(1, max_pages + 1):
        page = await client.fetch_modifications(
            since,
            until=until,
            overlap=overlap,
            cursor=cursor,
        )
        for procedure in page.items:
            modified_at = datetime.fromisoformat(
                procedure.source_modified_at.replace("Z", "+00:00")
            )
            if modified_at <= until:
                procedures[procedure.provider_id] = procedure
        if len(procedures) > max_records:
            raise DipWindowTooLargeError("DIP sync exceeded the record limit")
        if page.next_cursor is None:
            break
        if page.next_cursor == cursor:
            raise RuntimeError("DIP sync pagination made no progress")
        cursor = page.next_cursor
        if page_number == max_pages:
            raise DipWindowTooLargeError("DIP sync exceeded the page limit")

    records: Sequence[SyncRecord] = [
        dip_sync_record(procedure)
        for procedure in sorted(procedures.values(), key=lambda item: item.provider_id)
    ]
    window_start = since.isoformat(timespec="seconds")
    window_end = until.isoformat(timespec="seconds")
    persisted = persist_sync_window(
        "dip",
        window_start=window_start,
        window_end=window_end,
        records=list(records),
    )
    return SyncReport(
        source_id="dip",
        window_start=window_start,
        window_end=window_end,
        fetched=len(procedures),
        persisted=persisted,
    )


class DipRangeClient(DipPageClient, Protocol):
    """A page client that can also count a window before fetching its positions."""

    async def count_modifications(
        self,
        since: datetime,
        *,
        until: datetime,
        overlap: timedelta,
    ) -> int: ...


async def sync_dip_range(
    client: DipRangeClient,
    *,
    since: datetime,
    until: datetime,
    overlap: timedelta = timedelta(hours=2),
    chunk: timedelta = timedelta(hours=6),
    min_chunk: timedelta = timedelta(minutes=15),
    max_pages: int = 5,
    max_records: int = 100,
) -> SyncReport:
    """Sync a long range as consecutive bounded windows, keeping each completed window."""
    if since > until:
        raise ValueError("DIP sync start must not be after its end")
    if min_chunk <= timedelta(0) or chunk < min_chunk:
        raise ValueError("DIP sync chunks must be positive")
    start = since
    size = chunk
    window_overlap = overlap
    fetched = 0
    persisted = 0
    while True:
        end = min(start + size, until)
        count = await client.count_modifications(start, until=end, overlap=window_overlap)
        if count > max_records and end - start > min_chunk:
            size = max((end - start) / 2, min_chunk)
            continue
        if count > max_records:
            raise DipWindowTooLargeError(
                f"DIP changed more than {max_records} procedures within {min_chunk}"
            )
        report = await sync_dip_window(
            client,
            since=start,
            until=end,
            overlap=window_overlap,
            max_pages=max_pages,
            max_records=max_records,
        )
        fetched += report.fetched
        persisted += report.persisted
        if end >= until:
            break
        start = end
        size = chunk
        # Only the first window needs overlap with the previous run's watermark.
        window_overlap = timedelta(0)
    return SyncReport(
        source_id="dip",
        window_start=since.isoformat(timespec="seconds"),
        window_end=until.isoformat(timespec="seconds"),
        fetched=fetched,
        persisted=persisted,
    )
