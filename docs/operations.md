# Operations

Sourcebook starts from a failed-closed source registry. Research tools remain available so hosts can learn their stable contracts, but capability calls distinguish `not_configured`, `disabled`, `warming`, `schema_changed`, and `temporarily_unavailable` routes. An empty result never substitutes for one of those states. GovData catalogue search and the four actor sources (European Parliament, EU WhoisWho, Bundestag Lobbyregister, and EU Transparency Register) work interactively without user credentials. With a DIP API key, `legislation_search` and `legislation_procedure` query DIP live. The key comes from the `DIP_API_KEY` environment variable, which Claude Desktop and the Claude Code plugin set from the key entered at installation, or from the OS credential store. Without a key, DIP search uses a local index that the bounded sync worker fills. Changing registry state alone does not activate any other route.

## Preflight

Run these commands from the locked environment before enabling or packaging a route:

```bash
uv run policy-mcp doctor
uv run policy-mcp verify-schemas
uv run policy-mcp route-health
uv run pytest
```

`verify-schemas` validates the local registry only. It is not a live-source check. Each route may move to `healthy` only after its documented schema, fixture hash, host allowlist, credential transport, pagination behavior, limits, and low-volume live check are current.

`route-health` reports those release gates. MCP capability calls also check local runtime state, such as whether a credentialed DIP sync has placed validated records in the index. A registry route can therefore have a healthy contract while the corresponding local capability remains `not_configured`.

## Credentials

Store secrets with `policy-mcp configure --credential NAME`. The command writes through the operating-system credential store. Never put secrets in MCP arguments, registry files, URLs, fixture files, logs, or evaluation decisions. Rotate a credential by running the same command again, then run the source's low-volume authentication check before changing its registry state. Actor searches need no credential setup; when the Lobbyregister API requires a key, the adapter uses the Bundestag's public web search instead.

## Sync and backfill

Use `policy-mcp sync --source dip` for an incremental DIP run and `policy-mcp backfill --source dip --from-date YYYY-MM-DD --to-date YYYY-MM-DD` for a bounded historical window. Store `DIP_API_KEY` first. Sources without a bound worker stop with `not_configured`; no MCP request starts a background crawl. Actor sources are queried on demand. The EU Transparency Register snapshot is cached locally for 24 hours. DIP runs split a range into windows of at most six hours and halve a window until it holds no more than 250 changed procedures. Each window persists before its watermark advances, so an interrupted run resumes after the last completed window. Only one ingestion writer may run at a time. The DIP client sends at most one request per second, because DIP's bot protection challenges faster clients. A sync therefore takes about one second per changed procedure. If DIP still answers with a challenge, the run stops with a bot-protection message; wait several minutes before retrying.

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
