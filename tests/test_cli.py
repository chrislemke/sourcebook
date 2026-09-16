"""Tests for the project command-line entry point."""

import stat
from pathlib import Path

import pytest

from policy_mcp import __version__
from policy_mcp.cli import build_parser, main


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        main(["--version"])

    assert error.value.code == 0
    assert capsys.readouterr().out == f"policy-mcp {__version__}\n"


def test_serve_requires_a_profile() -> None:
    parser = build_parser()

    with pytest.raises(SystemExit) as error:
        parser.parse_args(["serve"])

    assert error.value.code == 2


def test_serve_accepts_each_profile() -> None:
    parser = build_parser()

    for profile in ("legislation", "actors", "evidence"):
        args = parser.parse_args(["serve", "--profile", profile])
        assert args.profile == profile


def test_package_command_builds_artifacts(tmp_path: Path) -> None:
    binary = tmp_path / "policy-mcp"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    output = tmp_path / "release"

    assert (
        main(
            [
                "package",
                "--binary",
                str(binary),
                "--output",
                str(output),
                "--target",
                "darwin-arm64",
            ]
        )
        == 0
    )

    assert (output / "claude-desktop" / "policy-legislation-0.1.0-darwin-arm64.mcpb").is_file()
