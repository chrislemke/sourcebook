"""Shared local storage used by every policy-mcp profile."""

from __future__ import annotations

import os
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_path

DATA_DIR_ENV = "POLICY_MCP_DATA_DIR"
DATABASE_NAME = "sourcebook.sqlite3"
BUSY_TIMEOUT_MS = 5_000
INITIALIZATION_LOCK_NAME = ".database-init.lock"


@dataclass(frozen=True)
class DatabaseHealth:
    """Small, serializable report for the diagnostic tool and doctor command."""

    journal_mode: str
    busy_timeout_ms: int
    readable: bool
    writable: bool


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
        connection.commit()
    return connection


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
