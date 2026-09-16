"""Shared local storage used by every policy-mcp profile."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_path

if os.name == "nt":  # pragma: no cover - exercised by the Windows package job
    import msvcrt
else:  # pragma: no cover - platform branch
    import fcntl

DATA_DIR_ENV = "POLICY_MCP_DATA_DIR"
DATABASE_NAME = "sourcebook.sqlite3"
BUSY_TIMEOUT_MS = 5_000
INITIALIZATION_LOCK_NAME = ".database-init.lock"
INGESTION_LOCK_NAME = ".ingestion.lock"

SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS sources (
        source_id TEXT PRIMARY KEY,
        status TEXT NOT NULL DEFAULT 'not_configured',
        parser_version TEXT,
        last_checked_at TEXT,
        last_error_code TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS records (
        id INTEGER PRIMARY KEY,
        source_id TEXT NOT NULL REFERENCES sources(source_id),
        provider_id TEXT NOT NULL,
        entity_kind TEXT NOT NULL,
        UNIQUE(source_id, provider_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS record_versions (
        id INTEGER PRIMARY KEY,
        record_id INTEGER NOT NULL REFERENCES records(id),
        provider_version TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        source_timestamp TEXT,
        retrieved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        payload_json TEXT NOT NULL,
        UNIQUE(record_id, provider_version, content_hash)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS relations (
        id INTEGER PRIMARY KEY,
        subject_record_id INTEGER NOT NULL REFERENCES records(id),
        predicate TEXT NOT NULL,
        object_record_id INTEGER NOT NULL REFERENCES records(id),
        basis TEXT NOT NULL,
        evidence_version_id INTEGER REFERENCES record_versions(id),
        valid_from TEXT,
        valid_to TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS text_sections (
        id INTEGER PRIMARY KEY,
        record_version_id INTEGER NOT NULL REFERENCES record_versions(id),
        ordinal INTEGER NOT NULL,
        heading TEXT,
        locator TEXT NOT NULL,
        language TEXT NOT NULL,
        text TEXT NOT NULL,
        UNIQUE(record_version_id, ordinal)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dataset_schemas (
        dataset_record_id INTEGER NOT NULL REFERENCES records(id),
        schema_version TEXT NOT NULL,
        schema_json TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        PRIMARY KEY(dataset_record_id, schema_version)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sync_state (
        source_id TEXT PRIMARY KEY REFERENCES sources(source_id),
        completed_watermark TEXT,
        in_progress_cursor TEXT,
        window_start TEXT,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS search_snapshots (
        snapshot_id TEXT PRIMARY KEY,
        principal_id TEXT NOT NULL,
        query_hash TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS search_snapshot_items (
        snapshot_id TEXT NOT NULL REFERENCES search_snapshots(snapshot_id) ON DELETE CASCADE,
        ordinal INTEGER NOT NULL,
        record_id INTEGER NOT NULL REFERENCES records(id),
        PRIMARY KEY(snapshot_id, ordinal)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS opaque_references (
        token_digest TEXT PRIMARY KEY,
        principal_id TEXT NOT NULL,
        entity_kind TEXT NOT NULL,
        entity_key TEXT NOT NULL,
        UNIQUE(principal_id, entity_kind, entity_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS opaque_snapshots (
        token_digest TEXT PRIMARY KEY,
        principal_id TEXT NOT NULL,
        query_hash TEXT NOT NULL,
        position INTEGER NOT NULL,
        expires_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS opaque_snapshot_items (
        token_digest TEXT NOT NULL REFERENCES opaque_snapshots(token_digest) ON DELETE CASCADE,
        ordinal INTEGER NOT NULL,
        entity_key TEXT NOT NULL,
        PRIMARY KEY(token_digest, ordinal)
    )
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS record_search USING fts5(
        record_id UNINDEXED,
        title,
        abstract,
        subjects
    )
    """,
)


@dataclass(frozen=True)
class DatabaseHealth:
    """Small, serializable report for the diagnostic tool and doctor command."""

    journal_mode: str
    busy_timeout_ms: int
    readable: bool
    writable: bool


