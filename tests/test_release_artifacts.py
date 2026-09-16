"""Acceptance tests for native client artifacts, enabled by release builds."""

from __future__ import annotations

import os
import shutil
import stat
import zipfile
from pathlib import Path
from typing import Any

import pytest
from mcp import ClientSession, StdioServerParameters, stdio_client

from policy_mcp import __version__
from policy_mcp.profiles import Profile

PACKAGED_ROOT = os.environ.get("SOURCEBOOK_TEST_PACKAGES")
NATIVE_BINARY = os.environ.get("SOURCEBOOK_TEST_BINARY")
TARGET = os.environ.get("SOURCEBOOK_TEST_TARGET", "darwin-arm64")
pytestmark = [
    pytest.mark.release_artifact,
    pytest.mark.skipif(
        not PACKAGED_ROOT or not NATIVE_BINARY,
        reason="release artifacts were not supplied",
    ),
]


async def capture_contract(
    command: Path,
    profile: Profile,
    data_directory: Path,
) -> dict[str, Any]:
    parameters = StdioServerParameters(
        command=str(command),
        args=["serve", "--profile", profile.value],
        env={"POLICY_MCP_DATA_DIR": str(data_directory)},
    )
    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        initialized = await session.initialize()
        tools = await session.list_tools()
        result = await session.call_tool("policy_diagnostic", {})
    return {
        "server": initialized.server_info.model_dump(by_alias=True, exclude_none=True),
        "tools": [tool.model_dump(by_alias=True, exclude_none=True) for tool in tools.tools],
        "result": result.model_dump(by_alias=True, exclude_none=True),
    }


def package_binaries(packages: Path, profile: Profile, extracted: Path) -> list[Path]:
    binary_name = "policy-mcp.exe" if TARGET == "windows-x64" else "policy-mcp"
    candidates = [
        packages / "claude-code-plugin" / "policy-research" / "bin" / binary_name,
        packages / "openai-agent-plugin" / "policy-research" / "bin" / binary_name,
    ]
    bundle = (
        packages
        / "claude-desktop"
        / f"{profile.server_name}-{__version__}-{TARGET}.mcpb"
    )
    destination = extracted / profile.value
    with zipfile.ZipFile(bundle) as archive:
        archive.extractall(destination)
    bundled_binary = destination / "server" / binary_name
    bundled_binary.chmod(0o555)
    candidates.append(bundled_binary)
    return candidates


@pytest.mark.parametrize("profile", list(Profile))
async def test_client_artifacts_preserve_the_direct_mcp_contract(
    profile: Profile,
    tmp_path: Path,
) -> None:
    assert PACKAGED_ROOT is not None
    assert NATIVE_BINARY is not None
    packages = Path(PACKAGED_ROOT)
    direct_binary = Path(NATIVE_BINARY)
    data_directory = tmp_path / "shared user data"
    baseline = await capture_contract(direct_binary, profile, data_directory)

    read_only_root = tmp_path / "read only package path"
    shutil.copytree(packages, read_only_root)
    extracted = tmp_path / "extracted bundles"
    candidates = package_binaries(read_only_root, profile, extracted)
    for candidate in candidates:
        candidate.chmod(stat.S_IRUSR | stat.S_IXUSR)

    for candidate in candidates:
        assert await capture_contract(candidate, profile, data_directory) == baseline


def test_package_replacement_does_not_remove_shared_data(tmp_path: Path) -> None:
    assert PACKAGED_ROOT is not None
    package_copy = tmp_path / "disposable package"
    shared_data = tmp_path / "persistent user data"
    shutil.copytree(Path(PACKAGED_ROOT), package_copy)
    shared_data.mkdir()
    database = shared_data / "sourcebook.sqlite3"
    database.write_bytes(b"preserved")

    shutil.rmtree(package_copy)

    assert database.read_bytes() == b"preserved"


def test_manifests_do_not_contain_credentials() -> None:
    assert PACKAGED_ROOT is not None
    forbidden = (
        "seeded-test-secret",
        "DIP_API_KEY",
        "LOBBYREGISTER_API_KEY",
        "GENESIS_TOKEN",
        "EURLEX_PASSWORD",
    )
    for path in Path(PACKAGED_ROOT).rglob("*"):
        if path.is_file() and path.suffix in {".json", ".mcpb"}:
            content = path.read_bytes()
            for value in forbidden:
                assert value.encode() not in content, f"Found credential material in {path}"
