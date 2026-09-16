"""Operator-facing backup, restore, and route-health services."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from policy_mcp.registry import RouteState, SourceRegistry
from policy_mcp.storage import (
    DATABASE_NAME,
    data_directory,
    database_ingestion_lock,
    open_database,
)

DOCUMENTS_DIRECTORY_NAME = "documents"
BACKUP_MANIFEST_NAME = "manifest.json"
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class BackupVerificationError(ValueError):
    """Raised when a backup cannot be trusted for restoration."""


class BackupFile(BaseModel):
    """One immutable file recorded in a backup manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: Annotated[str, Field(min_length=1)]
    sha256: Sha256
    size: Annotated[int, Field(ge=0)]


class BackupManifest(BaseModel):
    """Versioned integrity manifest for a complete local-state backup."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    backup_version: Literal[1]
    files: tuple[BackupFile, ...]


@dataclass(frozen=True)
class RouteHealth:
    """One route's state without collapsing distinct failure classes."""

    source_id: str
    route_id: str
    state: RouteState
    detail: str | None = None


@dataclass(frozen=True)
class RouteHealthSummary:
    """Counts and route-level details for operator diagnostics."""

    total_routes: int
    counts: dict[RouteState, int]
    routes: tuple[RouteHealth, ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_entry(root: Path, path: Path) -> BackupFile:
    relative = path.relative_to(root).as_posix()
    return BackupFile(path=relative, sha256=_sha256(path), size=path.stat().st_size)


def _prepare_empty_destination(destination: Path) -> None:
    if destination.is_symlink() or (destination.exists() and not destination.is_dir()):
        raise FileExistsError(f"Backup destination is not an empty directory: {destination}")
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f"Backup destination is non-empty: {destination}")


def backup_state(destination: Path) -> BackupManifest:
    """Checkpoint SQLite and atomically back up it and immutable documents."""
    source_root = data_directory().resolve()
    destination = destination.resolve()
    if destination == source_root or source_root in destination.parents:
        raise ValueError("Backup destination must be outside the live data directory")
    _prepare_empty_destination(destination)
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}-backup-", dir=destination.parent))
    try:
        with database_ingestion_lock(source_root), open_database() as source:
            checkpoint = source.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if checkpoint is None or int(checkpoint[0]) != 0:
                raise RuntimeError("SQLite checkpoint could not complete")
            backup_database = staging / DATABASE_NAME
            with sqlite3.connect(backup_database) as target:
                source.backup(target)

            documents_root = source_root / DOCUMENTS_DIRECTORY_NAME
            if documents_root.exists():
                if documents_root.is_symlink() or not documents_root.is_dir():
                    raise RuntimeError("Document store is not a regular directory")
                backup_documents = staging / DOCUMENTS_DIRECTORY_NAME
                for document in sorted(documents_root.iterdir(), key=lambda path: path.name):
                    if document.is_symlink() or not document.is_file():
                        raise RuntimeError(f"Unexpected document-store entry: {document.name}")
                    digest = _sha256(document)
                    if document.name != digest:
                        raise RuntimeError(
                            f"Document-store entry is not content-addressed: {document.name}"
                        )
                    backup_documents.mkdir(mode=0o700, exist_ok=True)
                    shutil.copyfile(document, backup_documents / document.name)

        backed_up_files = sorted(
            (
                path
                for path in staging.rglob("*")
                if path.is_file() and path.name != BACKUP_MANIFEST_NAME
            ),
            key=lambda path: path.relative_to(staging).as_posix(),
        )
        manifest = BackupManifest(
            backup_version=1,
            files=tuple(_manifest_entry(staging, path) for path in backed_up_files),
        )
        (staging / BACKUP_MANIFEST_NAME).write_text(
            json.dumps(manifest.model_dump(mode="json"), indent=2) + "\n"
        )
        if destination.exists():
            destination.rmdir()
        staging.rename(destination)
        return manifest
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _safe_manifest_path(root: Path, value: str) -> Path:
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or not relative.parts
        or ".." in relative.parts
        or "\\" in value
        or ":" in value
    ):
        raise BackupVerificationError(f"Unsafe backup path: {value}")
    candidate = root.joinpath(*relative.parts)
    if candidate.is_symlink():
        raise BackupVerificationError(f"Backup entry must not be a symlink: {value}")
    resolved = candidate.resolve()
    if root != resolved and root not in resolved.parents:
        raise BackupVerificationError(f"Backup path leaves its root: {value}")
    return resolved


