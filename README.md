# Sourcebook

[![Quality](https://github.com/chrislemke/sourcebook/actions/workflows/quality.yml/badge.svg)](https://github.com/chrislemke/sourcebook/actions/workflows/quality.yml)
[![Validate packages](https://github.com/chrislemke/sourcebook/actions/workflows/package-proof.yml/badge.svg)](https://github.com/chrislemke/sourcebook/actions/workflows/package-proof.yml)

Sourcebook adds read-only German federal and EU research tools to Claude and Codex. It searches public-source metadata, returns compact records, and keeps links and source dates attached to the result.

You do not need to install Python or start a server yourself. Install the package once, and your desktop app or command-line client starts Sourcebook when it needs it.

## Install Sourcebook

Sourcebook currently provides packages for Apple Silicon Macs and 64-bit Windows computers. Intel Macs and Linux are not packaged yet.

The macOS package is not notarized, and the Windows package is not Authenticode-signed. Only download them from this repository. Gatekeeper or SmartScreen may ask you to approve the program the first time it runs.

### 1. Download and extract the package

Download the package for your computer:

- [Apple Silicon Mac](https://github.com/chrislemke/sourcebook/releases/latest/download/sourcebook-darwin-arm64.tar.gz)
- [64-bit Windows](https://github.com/chrislemke/sourcebook/releases/latest/download/sourcebook-windows-x64.zip)
- [Checksums](https://github.com/chrislemke/sourcebook/releases/latest/download/SHA256SUMS)

On macOS, open Terminal and run:

```bash
SOURCEBOOK_DIR="$HOME/Applications/Sourcebook"
mkdir -p "$SOURCEBOOK_DIR"
tar -xzf "$HOME/Downloads/sourcebook-darwin-arm64.tar.gz" -C "$SOURCEBOOK_DIR"
cd "$SOURCEBOOK_DIR"
```

On Windows, open PowerShell and run:

```powershell
$SourcebookDir = Join-Path $env:LOCALAPPDATA "Sourcebook"
New-Item -ItemType Directory -Force -Path $SourcebookDir | Out-Null
Expand-Archive -Path "$HOME\Downloads\sourcebook-windows-x64.zip" -DestinationPath $SourcebookDir -Force
Set-Location $SourcebookDir
```

Keep this terminal open and continue with the section for your app.

### 2. Connect your app

#### Claude Code

Install [Claude Code](https://code.claude.com/docs/en/setup) first if the `claude` command is unavailable.

On macOS, run these commands from the Sourcebook folder:

```bash
claude plugin marketplace add "$PWD/marketplaces/claude" --scope user
claude plugin install policy-research@policy-tools --scope user
./bin/policy-mcp doctor --client claude-code
```

On Windows PowerShell, run:

```powershell
claude plugin marketplace add "$((Resolve-Path '.\marketplaces\claude').Path)" --scope user
claude plugin install policy-research@policy-tools --scope user
& ".\bin\policy-mcp.exe" doctor --client claude-code
```

`policy-research@policy-tools` is the complete plugin ID. `policy-tools` is Sourcebook's marketplace name, not a value you need to replace.

Start a new Claude Code session. Run `/plugin`, open **Installed**, and confirm that `policy-research` is enabled. See the [Claude Code plugin guide](https://code.claude.com/docs/en/discover-plugins) if the plugin commands are unavailable.

#### Claude Desktop

Claude Desktop uses three extension files:

1. Open Claude Desktop.
2. Open **Settings > Extensions > Advanced settings**.
3. Under **Extension Developer**, choose **Install Extension...**.
4. Open the `claude-desktop` folder inside your Sourcebook folder.
5. Install the three files whose names begin with `policy-legislation`, `policy-actors`, and `policy-evidence`.
6. Start a new conversation. If the tools do not appear, quit and reopen Claude Desktop.

Anthropic's [Claude Desktop extension guide](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop) has screenshots of the same flow.

#### Codex CLI

Install [Codex CLI](https://learn.chatgpt.com/docs/codex/cli) first if the `codex` command is unavailable.

On macOS, run these commands from the Sourcebook folder:

```bash
codex plugin marketplace add "$PWD/marketplaces/openai"
codex plugin add policy-research@policy-tools
./bin/policy-mcp doctor --client codex-cli
```

On Windows PowerShell, run:

```powershell
codex plugin marketplace add "$((Resolve-Path '.\marketplaces\openai').Path)"
codex plugin add policy-research@policy-tools
& ".\bin\policy-mcp.exe" doctor --client codex-cli
```

Start a new Codex session and run `/plugins` to confirm that Sourcebook is installed. The [OpenAI plugin guide](https://learn.chatgpt.com/docs/plugins) explains the plugin browser.

#### ChatGPT desktop app

Install Sourcebook with the Codex CLI commands above, then quit and reopen the ChatGPT desktop app. Open **Plugins** and confirm that Sourcebook is installed before starting a new local Codex task.

If the plugin does not appear, use the shared MCP configuration instead:

```bash
./bin/policy-mcp setup-client --client codex-cli
```

On Windows PowerShell, run:

```powershell
& ".\bin\policy-mcp.exe" setup-client --client codex-cli
```

Restart the desktop app after direct registration. The ChatGPT desktop app and Codex CLI share MCP configuration on the same host, as described in the [OpenAI MCP guide](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).

### 3. Run your first search

GovData and the actor sources work without an account, API key, or setup step. Start a new conversation or task and ask:

> Search GovData for official datasets about the federal budget. Return the title, publisher, licence, and official link for the three best matches.

Then try the actor profile:

> Find Friedrich Merz in the official European Parliament and EU directory sources. Return his published identifiers, dated roles, and official links.

Actor searches query the European Parliament and EU WhoisWho directly. Searches for interest representatives also use the German Lobbyregister and the EU Transparency Register. Sourcebook uses the Lobbyregister's public web search when its API requires a key, so users do not need to request or enter one. The EU Transparency Register publishes a large daily XML snapshot. Sourcebook downloads it on the first relevant search, stores it in the local Sourcebook data directory, and reuses it for 24 hours.

## Add German Bundestag procedures

German Bundestag DIP procedure search needs a free DIP API key and a first sync. Get a key from the [Bundestag DIP API page](https://dip.bundestag.de/%C3%BCber-dip/hilfe/api).

On macOS, open Terminal in the Sourcebook folder and run:

```bash
./bin/policy-mcp configure --credential DIP_API_KEY
./bin/policy-mcp sync --source dip
```

On Windows PowerShell, run:

```powershell
& ".\bin\policy-mcp.exe" configure --credential DIP_API_KEY
& ".\bin\policy-mcp.exe" sync --source dip
```

Sourcebook asks for the key in a hidden prompt and stores it in your operating system's credential store. It does not write the key to the MCP configuration.

The first sync covers changes from the previous day. Sourcebook does not schedule updates, so run `sync` again when you need newer records. Restart the connected app after a sync so it opens the updated local index. See [docs/operations.md](docs/operations.md) for bounded historical backfills.

Then try:

> Search the locally synchronized German federal legislative procedures for a topic that changed recently. Show the recorded status, timeline, and official source links.

## Troubleshooting

Run a general check from the Sourcebook folder:

```bash
./bin/policy-mcp doctor
```

On Windows PowerShell, run `& ".\bin\policy-mcp.exe" doctor`.

A public source can occasionally be slow or unavailable. Sourcebook reports that source separately and still returns results from the other available sources. An `ERROR` line from `doctor` means the program, data folder, database, or client registration needs attention.

If macOS blocks the program, run `./bin/policy-mcp --version` once. Then open **System Settings > Privacy & Security**, choose **Open Anyway** for `policy-mcp`, and rerun the command.

If plugin installation is unavailable, register the MCP servers directly:

```bash
./bin/policy-mcp setup-client --client claude-code
./bin/policy-mcp setup-client --client codex-cli
```

On Windows PowerShell, replace `./bin/policy-mcp` with `& ".\bin\policy-mcp.exe"`. Direct registration saves the current executable path, so do not move or delete the Sourcebook folder afterward.

## What works now

- GovData catalogue search works without an account or API key.
- European Parliament and EU WhoisWho actor searches work without an account or API key.
- German Lobbyregister and EU Transparency Register searches work without user-supplied credentials. Sourcebook uses the Bundestag's public search and caches the EU snapshot automatically.
- German Bundestag DIP procedure search works after you add a DIP API key and run the first sync.
- Claude Desktop, Claude Code, the ChatGPT desktop app, and Codex CLI use the same local, read-only program.
- Sourcebook stores its index and credentials outside the installed package, so updates do not remove them.

## Update or remove Sourcebook

To update, download the newest release and extract it into the same Sourcebook folder. Then refresh the client:

- Claude Desktop: remove the old extensions in **Settings > Extensions**, then install the new `.mcpb` files.
- Claude Code: run `claude plugin marketplace update policy-tools`, followed by `claude plugin update policy-research@policy-tools --scope user`.
- Codex and ChatGPT desktop: run `codex plugin remove policy-research@policy-tools`, followed by `codex plugin add policy-research@policy-tools`.

Removing a plugin does not remove Sourcebook's local index or stored API keys.

## Build from source

Developers can run Sourcebook directly with Python 3.12. Install [uv](https://docs.astral.sh/uv/getting-started/installation/), open a terminal in this repository, and run:

```bash
uv sync --locked
uv run pyinstaller --noconfirm --clean policy-mcp.spec
```

On an Apple Silicon Mac, build the client packages with:

```bash
uv run policy-mcp package --binary dist/policy-mcp --output dist/packages --target darwin-arm64
```

On Windows, use:

```powershell
uv run policy-mcp package --binary dist/policy-mcp.exe --output dist/packages --target windows-x64
```

The `dist/packages` folder has the same layout as an extracted release. Run the installation commands from that folder.

Every push to `main` runs the source checks and native package tests. GitHub publishes a release only after the macOS and Windows packages pass their packaged MCP tests. The macOS binary is ad-hoc signed rather than notarized, and the Windows binary is not Authenticode-signed. A public release still needs platform signing and an interactive installation check in each desktop app.

Maintainer details are in [docs/packaging.md](docs/packaging.md) and [docs/operations.md](docs/operations.md).

## Privacy and limits

Sourcebook runs on your computer and exposes read-only research tools. It does not change public records or contact anyone. It stores its local index, source metadata, and downloaded public snapshots outside the installed package.

Actor searches send the user's search terms to the selected official public sources. The EU Transparency Register snapshot can exceed 100 MB and may make the first matching search slower. Sourcebook retains only the public fields needed for identity, role, disclosure, provenance, and source links. It does not retain published phone numbers, email addresses, or postal addresses.

GovData is catalogue discovery only. Sourcebook lists distributions but does not execute files or queries from them. DIP coverage starts with the time windows you sync, so it is not automatically a complete historical archive. Other planned source routes remain unavailable until their contracts and live-data checks pass.
