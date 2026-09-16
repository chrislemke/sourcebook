# Sourcebook

Local, read-only MCP servers for traceable research across German federal and EU public sources. The implementation follows the repository's implementation plan and is split into legislation, actors, and evidence profiles.

## Development setup

The project targets Python 3.12 and uses uv for Python installation, dependency resolution, and command execution.

```bash
uv sync
uv run policy-mcp --version
```

Run the local quality checks with:

```bash
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
```

Use `uv build` to verify the Python package. The commands below build the self-contained client executable and plugin artifacts.

## Local MCP runtime

Start one profile over `stdio`:

```bash
uv run policy-mcp serve --profile legislation
uv run policy-mcp serve --profile actors
uv run policy-mcp serve --profile evidence
```

The legislation profile exposes six task-oriented tools, the actor profile four, and the evidence profile five. All are read-only. No live source workers are bound yet, so the production server fails closed with `not_configured` source states; deterministic frozen catalogs are used only by acceptance tests. Set `POLICY_MCP_DATA_DIR` only for development or tests; normal runs use the operating system's user-data directory.

Run operator checks or store an upstream credential with:

```bash
uv run policy-mcp doctor
uv run policy-mcp doctor --client codex-cli
uv run policy-mcp configure --credential DIP_API_KEY
uv run policy-mcp verify-schemas
uv run policy-mcp route-health
uv run policy-mcp measure-tool-tokens --profile legislation
```

`doctor` never reads or prints credential values. `configure` writes the prompted value to the operating system credential store.

## Client packages

Build a native executable, then generate all package families from that one binary:

```bash
PYINSTALLER_CONFIG_DIR=/tmp/sourcebook-pyinstaller uv run pyinstaller --noconfirm --clean policy-mcp.spec
uv run policy-mcp package --binary dist/policy-mcp --output dist/packages --target darwin-arm64
```

The package command creates three Claude Desktop MCPBs, one Claude Code plugin, one portable OpenAI Agent Plugin, and local marketplace trees. See [docs/packaging.md](docs/packaging.md) for validation and installation details.

Backup, staged restore, bounded backfill gates, routing evaluation, and route-state interpretation are documented in [docs/operations.md](docs/operations.md).

## Current status

The local runtime now provides stable legislation, actor, and evidence contracts; durable opaque references; bounded response envelopes; a versioned SQLite/FTS store; content-addressed documents; strict source registry and networking policy; DIP, EP/CELLAR, Bundestag-record, GENESIS, and GovData adapter contracts; and operator backup, restore, routing-evaluation, and health commands. Frozen MCP fixtures verify complete search-to-evidence paths without network access.

Live source activation and worker binding remain. The registry currently reports routes as `not_configured` until credentials, current schema fixtures, distribution URLs, and low-volume live checks have passed. Signed macOS and Windows release checks, plus the Claude Desktop and ChatGPT Desktop installation dialogs, still require release credentials or interactive host validation.
