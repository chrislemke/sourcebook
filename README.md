# Sourcebook

[![Quality](https://github.com/chrislemke/sourcebook/actions/workflows/quality.yml/badge.svg)](https://github.com/chrislemke/sourcebook/actions/workflows/quality.yml)
[![Validate packages](https://github.com/chrislemke/sourcebook/actions/workflows/package-proof.yml/badge.svg)](https://github.com/chrislemke/sourcebook/actions/workflows/package-proof.yml)

Sourcebook adds read-only German federal and EU research tools to Claude and Codex. It can search public-source metadata, return compact records, and keep links and source dates attached to the result.

You do not need to run a server yourself. After installation, the desktop app or command-line client starts Sourcebook when it needs it.

> The product names used below are **Claude Code** and **Codex CLI**. These are sometimes mistyped as "Cloud Code" and "Codec CLI."

## What works immediately

- GovData catalogue search works without an account or API key.
- German Bundestag DIP procedure search works after you add a free DIP API key and run the first sync.
- Claude Desktop, Claude Code, the ChatGPT desktop app, and Codex CLI all use the same local, read-only program.
- Sourcebook stores its index and credentials outside the installed package, so updates do not remove them.

Sources that have not been configured are shown as unavailable. Sourcebook does not turn a missing source into an empty search result.

## Build targets and release status

The package builder currently targets:

- Apple Silicon Macs, such as M1, M2, M3, and M4 Macs
- 64-bit Windows computers

Intel Macs and Linux are not packaged yet. Developers can still run the Python project directly with Python 3.12.

The packages built from this checkout are development artifacts. The macOS binary is ad-hoc signed rather than notarized, and the Windows binary is not Authenticode-signed. Gatekeeper or SmartScreen may therefore block it. A normal public release still needs platform signing and an interactive installation check in each desktop app.

## Download from GitHub

Open the [latest GitHub release](https://github.com/chrislemke/sourcebook/releases/latest) and download the file for your computer:

- `sourcebook-darwin-arm64.tar.gz` for an Apple Silicon Mac
- `sourcebook-windows-x64.zip` for a 64-bit Windows computer

Extract the file into a folder named `sourcebook`. It contains the standalone program, all three Claude Desktop extensions, and the Claude Code and OpenAI plugin marketplaces. The release also includes `SHA256SUMS` if you want to verify the downloads.

These downloads currently have the unsigned-development-package limitation described above. You may need to approve the program in your operating system's security settings.

## Prepare the package

If someone gave you a prepared `dist/packages` folder, skip to the section for your app.

To build it from this repository, first install [uv](https://docs.astral.sh/uv/getting-started/installation/). Then open a terminal in this folder and run:

```bash
uv sync --locked
uv run pyinstaller --noconfirm --clean policy-mcp.spec
```

On an Apple Silicon Mac, finish with:

```bash
uv run policy-mcp package --binary dist/policy-mcp --output dist/packages --target darwin-arm64
```

On Windows, finish with:

```powershell
uv run policy-mcp package --binary dist/policy-mcp.exe --output dist/packages --target windows-x64
```

The `dist/packages` folder now contains the client packages and a standalone executable in `dist/packages/bin`.

For the commands below, set the package folder once. Use the first `PACKAGE_DIR` line for a repository build or the second for an extracted GitHub download. On macOS:

```bash
PACKAGE_DIR="$PWD/dist/packages"
# PACKAGE_DIR="$PWD/sourcebook"
SOURCEBOOK="$PACKAGE_DIR/bin/policy-mcp"
CLAUDE_MARKETPLACE="$PACKAGE_DIR/marketplaces/claude"
OPENAI_MARKETPLACE="$PACKAGE_DIR/marketplaces/openai"
```

On Windows PowerShell:

```powershell
$PackageDir = (Resolve-Path ".\dist\packages").Path
# $PackageDir = (Resolve-Path ".\sourcebook").Path
$Sourcebook = (Resolve-Path "$PackageDir\bin\policy-mcp.exe").Path
$ClaudeMarketplace = (Resolve-Path "$PackageDir\marketplaces\claude").Path
$OpenAIMarketplace = (Resolve-Path "$PackageDir\marketplaces\openai").Path
```

## Claude Desktop

Claude Desktop uses three small extension files. Installing all three gives you the complete tool set; you can install only the areas you need if you prefer.

1. Open Claude Desktop.
2. Open **Settings → Extensions → Advanced settings**.
3. In **Extension Developer**, choose **Install Extension…**.
4. Open `dist/packages/claude-desktop` and install each `.mcpb` file:
   - `policy-legislation-…mcpb`
   - `policy-actors-…mcpb`
   - `policy-evidence-…mcpb`
5. Start a new conversation. If the tools do not appear, quit and reopen Claude Desktop.

Anthropic also documents this flow in its [Claude Desktop extension guide](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop).

## Claude Code

Install [Claude Code](https://code.claude.com/docs/en/setup) first if the `claude` command is not available. Then run:

```bash
claude plugin marketplace add "$CLAUDE_MARKETPLACE" --scope user
claude plugin install policy-research@policy-tools --scope user
```

On Windows PowerShell, use:

```powershell
claude plugin marketplace add "$ClaudeMarketplace" --scope user
claude plugin install policy-research@policy-tools --scope user
```

Start Claude Code again. Run `/plugin`, open **Installed**, and confirm that `policy-research` is enabled. Claude Code's [plugin guide](https://code.claude.com/docs/en/discover-plugins) explains the same marketplace process.

If plugin installation is unavailable, direct registration is the fallback:

```bash
"$SOURCEBOOK" setup-client --client claude-code
```

On Windows PowerShell, use `& $Sourcebook setup-client --client claude-code`. Direct registration saves this exact path, so do not move or delete the executable afterward.

## ChatGPT desktop app

This path requires a ChatGPT desktop version that shows local Plugins or MCP server settings. Local `stdio` support remains host-version-specific and still needs an interactive release check.

If [Codex CLI](https://learn.chatgpt.com/docs/codex/cli) is installed, add the local plugin with:

```bash
codex plugin marketplace add "$OPENAI_MARKETPLACE"
codex plugin add policy-research@policy-tools
```

On Windows PowerShell, use:

```powershell
codex plugin marketplace add "$OpenAIMarketplace"
codex plugin add policy-research@policy-tools
```

Quit and reopen the ChatGPT desktop app, then start a new task. Open the Plugins area and confirm that **Sourcebook** is enabled.

If you do not have Codex CLI, add the servers in the app itself:

1. Open **Settings → MCP servers**.
2. Choose **Add server** and select **STDIO**.
3. Add `policy-legislation` with this command and these arguments:

   ```text
   /absolute/path/to/policy-mcp serve --profile legislation
   ```

4. Repeat for `policy-actors` with `--profile actors` and `policy-evidence` with `--profile evidence`.
5. Save, choose **Restart**, and start a new task.

Use the real full path to the executable. The [OpenAI MCP guide](https://learn.chatgpt.com/docs/extend/mcp?surface=cli) also shows the desktop settings flow.

## Codex CLI

Install [Codex CLI](https://learn.chatgpt.com/docs/codex/cli) first if the `codex` command is not available. Then use the same OpenAI plugin package as the ChatGPT desktop app:

```bash
codex plugin marketplace add "$OPENAI_MARKETPLACE"
codex plugin add policy-research@policy-tools
```

On Windows PowerShell, use:

```powershell
codex plugin marketplace add "$OpenAIMarketplace"
codex plugin add policy-research@policy-tools
```

Start a new `codex` session and run `/plugins` to confirm that Sourcebook is installed.

If plugins are unavailable, use direct registration:

```bash
"$SOURCEBOOK" setup-client --client codex-cli
```

On Windows PowerShell, use `& $Sourcebook setup-client --client codex-cli`. Direct registration saves this exact path, so do not move or delete the executable afterward. You can check the registrations with `codex mcp list`. OpenAI's [MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli) describes these shared CLI and desktop settings.

## First use

GovData needs no setup. Try this in any connected client:

> Search GovData for official datasets about the federal budget. Return the title, publisher, licence, and official link for the three best matches.

For German legislative procedures, get a free API key from the [Bundestag DIP API page](https://dip.bundestag.de/%C3%BCber-dip/hilfe/api). Store it and download the most recent changes:

```bash
"$SOURCEBOOK" configure --credential DIP_API_KEY
"$SOURCEBOOK" sync --source dip
```

On Windows PowerShell, run `& $Sourcebook configure --credential DIP_API_KEY`, followed by `& $Sourcebook sync --source dip`.

The key is entered in a hidden prompt and stored in your operating system's credential store. It is not written to the MCP configuration. The first sync covers changes published during the previous day; use a bounded `backfill` for older dates. Sourcebook does not schedule refreshes, so run `sync` again when you want newer records. Restart the connected app after a sync so that it opens the updated local index.

For example, to add one older day on macOS:

```bash
"$SOURCEBOOK" backfill --source dip --from-date 2026-09-01 --to-date 2026-09-01
```

On Windows PowerShell, start the command with `& $Sourcebook` and use the same arguments. Choose dates that matter to your research; bounded windows keep provider requests predictable.

Then try:

> Search the locally synchronized German federal legislative procedures for a topic that changed recently. Show the recorded status, timeline, and official source links.

## Check that setup worked

Run the check that matches your client:

```bash
"$SOURCEBOOK" doctor --client claude-code
"$SOURCEBOOK" doctor --client codex-cli
```

On Windows PowerShell, use `& $Sourcebook doctor --client claude-code` or `& $Sourcebook doctor --client codex-cli`.

For a general check, run:

```bash
"$SOURCEBOOK" doctor
```

On Windows PowerShell, use `& $Sourcebook doctor`.

Warnings about sources without credentials are normal. An `ERROR` line means that the program, data folder, database, or selected client registration needs attention.

## Updating or removing Sourcebook

Download the newest GitHub release or rebuild the package first, then update the client:

- Claude Desktop: remove the old extensions in **Settings → Extensions**, then install the new `.mcpb` files.
- Claude Code: run `claude plugin update policy-research@policy-tools --scope user` after refreshing the marketplace, or uninstall and install it again.
- Codex and ChatGPT desktop: rebuild the local package, run `codex plugin remove policy-research@policy-tools`, then run `codex plugin add policy-research@policy-tools` again. The marketplace stays configured.

Removing a plugin does not remove Sourcebook's local index or stored API keys.

Every push to `main` runs the complete source checks and native package tests. GitHub publishes a new release only after the macOS and Windows packages pass their packaged MCP tests. Pull requests run the same package validation without publishing a release.

## Privacy and limits

Sourcebook runs on your computer and exposes read-only research tools. It does not change public records or contact anyone. It stores a local search index, source metadata, and any documents that a configured source worker downloads.

GovData is catalogue discovery only: Sourcebook lists distributions but does not execute arbitrary files or queries from them. DIP coverage starts with the time windows you sync; it is not automatically a complete historical archive. Other planned source routes remain visibly unavailable until their individual contract and live-data checks pass.

Maintainer details are in [docs/packaging.md](docs/packaging.md) and [docs/operations.md](docs/operations.md).
