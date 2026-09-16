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

Each profile currently exposes the read-only `policy_diagnostic` tool. The tool checks the shared SQLite store without contacting an upstream source. Set `POLICY_MCP_DATA_DIR` only for development or tests; normal runs use the operating system's user-data directory.

Run operator checks or store an upstream credential with:

```bash
uv run policy-mcp doctor
uv run policy-mcp doctor --client codex-cli
uv run policy-mcp configure --credential DIP_API_KEY
```

`doctor` never reads or prints credential values. `configure` writes the prompted value to the operating system credential store.

## Client packages

Build a native executable, then generate all package families from that one binary:

```bash
PYINSTALLER_CONFIG_DIR=/tmp/sourcebook-pyinstaller uv run pyinstaller --noconfirm --clean policy-mcp.spec
uv run policy-mcp package --binary dist/policy-mcp --output dist/packages --target darwin-arm64
```

The package command creates three Claude Desktop MCPBs, one Claude Code plugin, one portable OpenAI Agent Plugin, and local marketplace trees. See [docs/packaging.md](docs/packaging.md) for validation and installation details.

## Current status

Milestone 0 has a working MCP runtime, package generator, native macOS arm64 proof build, and cross-package contract tests. Claude Code and Codex accepted their generated local plugins. Signed macOS and Windows release checks, plus the Claude Desktop and ChatGPT Desktop installation dialogs, still require release credentials or interactive host validation.

Source adapters and research tools begin in milestone 1 and are not implemented yet.