@dataclass(frozen=True)
class SyncRecord:
    """One normalized provider record ready for an atomic sync window."""

    provider_id: str
    provider_version: str
    entity_kind: str
    content_hash: str
    source_timestamp: str | None
    payload: dict[str, object]


class DocumentStore:
    """Content-addressed immutable storage for retrieved source bytes."""

    def __init__(self, root: Path, *, max_bytes: int = 25_000_000) -> None:
        self.root = root
        self.max_bytes = max_bytes

    def put(self, content: bytes) -> Path:
        """Store bytes once and return their content-addressed path."""
        if len(content) > self.max_bytes:
            raise ValueError(f"Document exceeds maximum size of {self.max_bytes} bytes")
        digest = hashlib.sha256(content).hexdigest()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        destination = self.root / digest
        if destination.exists():
            if destination.read_bytes() != content:
                raise RuntimeError(f"Content hash collision for {digest}")
            return destination
        staging = self.root / f".{digest}.{os.getpid()}.{secrets.token_hex(8)}"
        descriptor = os.open(staging, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            view = memoryview(content)
            while view:
                written = os.write(descriptor, view)
                if written == 0:
                    raise OSError("Document write made no progress")
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            if hashlib.sha256(staging.read_bytes()).hexdigest() != digest:
                raise RuntimeError("Staged document failed its content-hash check")
            os.replace(staging, destination)
        finally:
            staging.unlink(missing_ok=True)
        return destination

    def read(self, content_hash: str) -> bytes:
        """Read bytes by a validated SHA-256 digest."""
        if len(content_hash) != 64 or any(char not in "0123456789abcdef" for char in content_hash):
            raise ValueError("Invalid content hash")
        return (self.root / content_hash).read_bytes()


def data_directory() -> Path:
    """Return the shared mutable-data directory, never a package directory."""
    configured = os.environ.get(DATA_DIR_ENV)
    if configured:
        return Path(configured).expanduser()
    return user_data_path("sourcebook", appauthor=False, ensure_exists=False)


def database_path() -> Path:
    """Return the shared SQLite database path."""
    return data_directory() / DATABASE_NAME


@contextmanager
def database_initialization_lock(directory: Path) -> Iterator[None]:
    """Serialize first-open SQLite setup across local client processes."""
    lock_path = directory / INITIALIZATION_LOCK_NAME
    deadline = time.monotonic() + (BUSY_TIMEOUT_MS / 1_000)
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as error:
            if time.monotonic() >= deadline:
                message = f"Timed out waiting for database initialization lock: {lock_path}"
                raise TimeoutError(message) from error
            time.sleep(0.05)
    try:
        os.write(descriptor, str(os.getpid()).encode("ascii"))
        yield
    finally:
        os.close(descriptor)
        lock_path.unlink(missing_ok=True)


@contextmanager
def database_ingestion_lock(
    directory: Path | None = None, *, timeout_ms: int = BUSY_TIMEOUT_MS
) -> Iterator[None]:
    """Serialize ingestion across local processes without blocking readers."""
    selected = directory or data_directory()
    selected.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = selected / INGESTION_LOCK_NAME
    deadline = time.monotonic() + (timeout_ms / 1_000)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    while not acquired:
        try:
            if os.name == "nt":  # pragma: no cover - exercised by the Windows package job
                if os.fstat(descriptor).st_size == 0:
                    os.write(descriptor, b"0")
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except (BlockingIOError, OSError) as error:
            if time.monotonic() >= deadline:
                message = f"Timed out waiting for ingestion lock: {lock_path}"
                os.close(descriptor)
                raise TimeoutError(message) from error
            time.sleep(min(0.01, timeout_ms / 1_000))
    try:
        yield
    finally:
        if os.name == "nt":  # pragma: no cover - exercised by the Windows package job
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def open_database() -> sqlite3.Connection:
    """Open the shared database with settings suitable for concurrent clients."""
    directory = data_directory()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    with database_initialization_lock(directory):
        connection = sqlite3.connect(database_path(), timeout=BUSY_TIMEOUT_MS / 1_000)
        connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS store_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        for statement in SCHEMA_STATEMENTS:
            connection.execute(statement)
        connection.commit()
    return connection


def persist_sync_window(
    source_id: str,
    *,
    window_start: str,
    window_end: str,
    records: Iterator[SyncRecord] | list[SyncRecord],
) -> int:
    """Persist a complete provider window before advancing its watermark."""
    persisted = 0
    with database_ingestion_lock(), open_database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT INTO sources(source_id, status) VALUES (?, 'healthy') "
            "ON CONFLICT(source_id) DO UPDATE SET status = excluded.status",
            (source_id,),
        )
        for record in records:
            connection.execute(
                "INSERT INTO records(source_id, provider_id, entity_kind) VALUES (?, ?, ?) "
                "ON CONFLICT(source_id, provider_id) DO UPDATE SET "
                "entity_kind = excluded.entity_kind",
                (source_id, record.provider_id, record.entity_kind),
            )
            record_id = int(
                connection.execute(
                    "SELECT id FROM records WHERE source_id = ? AND provider_id = ?",
                    (source_id, record.provider_id),
                ).fetchone()[0]
            )
            before = connection.total_changes
            connection.execute(
                "INSERT OR IGNORE INTO record_versions("
                "record_id, provider_version, content_hash, source_timestamp, payload_json"
                ") VALUES (?, ?, ?, ?, ?)",
                (
                    record_id,
                    record.provider_version,
                    record.content_hash,
                    record.source_timestamp,
                    json.dumps(record.payload, ensure_ascii=False, sort_keys=True),
                ),
            )
            persisted += connection.total_changes - before
            current_payload_json = connection.execute(
                "SELECT payload_json FROM record_versions WHERE record_id = ? "
                "ORDER BY source_timestamp DESC, id DESC LIMIT 1",
                (record_id,),
            ).fetchone()[0]
            current_payload = json.loads(str(current_payload_json))
            subjects = current_payload.get("subjects", [])
            searchable_subjects = (
                " ".join(str(item) for item in subjects)
                if isinstance(subjects, list | tuple)
                else str(subjects)
            )
            connection.execute("DELETE FROM record_search WHERE record_id = ?", (record_id,))
            connection.execute(
                "INSERT INTO record_search(record_id, title, abstract, subjects) "
                "VALUES (?, ?, ?, ?)",
                (
                    record_id,
                    str(current_payload.get("title", "")),
                    str(current_payload.get("abstract", "")),
                    searchable_subjects,
                ),
            )
        connection.execute(
            """
                INSERT INTO sync_state(
                    source_id, completed_watermark, in_progress_cursor, window_start, updated_at
                ) VALUES (?, ?, NULL, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(source_id) DO UPDATE SET
                    completed_watermark = CASE
                        WHEN sync_state.completed_watermark IS NULL
                          OR excluded.completed_watermark > sync_state.completed_watermark
                        THEN excluded.completed_watermark
                        ELSE sync_state.completed_watermark
                    END,
                    in_progress_cursor = NULL,
                    window_start = CASE
                        WHEN sync_state.completed_watermark IS NULL
                          OR excluded.completed_watermark > sync_state.completed_watermark
                        THEN excluded.window_start
                        ELSE sync_state.window_start
                    END,
                    updated_at = CURRENT_TIMESTAMP
                """,
            (source_id, window_end, window_start),
        )
    return persisted


def database_health() -> DatabaseHealth:
    """Check that the shared store can be read and written without exposing content."""
    with open_database() as connection:
        journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        busy_timeout_ms = int(connection.execute("PRAGMA busy_timeout").fetchone()[0])
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("ROLLBACK")
        connection.execute("SELECT 1").fetchone()
    return DatabaseHealth(
        journal_mode=journal_mode,
        busy_timeout_ms=busy_timeout_ms,
        readable=True,
        writable=True,
    )
