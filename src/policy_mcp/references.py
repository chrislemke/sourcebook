"""Opaque in-memory references and stable search snapshot cursors."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from policy_mcp.storage import open_database

MAX_SNAPSHOT_ITEMS = 1_000


class ForgedReferenceError(LookupError):
    """A reference is unknown, belongs to another principal, or has the wrong kind."""


class ForgedCursorError(LookupError):
    """A cursor is unknown or is not bound to this principal and query."""


class ExpiredCursorError(LookupError):
    """A cursor existed but its snapshot has expired."""


@dataclass(frozen=True)
class CursorPage:
    keys: tuple[str, ...]
    cursor: str | None
    expires_at: datetime | None


class ReferenceStore(Protocol):
    """Storage contract for principal-bound opaque references and cursors."""

    principal: str

    def reference_for(self, *, principal: str, kind: str, key: str) -> str: ...

    def resolve(
        self,
        reference: str,
        *,
        principal: str,
        expected_kinds: Sequence[str],
    ) -> str: ...

    def first_page(
        self,
        keys: Sequence[str],
        *,
        principal: str,
        query_hash: str,
        limit: int,
    ) -> CursorPage: ...

    def next_page(
        self,
        cursor: str,
        *,
        principal: str,
        query_hash: str,
        limit: int,
    ) -> CursorPage: ...


@dataclass
class _Reference:
    principal: str
    kind: str
    key: str


@dataclass
class _Snapshot:
    principal: str
    query_hash: str
    keys: tuple[str, ...]
    position: int
    expires_at: datetime


class InMemoryReferenceStore:
    """Reference store used by frozen acceptance paths and unit deployments."""

    def __init__(
        self,
        *,
        principal: str,
        clock: Callable[[], datetime] | None = None,
        cursor_ttl: timedelta = timedelta(minutes=15),
    ) -> None:
        self.principal = principal
        self._clock = clock or (lambda: datetime.now(UTC))
        self._cursor_ttl = cursor_ttl
        self._references: dict[str, _Reference] = {}
        self._stable_references: dict[tuple[str, str, str], str] = {}
        self._snapshots: dict[str, _Snapshot] = {}

    def reference_for(self, *, principal: str, kind: str, key: str) -> str:
        """Return one stable opaque reference for a principal and entity."""
        stable_key = (principal, kind, key)
        existing = self._stable_references.get(stable_key)
        if existing is not None:
            return existing
        token = f"ref_{secrets.token_urlsafe(24)}"
        self._stable_references[stable_key] = token
        self._references[token] = _Reference(principal=principal, kind=kind, key=key)
        return token

    def resolve(
        self,
        reference: str,
        *,
        principal: str,
        expected_kinds: Sequence[str],
    ) -> str:
        """Resolve a reference only after principal and kind checks."""
        stored = self._references.get(reference)
        if stored is None or stored.principal != principal or stored.kind not in expected_kinds:
            raise ForgedReferenceError(reference)
        return stored.key

    def first_page(
        self,
        keys: Sequence[str],
        *,
        principal: str,
        query_hash: str,
        limit: int,
    ) -> CursorPage:
        """Create a stable snapshot and return its first page."""
        frozen = tuple(keys)
        if len(frozen) > MAX_SNAPSHOT_ITEMS:
            raise ValueError(f"Snapshot exceeds the {MAX_SNAPSHOT_ITEMS}-item limit")
        now = self._clock()
        self._snapshots = {
            token: snapshot
            for token, snapshot in self._snapshots.items()
            if snapshot.expires_at > now
        }
        page = frozen[:limit]
        if len(frozen) <= limit:
            return CursorPage(page, None, None)
        cursor = f"cur_{secrets.token_urlsafe(24)}"
        expires_at = now + self._cursor_ttl
        self._snapshots[cursor] = _Snapshot(
            principal=principal,
            query_hash=query_hash,
            keys=frozen,
            position=limit,
            expires_at=expires_at,
        )
        return CursorPage(page, cursor, expires_at)

    def next_page(
        self,
        cursor: str,
        *,
        principal: str,
        query_hash: str,
        limit: int,
    ) -> CursorPage:
        """Read the next page from a principal- and query-bound snapshot."""
        snapshot = self._snapshots.get(cursor)
        if snapshot is None or snapshot.principal != principal or snapshot.query_hash != query_hash:
            raise ForgedCursorError(cursor)
        if self._clock() >= snapshot.expires_at:
            del self._snapshots[cursor]
            raise ExpiredCursorError(cursor)
        start = snapshot.position
        end = min(start + limit, len(snapshot.keys))
        keys = snapshot.keys[start:end]
        snapshot.position = end
        if end == len(snapshot.keys):
            del self._snapshots[cursor]
            return CursorPage(keys, None, None)
        return CursorPage(keys, cursor, snapshot.expires_at)


class SQLiteReferenceStore:
    """Persistent opaque references and snapshot cursors for local clients."""

    def __init__(
        self,
        *,
        principal: str,
        clock: Callable[[], datetime] | None = None,
        cursor_ttl: timedelta = timedelta(minutes=15),
    ) -> None:
        self.principal = principal
        self._clock = clock or (lambda: datetime.now(UTC))
        self._cursor_ttl = cursor_ttl

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def _secret() -> bytes:
        with open_database() as connection:
            row = connection.execute(
                "SELECT value FROM store_metadata WHERE key = 'reference_secret'"
            ).fetchone()
            if row is None:
                value = secrets.token_hex(32)
                connection.execute(
                    "INSERT OR IGNORE INTO store_metadata(key, value) VALUES "
                    "('reference_secret', ?)",
                    (value,),
                )
                row = connection.execute(
                    "SELECT value FROM store_metadata WHERE key = 'reference_secret'"
                ).fetchone()
            return bytes.fromhex(str(row[0]))

    def reference_for(self, *, principal: str, kind: str, key: str) -> str:
        """Derive a stable opaque token and retain only its digest."""
        message = "\x00".join((principal, kind, key)).encode()
        signature = hmac.new(self._secret(), message, hashlib.sha256).digest()
        token = "ref_" + base64.urlsafe_b64encode(signature).decode().rstrip("=")
        with open_database() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO opaque_references(
                    token_digest, principal_id, entity_kind, entity_key
                ) VALUES (?, ?, ?, ?)
                """,
                (self._digest(token), principal, kind, key),
            )
        return token

    def resolve(
        self,
        reference: str,
        *,
        principal: str,
        expected_kinds: Sequence[str],
    ) -> str:
        """Resolve a token only for its bound local principal and entity kind."""
        with open_database() as connection:
            row = connection.execute(
                """
                SELECT entity_kind, entity_key FROM opaque_references
                WHERE token_digest = ? AND principal_id = ?
                """,
                (self._digest(reference), principal),
            ).fetchone()
        if row is None or str(row[0]) not in expected_kinds:
            raise ForgedReferenceError(reference)
        return str(row[1])

    def first_page(
        self,
        keys: Sequence[str],
        *,
        principal: str,
        query_hash: str,
        limit: int,
    ) -> CursorPage:
        """Persist an ordered snapshot and return its first page."""
        frozen = tuple(keys)
        if len(frozen) > MAX_SNAPSHOT_ITEMS:
            raise ValueError(f"Snapshot exceeds the {MAX_SNAPSHOT_ITEMS}-item limit")
        page = frozen[:limit]
        if len(frozen) <= limit:
            return CursorPage(page, None, None)
        cursor = f"cur_{secrets.token_urlsafe(24)}"
        digest = self._digest(cursor)
        expires_at = self._clock() + self._cursor_ttl
        with open_database() as connection:
            connection.execute(
                "DELETE FROM opaque_snapshots WHERE expires_at <= ?",
                (self._clock().isoformat(),),
            )
            connection.execute(
                "INSERT INTO opaque_snapshots("
                "token_digest, principal_id, query_hash, position, expires_at"
                ") VALUES (?, ?, ?, ?, ?)",
                (digest, principal, query_hash, limit, expires_at.isoformat()),
            )
            connection.executemany(
                "INSERT INTO opaque_snapshot_items(token_digest, ordinal, entity_key) "
                "VALUES (?, ?, ?)",
                [(digest, ordinal, key) for ordinal, key in enumerate(frozen)],
            )
        return CursorPage(page, cursor, expires_at)

    def next_page(
        self,
        cursor: str,
        *,
        principal: str,
        query_hash: str,
        limit: int,
    ) -> CursorPage:
        """Continue a stored snapshot without observing later index changes."""
        digest = self._digest(cursor)
        with open_database() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT position, expires_at FROM opaque_snapshots
                WHERE token_digest = ? AND principal_id = ? AND query_hash = ?
                """,
                (digest, principal, query_hash),
            ).fetchone()
            if row is None:
                raise ForgedCursorError(cursor)
            position = int(row[0])
            expires_at = datetime.fromisoformat(str(row[1]))
            if self._clock() >= expires_at:
                connection.execute("DELETE FROM opaque_snapshots WHERE token_digest = ?", (digest,))
                connection.commit()
                raise ExpiredCursorError(cursor)
            items = tuple(
                str(item[0])
                for item in connection.execute(
                    """
                    SELECT entity_key FROM opaque_snapshot_items
                    WHERE token_digest = ? AND ordinal >= ? AND ordinal < ?
                    ORDER BY ordinal
                    """,
                    (digest, position, position + limit),
                )
            )
            total = int(
                connection.execute(
                    "SELECT COUNT(*) FROM opaque_snapshot_items WHERE token_digest = ?",
                    (digest,),
                ).fetchone()[0]
            )
            next_position = position + len(items)
            if next_position >= total:
                connection.execute("DELETE FROM opaque_snapshots WHERE token_digest = ?", (digest,))
                return CursorPage(items, None, None)
            connection.execute(
                "UPDATE opaque_snapshots SET position = ? WHERE token_digest = ?",
                (next_position, digest),
            )
        return CursorPage(items, cursor, expires_at)
