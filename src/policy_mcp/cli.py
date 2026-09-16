"""Command-line entry point for policy-mcp."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import httpx

from policy_mcp import __version__
from policy_mcp.adapters.dip import DipClient, DipProviderError
from policy_mcp.client_setup import SETUP_CLIENTS, setup_client
from policy_mcp.diagnostics import (
    CLIENT_NAMES,
    CREDENTIAL_NAMES,
    load_credential,
    run_doctor,
    store_credential,
)
from policy_mcp.evaluation import RoutingDecision, load_corpus, run_evaluation
from policy_mcp.ingestion import sync_dip_window
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
from policy_mcp.storage import open_database


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
    setup = subparsers.add_parser(
        "setup-client",
        help="Register all three servers with Claude Code or Codex CLI.",
    )
    setup.add_argument("--client", choices=SETUP_CLIENTS, required=True)
    setup.add_argument(
        "--executable",
        type=Path,
        default=None,
        help="Sourcebook executable to register (defaults to this executable).",
    )
    setup.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the registration plan without changing client settings.",
    )
    setup.add_argument("--format", choices=("text", "json"), default="text")
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


def _dip_incremental_start(now: datetime) -> datetime:
    with open_database() as connection:
        row = connection.execute(
            "SELECT completed_watermark FROM sync_state WHERE source_id = 'dip'"
        ).fetchone()
    if row is None or row[0] is None:
        return now - timedelta(days=1)
    return datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))


async def _run_dip_sync(
    since: datetime,
    until: datetime,
    *,
    api_key: str | None = None,
) -> tuple[int, dict[str, object]]:
    api_key = api_key or load_credential("DIP_API_KEY")
    if api_key is None:
        return 2, {
            "status": "not_configured",
            "source": "dip",
            "detail": "Store DIP_API_KEY with policy-mcp configure before syncing.",
        }
    try:
        timeout = httpx.Timeout(30.0, connect=5.0)
        async with httpx.AsyncClient(timeout=timeout) as http:
            report = await sync_dip_window(
                DipClient(http, api_key=api_key),
                since=since,
                until=until,
                max_pages=10,
                max_records=250,
            )
    except (DipProviderError, httpx.HTTPError, OSError, RuntimeError) as error:
        return 2, {
            "status": "temporarily_unavailable",
            "source": "dip",
            "detail": str(error),
        }
    return 0, {"status": "ok", **report.__dict__}


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
    elif args.command == "setup-client":
        executable = args.executable or Path(sys.argv[0])
        report = setup_client(args.client, executable, dry_run=args.dry_run)
        if args.format == "json":
            print(json.dumps(report.as_dict(), indent=2))
        else:
            for step in report.steps:
                print(f"{step.status.upper():9} {step.profile}: {step.detail}")
            if report.status == "ok":
                print(f"DONE      {args.client}: restart the client, then run doctor")
        return 0 if report.status in {"ok", "planned"} else 1
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
        start: date | None = None
        end: date | None = None
        if args.command == "backfill":
            start = date.fromisoformat(args.from_date)
            end = date.fromisoformat(args.to_date)
            if start > end:
                raise ValueError("--from-date must not be after --to-date")
        if args.source == "dip":
            api_key = load_credential("DIP_API_KEY")
            if api_key is None:
                print(
                    json.dumps(
                        {
                            "status": "not_configured",
                            "source": "dip",
                            "detail": (
                                "Store DIP_API_KEY with policy-mcp configure before syncing."
                            ),
                        }
                    )
                )
                return 2
            now = datetime.now(UTC)
            if args.command == "backfill":
                assert start is not None and end is not None
                since = datetime.combine(start, time.min, tzinfo=UTC)
                until = datetime.combine(end, time.max, tzinfo=UTC)
            else:
                since = _dip_incremental_start(now)
                until = now
            exit_code, report = asyncio.run(_run_dip_sync(since, until, api_key=api_key))
            print(json.dumps(report))
            return exit_code
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
