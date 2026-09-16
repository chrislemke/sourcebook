"""Operator diagnostics and OS credential-store configuration."""

from __future__ import annotations

import shutil
import sqlite3
import sys
from dataclasses import asdict, dataclass
from getpass import getpass
from pathlib import Path
from typing import Literal

import keyring

from policy_mcp.storage import data_directory, database_health

CredentialName = Literal[
    "DIP_API_KEY",
    "LOBBYREGISTER_API_KEY",
    "GENESIS_TOKEN",
    "EURLEX_USERNAME",
    "EURLEX_PASSWORD",
]
ClientName = Literal["claude-desktop", "claude-code", "chatgpt-desktop", "codex-cli"]
CREDENTIAL_NAMES: tuple[CredentialName, ...] = (
    "DIP_API_KEY",
    "LOBBYREGISTER_API_KEY",
    "GENESIS_TOKEN",
    "EURLEX_USERNAME",
    "EURLEX_PASSWORD",
)
CLIENT_NAMES: tuple[ClientName, ...] = (
    "claude-desktop",
    "claude-code",
    "chatgpt-desktop",
    "codex-cli",
)
CREDENTIAL_SERVICE = "sourcebook"


@dataclass(frozen=True)
class DoctorCheck:
    """One health check without sensitive values."""

    name: str
    status: Literal["ok", "warning", "error"]
    detail: str


@dataclass(frozen=True)
class DoctorReport:
    """Complete operator health report."""

    status: Literal["ok", "error"]
    checks: list[DoctorCheck]

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-ready representation."""
        return asdict(self)


def store_credential(name: CredentialName) -> None:
    """Prompt for one credential and write it to the OS credential store."""
    value = getpass(f"{name}: ")
    if not value:
        raise ValueError(f"{name} cannot be empty")
    keyring.set_password(CREDENTIAL_SERVICE, name, value)


def _client_executable(client: ClientName) -> Path | None:
    if client == "claude-code":
        found = shutil.which("claude")
        return Path(found) if found else None
    if client == "codex-cli":
        found = shutil.which("codex")
        return Path(found) if found else None
    if sys.platform == "darwin":
        app = "Claude.app" if client == "claude-desktop" else "ChatGPT.app"
        path = Path("/Applications") / app
        return path if path.exists() else None
    return None


def _registration_files(client: ClientName) -> tuple[Path, ...]:
    home = Path.home()
    if client == "claude-desktop":
        if sys.platform == "darwin":
            return (home / "Library/Application Support/Claude/claude_desktop_config.json",)
        return (home / "AppData/Roaming/Claude/claude_desktop_config.json",)
    if client == "claude-code":
        return (
            home / ".claude/plugins/installed_plugins.json",
            home / ".claude.json",
        )
    if client == "chatgpt-desktop":
        return (home / ".agents/plugins/marketplace.json",)
    return (
        home / ".agents/plugins/marketplace.json",
        home / ".codex/config.toml",
    )


def _has_registration(path: Path) -> bool:
    try:
        content = path.read_text(errors="replace")
    except OSError:
        return False
    return "policy-research" in content or "policy-legislation" in content


def run_doctor(client: ClientName | None = None) -> DoctorReport:
    """Check local runtime requirements without reading credential values."""
    checks: list[DoctorCheck] = []
    executable = Path(sys.argv[0]).resolve()
    checks.append(
        DoctorCheck(
            name="executable",
            status="ok" if executable.exists() else "error",
            detail="Executable is present" if executable.exists() else "Executable is missing",
        )
    )

    directory = data_directory()
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        checks.append(DoctorCheck("data_directory", "ok", f"Writable data directory: {directory}"))
    except OSError as error:
        checks.append(DoctorCheck("data_directory", "error", f"Data directory failed: {error}"))

    try:
        health = database_health()
        checks.append(
            DoctorCheck(
                "database",
                "ok",
                f"SQLite {health.journal_mode.upper()}, busy timeout {health.busy_timeout_ms} ms",
            )
        )
    except (OSError, sqlite3.Error, TimeoutError) as error:
        checks.append(DoctorCheck("database", "error", f"Database failed: {error}"))

    backend = keyring.get_keyring()
    priority = float(getattr(backend, "priority", 0))
    checks.append(
        DoctorCheck(
            "credential_store",
            "ok" if priority > 0 else "warning",
            f"Credential backend: {type(backend).__name__}",
        )
    )

    if client is not None:
        client_executable = _client_executable(client)
        checks.append(
            DoctorCheck(
                "client_executable",
                "ok" if client_executable else "error",
                f"{client} is installed" if client_executable else f"{client} was not found",
            )
        )
        registration = next(
            (path for path in _registration_files(client) if _has_registration(path)),
            None,
        )
        checks.append(
            DoctorCheck(
                "client_registration",
                "ok" if registration else "error",
                (
                    f"Sourcebook registration found in {registration}"
                    if registration
                    else "Sourcebook registration was not found"
                ),
            )
        )

    status: Literal["ok", "error"] = (
        "error" if any(check.status == "error" for check in checks) else "ok"
    )
    return DoctorReport(status=status, checks=checks)
