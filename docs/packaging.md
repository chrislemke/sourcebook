# Client packaging

The release process builds one native `policy-mcp` executable per target and copies that exact binary into every client package. Package metadata may differ by host, but MCP server names, tool definitions, annotations, and results must remain identical.

## Supported targets

The initial targets are:

- `darwin-arm64` for Apple Silicon Macs
- `windows-x64` for 64-bit Windows

PyInstaller builds for the operating system it runs on. Build the Windows executable on Windows and the macOS executable on Apple Silicon. The project does not cross-compile either target.

## Build and package

Install locked development dependencies and build the native executable:

```bash
uv sync --locked
PYINSTALLER_CONFIG_DIR=/tmp/sourcebook-pyinstaller uv run pyinstaller --noconfirm --clean policy-mcp.spec
```

Generate the packages for the current target:

```bash
uv run policy-mcp package \
  --binary dist/policy-mcp \
  --output dist/packages \
  --target darwin-arm64
```

Use `dist/policy-mcp.exe` and `--target windows-x64` on Windows.

The output contains:

```text
dist/packages/
  claude-desktop/*.mcpb
  claude-code-plugin/policy-research/
  openai-agent-plugin/policy-research/
  marketplaces/claude/
  marketplaces/openai/
```

The package generator uses the skill at `src/policy_mcp/package_templates/skills/policy-research/SKILL.md` as the only skill source. Both plugin trees receive the same bytes.

## Automated verification

Run the normal checks first:

```bash
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
uv build
```

Then run the release-artifact suite against the generated packages:

```bash
SOURCEBOOK_TEST_BINARY="$PWD/dist/policy-mcp" \
SOURCEBOOK_TEST_PACKAGES="$PWD/dist/packages" \
SOURCEBOOK_TEST_TARGET=darwin-arm64 \
uv run pytest tests/test_release_artifacts.py
```

This suite initializes each profile through MCP `stdio`, lists its tools, calls `policy_diagnostic`, and compares the result across the direct executable, Claude Code plugin, OpenAI plugin, and extracted MCPB. It launches packages from read-only paths containing spaces and checks that package removal leaves the shared data directory intact.

Validate host manifests with the host tools:

```bash
claude plugin validate dist/packages/claude-code-plugin/policy-research
claude plugin validate dist/packages/marketplaces/claude
npx --yes @anthropic-ai/mcpb validate path/to/extracted/manifest.json
```

## Development registration

Direct registration remains a support path. It does not replace package testing.

```bash
claude mcp add --transport stdio --scope user policy-legislation -- \
  /absolute/path/to/policy-mcp serve --profile legislation

codex mcp add policy-legislation -- \
  /absolute/path/to/policy-mcp serve --profile legislation
```

Repeat for `actors` and `evidence` when those profiles are needed.

## Release gates

Do not describe an artifact as a signed release candidate until all relevant gates pass:

- Sign and notarize the macOS arm64 executable, then run `codesign --verify` and `spctl --assess` on the packaged binary.
- Sign the Windows x64 executable and run the SmartScreen installation smoke test on Windows.
- Install, update, disable, re-enable, and uninstall the MCPBs through Claude Desktop.
- Install the OpenAI plugin through ChatGPT Desktop's Plugins Directory and verify its three local servers.
- Confirm that every uninstall leaves the operating system user-data directory and credential store untouched.

The public OpenAI packaging documentation defines the portable root `plugin.json` and `mcp.json` layout. Public submission documentation currently describes remote HTTPS MCP servers and directs local-MCP publishers to their OpenAI contact. This project uses local marketplaces only until a host smoke test confirms local `stdio` behavior for the specific ChatGPT Desktop release.
