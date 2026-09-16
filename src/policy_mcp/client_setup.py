"""Register the local executable with supported command-line MCP clients."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from policy_mcp.profiles import Profile

SetupClient = Literal["claude-code", "codex-cli"]
SETUP_CLIENTS: tuple[SetupClient, ...] = ("claude-code", "codex-cli")


@dataclass(frozen=True)
class ClientSetupStep:
    """One host command used to register a profile."""

    profile: str
    command: list[str]
    status: Literal["planned", "installed", "error"]
    detail: str


@dataclass(frozen=True)
class ClientSetupReport:
    """Outcome of registering every Sourcebook profile with one client."""

    client: SetupClient
    status: Literal["planned", "ok", "error"]
    executable: str
    steps: list[ClientSetupStep]

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-ready representation."""
        return asdict(self)


def registration_command(
    client: SetupClient,
    client_executable: str,
    server_executable: Path,
    profile: Profile,
) -> list[str]:
    """Build one argument-safe MCP registration command."""
    server = str(server_executable.resolve())
    if client == "claude-code":
        return [
            client_executable,
            "mcp",
            "add",
            "--transport",
            "stdio",
            "--scope",
            "user",
            profile.server_name,
            "--",
            server,
            "serve",
            "--profile",
            profile.value,
        ]
    return [
        client_executable,
        "mcp",
        "add",
        profile.server_name,
        "--",
        server,
        "serve",
        "--profile",
        profile.value,
    ]


def removal_command(
    client: SetupClient,
    client_executable: str,
    profile: Profile,
) -> list[str]:
    """Build the exact command that removes one prior Sourcebook registration."""
    if client == "claude-code":
        return [
            client_executable,
            "mcp",
            "remove",
            "--scope",
            "user",
            profile.server_name,
        ]
    return [client_executable, "mcp", "remove", profile.server_name]


def setup_client(
    client: SetupClient,
    server_executable: Path,
    *,
    dry_run: bool = False,
) -> ClientSetupReport:
    """Replace and register all profiles, stopping after the first add failure."""
    if not server_executable.is_file():
        return ClientSetupReport(
            client=client,
            status="error",
            executable=str(server_executable),
            steps=[
                ClientSetupStep(
                    profile="executable",
                    command=[],
                    status="error",
                    detail=f"Sourcebook executable was not found: {server_executable}",
                )
            ],
        )

    command_name = "claude" if client == "claude-code" else "codex"
    client_executable = shutil.which(command_name)
    if client_executable is None:
        return ClientSetupReport(
            client=client,
            status="error",
            executable=str(server_executable.resolve()),
            steps=[
                ClientSetupStep(
                    profile="client",
                    command=[command_name],
                    status="error",
                    detail=f"{command_name} was not found on PATH",
                )
            ],
        )

    steps: list[ClientSetupStep] = []
    for profile in Profile:
        command = registration_command(
            client,
            client_executable,
            server_executable,
            profile,
        )
        if dry_run:
            steps.append(
                ClientSetupStep(
                    profile=profile.value,
                    command=command,
                    status="planned",
                    detail="Registration command was not run",
                )
            )
            continue

        subprocess.run(
            removal_command(client, client_executable, profile),
            check=False,
            capture_output=True,
            text=True,
        )
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "Command failed"
            steps.append(
                ClientSetupStep(
                    profile=profile.value,
                    command=command,
                    status="error",
                    detail=detail,
                )
            )
            return ClientSetupReport(
                client=client,
                status="error",
                executable=str(server_executable.resolve()),
                steps=steps,
            )
        steps.append(
            ClientSetupStep(
                profile=profile.value,
                command=command,
                status="installed",
                detail=f"Registered {profile.server_name}",
            )
        )

    return ClientSetupReport(
        client=client,
        status="planned" if dry_run else "ok",
        executable=str(server_executable.resolve()),
        steps=steps,
    )
