"""Command-line entry point for policy-mcp."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from policy_mcp import __version__
from policy_mcp.diagnostics import CLIENT_NAMES, CREDENTIAL_NAMES, run_doctor, store_credential
from policy_mcp.evaluation import RoutingDecision, load_corpus, run_evaluation
from policy_mcp.operations import (
    backup_state,
    restore_state,
    summarize_route_health,
    verify_backup,
)
from policy_mcp.packaging import TARGET_PLATFORMS, build_packages
from policy_mcp.profiles import Profile
from policy_mcp.registry import RouteState, load_registry
from policy_mcp.resources import bundled_resource
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
    verify = subparsers.add_parser("verify-schemas", help="Validate the source registry.")
    verify.add_argument(
        "--registry",
        type=Path,
        default=bundled_resource("sources.yaml", Path("config/sources.yaml")),
    )
    health = subparsers.add_parser("route-health", help="Report each registered route state.")
    health.add_argument(
        "--registry",
        type=Path,
        default=bundled_resource("sources.yaml", Path("config/sources.yaml")),
    )
    sync = subparsers.add_parser("sync", help="Run one configured incremental source sync.")
    sync.add_argument("--source", required=True)
    sync.add_argument(
        "--registry",
        type=Path,
        default=bundled_resource("sources.yaml", Path("config/sources.yaml")),
    )
    backfill = subparsers.add_parser("backfill", help="Run one bounded source backfill.")
    backfill.add_argument("--source", required=True)
    backfill.add_argument("--from-date", required=True)
    backfill.add_argument("--to-date", required=True)
    backfill.add_argument(
        "--registry",
        type=Path,
        default=bundled_resource("sources.yaml", Path("config/sources.yaml")),
    )
    backup = subparsers.add_parser("backup", help="Back up local metadata and documents.")
    backup.add_argument("--output", type=Path, required=True)
    restore = subparsers.add_parser("restore", help="Verify and restore a local-state backup.")
    restore.add_argument("--input", type=Path, required=True)
    restore.add_argument("--destination", type=Path, required=True)
    restore.add_argument("--replace", action="store_true")
    restore.add_argument("--verify-only", action="store_true")
    evaluate = subparsers.add_parser(
        "evaluate-routing", help="Score deterministic routing decisions."
    )
    evaluate.add_argument(
        "--corpus",
        type=Path,
        default=bundled_resource("routing-v1.json", Path("evals/routing-v1.json")),
    )
    evaluate.add_argument("--decisions", type=Path, required=True)
    measure = subparsers.add_parser(
        "measure-tool-tokens", help="Measure host-visible MCP tool schemas."
    )
    measure.add_argument("--profile", choices=[profile.value for profile in Profile], required=True)
    return parser


def _source_not_ready(registry_path: Path, source_id: str) -> tuple[bool, dict[str, object]]:
    registry = load_registry(registry_path)
    source = registry.sources.get(source_id)
    if source is None:
        return True, {"status": "unsupported", "source": source_id}
    states = [route.state for route in source.routes.values()]
    ready = any(state is RouteState.HEALTHY for state in states)
    return not ready, {
        "status": "ready" if ready else "not_configured",
        "source": source_id,
        "routes": {route_id: route.state.value for route_id, route in source.routes.items()},
    }


async def _tool_measurement(profile: str) -> dict[str, object]:
    tools = await create_server(profile).list_tools()
    serialized = json.dumps(
        [tool.model_dump(by_alias=True, exclude_none=True) for tool in tools],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return {
        "profile": profile,
        "tools": [tool.name for tool in tools],
        "schema_bytes": len(serialized),
        "estimated_tokens": (len(serialized) + 3) // 4,
    }


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
    elif args.command == "verify-schemas":
        registry = load_registry(args.registry)
        print(
            json.dumps(
                {
                    "registry_version": registry.registry_version,
                    "issues": [issue.model_dump(mode="json") for issue in registry.issues],
                }
            )
        )
        return 1 if registry.issues else 0
    elif args.command == "route-health":
        summary = summarize_route_health(load_registry(args.registry))
        print(
            json.dumps(
                {
                    "total_routes": summary.total_routes,
                    "counts": {state.value: count for state, count in summary.counts.items()},
                    "routes": [
                        {
                            "source": route.source_id,
                            "route": route.route_id,
                            "state": route.state.value,
                            "detail": route.detail,
                        }
                        for route in summary.routes
                    ],
                }
            )
        )
    elif args.command in {"sync", "backfill"}:
        if args.command == "backfill":
            start = date.fromisoformat(args.from_date)
            end = date.fromisoformat(args.to_date)
            if start > end:
                raise ValueError("--from-date must not be after --to-date")
        blocked, report = _source_not_ready(args.registry, args.source)
        if not blocked:
            report["status"] = "not_configured"
            report["detail"] = "The route passed its registry gate but has no bound sync worker."
            blocked = True
        print(json.dumps(report))
        return 2 if blocked else 0
    elif args.command == "backup":
        manifest = backup_state(args.output)
        print(manifest.model_dump_json())
    elif args.command == "restore":
        if args.verify_only:
            manifest = verify_backup(args.input)
            print(manifest.model_dump_json())
        else:
            restored = restore_state(args.input, args.destination, replace=args.replace)
            print(json.dumps({"status": "restored", "destination": str(restored)}))
    elif args.command == "evaluate-routing":
        corpus = load_corpus(args.corpus)
        raw = json.loads(args.decisions.read_text())
        decisions = {key: RoutingDecision.model_validate(value) for key, value in raw.items()}
        report = run_evaluation(corpus, decisions)
        print(report.model_dump_json())
        return 0 if report.release_gate_passed else 1
    elif args.command == "measure-tool-tokens":
        print(json.dumps(asyncio.run(_tool_measurement(args.profile))))
    return 0