def verify_backup(path: Path) -> BackupManifest:
    """Verify manifest shape, file set, hashes, and SQLite integrity."""
    root = path.resolve()
    manifest_path = root / BACKUP_MANIFEST_NAME
    try:
        manifest = BackupManifest.model_validate_json(manifest_path.read_text())
    except (OSError, ValidationError) as error:
        raise BackupVerificationError(f"Invalid backup manifest: {error}") from error

    paths = [entry.path for entry in manifest.files]
    if len(paths) != len(set(paths)):
        raise BackupVerificationError("Backup manifest contains duplicate paths")
    if DATABASE_NAME not in paths:
        raise BackupVerificationError(f"Backup manifest does not contain {DATABASE_NAME}")

    expected_files = {BACKUP_MANIFEST_NAME, *paths}
    try:
        actual_files = {
            file.relative_to(root).as_posix()
            for file in root.rglob("*")
            if file.is_file() or file.is_symlink()
        }
    except OSError as error:
        raise BackupVerificationError(f"Could not inspect backup: {error}") from error
    if actual_files != expected_files:
        missing = sorted(expected_files - actual_files)
        unexpected = sorted(actual_files - expected_files)
        raise BackupVerificationError(
            f"Backup file set mismatch; missing={missing}, unexpected={unexpected}"
        )

    for entry in manifest.files:
        candidate = _safe_manifest_path(root, entry.path)
        if not candidate.is_file():
            raise BackupVerificationError(f"Missing backup file: {entry.path}")
        if _sha256(candidate) != entry.sha256:
            raise BackupVerificationError(f"Hash mismatch for backup file: {entry.path}")
        if candidate.stat().st_size != entry.size:
            raise BackupVerificationError(f"Size mismatch for backup file: {entry.path}")
        relative = PurePosixPath(entry.path)
        if relative.parts[0] == DOCUMENTS_DIRECTORY_NAME:
            if len(relative.parts) != 2 or relative.name != entry.sha256:
                raise BackupVerificationError(
                    f"Document backup path is not content-addressed: {entry.path}"
                )
        elif entry.path != DATABASE_NAME:
            raise BackupVerificationError(f"Unsupported backup file: {entry.path}")

    database = root / DATABASE_NAME
    try:
        uri = f"{database.resolve().as_uri()}?mode=ro&immutable=1"
        with sqlite3.connect(uri, uri=True) as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.Error as error:
        raise BackupVerificationError(f"Backup database is invalid: {error}") from error
    if integrity != ("ok",):
        raise BackupVerificationError(f"Backup database failed integrity check: {integrity}")
    return manifest


def _destination_is_nonempty(destination: Path) -> bool:
    return destination.exists() and any(destination.iterdir())


def restore_state(path: Path, destination: Path, *, replace: bool = False) -> Path:
    """Verify then atomically restore local state through a staging directory."""
    manifest = verify_backup(path)
    source = path.resolve()
    destination = destination.resolve()
    if destination.is_symlink() or (destination.exists() and not destination.is_dir()):
        raise FileExistsError(f"Restore destination is not a directory: {destination}")
    if _destination_is_nonempty(destination) and not replace:
        raise FileExistsError(f"Restore destination is non-empty: {destination}")

    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}-restore-", dir=destination.parent))
    rollback: Path | None = None
    try:
        for entry in manifest.files:
            source_file = _safe_manifest_path(source, entry.path)
            restored_file = staging.joinpath(*PurePosixPath(entry.path).parts)
            restored_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            shutil.copyfile(source_file, restored_file)
            if _sha256(restored_file) != entry.sha256:
                raise BackupVerificationError(f"Restored file hash mismatch: {entry.path}")

        if destination.exists():
            if _destination_is_nonempty(destination):
                rollback = destination.with_name(f".{destination.name}-rollback-{uuid.uuid4().hex}")
                destination.rename(rollback)
            else:
                destination.rmdir()
        staging.rename(destination)
        if rollback is not None:
            shutil.rmtree(rollback)
        return destination
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        if rollback is not None and rollback.exists() and not destination.exists():
            rollback.rename(destination)
        raise


def summarize_route_health(registry: SourceRegistry) -> RouteHealthSummary:
    """Summarize route states without treating operational failures as no matches."""
    issue_details = {
        (issue.source_id, issue.route_id): issue.detail
        for issue in registry.issues
        if issue.route_id is not None
    }
    routes = tuple(
        RouteHealth(
            source_id=registration.source_id,
            route_id=registration.route_id,
            state=registration.state,
            detail=issue_details.get((registration.source_id, registration.route_id)),
        )
        for _, registration in sorted(registry.registrations.items())
    )
    counts: dict[RouteState, int] = {}
    for route in routes:
        counts[route.state] = counts.get(route.state, 0) + 1
    return RouteHealthSummary(total_routes=len(routes), counts=counts, routes=routes)
