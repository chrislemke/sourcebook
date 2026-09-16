"""Command-line entry point for policy-mcp."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from policy_mcp import __version__
from policy_mcp.diagnostics import CLIENT_NAMES, CREDENTIAL_NAMES, run_doctor, store_credential
from policy_mcp.packaging import TARGET_PLATFORMS, build_packages
from policy_mcp.profiles import Profile
from policy_mcp.server import create_server


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        prog="policy-mcp",
        description="Local MCP servers for German federal and EU political research.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command")
    serve = subparsers.add_parser("serve", help="Run one local MCP server over stdio.")
    serve.add_argument(
        "--profile",
        choices=[profile.value for profile in Profile],
        required=True,
        help="Domain profile exposed by this process.",
    )
    package = subparsers.add_parser("package", help="Build native client packages.")
    package.add_argument("--binary", type=Path, required=True, help="Self-contained executable.")
    package.add_argument("--output", type=Path, required=True, help="Package output directory.")
    package.add_argument("--target", choices=sorted(TARGET_PLATFORMS), required=True)
    doctor = subparsers.add_parser("doctor", help="Check local runtime and client registration.")
    doctor.add_argument("--client", choices=CLIENT_NAMES)
    doctor.add_argument("--format", choices=("text", "json"), default="text")
    configure = subparsers.add_parser("configure", help="Store one upstream credential securely.")
    configure.add_argument("--credential", choices=CREDENTIAL_NAMES, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line entry point."""
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        create_server(args.profile).run(transport="stdio")
    elif args.command == "package":
        build_packages(args.binary, args.output, target=args.target)
    elif args.command == "doctor":
        report = run_doctor(args.client)
        if args.format == "json":
            print(json.dumps(report.as_dict(), indent=2))
        else:
            for check in report.checks:
                print(f"{check.status.upper():7} {check.name}: {check.detail}")
        return 0 if report.status == "ok" else 1
    elif args.command == "configure":
        store_credential(args.credential)
        print(f"Stored {args.credential} in the OS credential store.")
    return 0
