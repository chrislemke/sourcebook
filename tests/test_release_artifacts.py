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
CAPABILITY_TOOLS = {
    Profile.LEGISLATION: "legislation_capabilities",
    Profile.ACTORS: "actor_capabilities",
    Profile.EVIDENCE: "evidence_capabilities",
}
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
        result = await session.call_tool(CAPABILITY_TOOLS[profile], {})
    return {
        "server": initialized.server_info.model_dump(by_alias=True, exclude_none=True),
        "tools": [tool.model_dump(by_alias=True, exclude_none=True) for tool in tools.tools],
        "result": result.model_dump(by_alias=True, exclude_none=True),
    }


def package_binaries(packages: Path, profile: Profile, extracted: Path) -> list[Path]:
    binary_name = "policy-mcp.exe" if TARGET == "windows-x64" else "policy-mcp"
    candidates = [
        packages / "bin" / binary_name,
        packages / "claude-code-plugin" / "policy-research" / "bin" / binary_name,
        packages / "openai-agent-plugin" / "policy-research" / "bin" / binary_name,
    ]
    bundle = packages / "claude-desktop" / f"{profile.server_name}-{__version__}-{TARGET}.mcpb"
    destination = extracted / profile.value
    with zipfile.ZipFile(bundle) as archive:
        archive.extractall(destination)
    bundled_binary = destination / "server" / binary_name
    bundled_binary.chmod(0o555)
    candidates.append(bundled_binary)
    return candidates


def make_tree_read_only(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_file():
            executable = path.name in {"policy-mcp", "policy-mcp.exe"}
            path.chmod(0o555 if executable else 0o444)
    for path in sorted(
        (path for path in root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        path.chmod(0o555)
    root.chmod(0o555)


def make_tree_writable(root: Path) -> None:
    root.chmod(0o755)
    for path in root.rglob("*"):
        if path.is_dir():
            path.chmod(0o755)


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
    make_tree_read_only(read_only_root)
    make_tree_read_only(extracted)
    try:
        assert not stat.S_IMODE(read_only_root.stat().st_mode) & stat.S_IWUSR
        assert not stat.S_IMODE(extracted.stat().st_mode) & stat.S_IWUSR
        for candidate in candidates:
            assert await capture_contract(candidate, profile, data_directory) == baseline
    finally:
        make_tree_writable(read_only_root)
        make_tree_writable(extracted)


def copy_artifact(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)


def remove_artifact(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def test_package_lifecycle_does_not_remove_shared_data_or_credentials(tmp_path: Path) -> None:
    assert PACKAGED_ROOT is not None
    packages = Path(PACKAGED_ROOT)
    shared_data = tmp_path / "persistent user data"
    shared_data.mkdir()
    database = shared_data / "sourcebook.sqlite3"
    database.write_bytes(b"preserved")
    external_credential_store = tmp_path / "operating system credential store"
    external_credential_store.write_bytes(b"credential remains outside packages")

    artifacts = [
        *sorted((packages / "claude-desktop").glob("*.mcpb")),
        packages / "claude-code-plugin" / "policy-research",
        packages / "openai-agent-plugin" / "policy-research",
    ]

    def assert_user_state() -> None:
        assert database.read_bytes() == b"preserved"
        assert external_credential_store.read_bytes() == (b"credential remains outside packages")

    for index, artifact in enumerate(artifacts):
        installed = tmp_path / "host packages" / str(index) / artifact.name
        copy_artifact(artifact, installed)  # fresh install
        assert_user_state()

        remove_artifact(installed)
        copy_artifact(artifact, installed)  # update/replacement
        assert_user_state()

        disabled = installed.with_name(f"{installed.name}.disabled")
        installed.rename(disabled)
        assert_user_state()
        disabled.rename(installed)  # re-enable
        assert_user_state()

        remove_artifact(installed)  # uninstall
        assert_user_state()


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
        if not path.is_file() or path.suffix not in {".json", ".mcpb"}:
            continue
        contents = {path.name: path.read_bytes()}
        if path.suffix == ".mcpb":
            with zipfile.ZipFile(path) as archive:
                contents = {member: archive.read(member) for member in archive.namelist()}
        for member, content in contents.items():
            for value in forbidden:
                assert value.encode() not in content, (
                    f"Found credential material in {path}:{member}"
                )
