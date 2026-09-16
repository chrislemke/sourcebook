# Operations

Sourcebook starts from a failed-closed source registry. Research tools remain available so hosts can learn their stable contracts, but capability calls distinguish `not_configured`, `disabled`, `warming`, `schema_changed`, and `temporarily_unavailable` routes. An empty result never substitutes for one of those states. The current release does not bind live source workers, so changing registry state alone does not activate a route.

## Preflight

Run these commands from the locked environment before enabling or packaging a route:

```bash
uv run policy-mcp doctor
uv run policy-mcp verify-schemas
uv run policy-mcp route-health
uv run pytest
```

`verify-schemas` validates the local registry only. It is not a live-source check. Each route may move to `healthy` only after its documented schema, fixture hash, host allowlist, credential transport, pagination behavior, limits, and low-volume live check are current.

## Credentials

Store secrets with `policy-mcp configure --credential NAME`. The command writes through the operating-system credential store. Never put secrets in MCP arguments, registry files, URLs, fixture files, logs, or evaluation decisions. Rotate a credential by running the same command again, then run the source's low-volume authentication check before changing its registry state.

## Sync and backfill

Use `policy-mcp sync --source SOURCE` for an incremental run and `policy-mcp backfill --source SOURCE --from-date YYYY-MM-DD --to-date YYYY-MM-DD` for a bounded historical window. These commands currently stop with `not_configured` until a live worker is bound; they never perform a crawl from an MCP request. Watermarks advance only after an entire window persists, and only one ingestion writer may run at a time.

## Backup and restore

Create a verified snapshot outside the live data directory:

```bash
uv run policy-mcp backup --output /safe/path/sourcebook-backup
uv run policy-mcp restore --input /safe/path/sourcebook-backup --destination /staging/restore --verify-only
uv run policy-mcp restore --input /safe/path/sourcebook-backup --destination /staging/restore
```

Restore first to an empty staging directory. The restore command verifies the manifest, hashes, content-addressed document names, and SQLite integrity before copying. Use `--replace` only after separately preserving any destination data.

## Routing and release evidence

Evaluate a versioned decision file with `policy-mcp evaluate-routing --decisions decisions.json`. Measure the serialized host-visible tool surface with `policy-mcp measure-tool-tokens --profile PROFILE`. Release candidates must also pass formatting, lint, type checking, all frozen tests, package construction, and the platform-specific artifact suite described in [packaging.md](packaging.md). Signing, notarization, and interactive desktop-host checks remain human release gates.
