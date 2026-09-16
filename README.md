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
claude plugin install policy-research@policy-tools --scope user --config dip_api_key=YOUR_DIP_KEY
./bin/policy-mcp doctor --client claude-code
```

On Windows PowerShell, run:

```powershell
claude plugin marketplace add "$((Resolve-Path '.\marketplaces\claude').Path)" --scope user
claude plugin install policy-research@policy-tools --scope user --config dip_api_key=YOUR_DIP_KEY
& ".\bin\policy-mcp.exe" doctor --client claude-code
```

`policy-research@policy-tools` is the complete plugin ID. `policy-tools` is Sourcebook's marketplace name, not a value you need to replace.

Replace `YOUR_DIP_KEY` with your [DIP API key](#get-a-dip-api-key). The key enables German Bundestag search. Claude Code stores it in the macOS Keychain or in its credentials file, not in `settings.json`. If you install the plugin from the `/plugin` menu instead, Claude Code asks for the key when you enable the plugin. To skip the key, leave out `--config dip_api_key=YOUR_DIP_KEY`; everything except German legislation search still works.

Start a new Claude Code session. Run `/plugin`, open **Installed**, and confirm that `policy-research` is enabled. See the [Claude Code plugin guide](https://code.claude.com/docs/en/discover-plugins) if the plugin commands are unavailable.

#### Claude Desktop

Claude Desktop uses three extension files:

1. Open Claude Desktop.
2. Open **Settings > Extensions > Advanced settings**.
3. Under **Extension Developer**, choose **Install Extension...**.
4. Open the `claude-desktop` folder inside your Sourcebook folder.
5. Install the three files whose names begin with `policy-legislation`, `policy-actors`, and `policy-evidence`.
6. When Claude Desktop installs `policy-legislation`, it asks for a **DIP API key (German Bundestag)**. Paste your [DIP API key](#get-a-dip-api-key). Claude Desktop stores it securely. You can leave the field empty and add the key later in **Settings > Extensions > Sourcebook Legislation**.
7. Start a new conversation. If the tools do not appear, quit and reopen Claude Desktop.

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

German legislation search queries the Bundestag's official DIP database live. DIP accepts requests only with an API key. The key is free.

### Get a DIP API key

You have two options:

- **Public key.** The official [DIP API help page](https://dip.bundestag.de/%C3%BCber-dip/hilfe/api) publishes a key that anyone may use without registering. The key published there in September 2026 is valid until the end of May 2027. The Bundestag then replaces it, so copy the new key from the same page when the old one stops working. The community project [bundesAPI/dip-bundestag-api](https://github.com/bundesAPI/dip-bundestag-api) on GitHub also lists the public key, but it can lag behind the official page.
- **Personal key.** Send an e-mail to parlamentsdokumentation@bundestag.de with your name and e-mail address, plus your organisation if you have one. A personal key is initially valid for ten years and works the same as the public key. The [DIP terms of use](https://dip.bundestag.de/documents/nutzungsbedingungen_dip.pdf) apply to both.

### Enter the key

- **Claude Desktop:** enter the key in the dialog that appears when you install `policy-legislation`. To add or change it later, open **Settings > Extensions > Sourcebook Legislation**.
- **Claude Code:** pass `--config dip_api_key=YOUR_DIP_KEY` to `claude plugin install`, as shown in [Connect your app](#claude-code). Claude Code also asks for the key when you enable the plugin from the `/plugin` menu.
- **Codex CLI, the ChatGPT desktop app, or any client:** store the key in your operating system's credential store. Sourcebook asks for it in a hidden prompt and never writes it to a configuration file.

  On macOS, run this from the Sourcebook folder:

  ```bash
  ./bin/policy-mcp configure --credential DIP_API_KEY
  ```

  On Windows PowerShell, run:

  ```powershell
  & ".\bin\policy-mcp.exe" configure --credential DIP_API_KEY
  ```

A key entered in Claude Desktop or the Claude Code plugin takes precedence over the credential store. Restart the app or start a new session after you add or change the key. Run `./bin/policy-mcp doctor` to confirm that the `dip_api_key` line reads `OK`.

Then ask:

> Search the German Bundestag procedures for the Tariftreuegesetz. Show its status, parliamentary steps, and the official DIP link.

Live search matches words in procedure titles, so distinctive words such as *Tariftreue* work better than general words such as *Gesetz*. An optional local index adds abstracts and subject terms; [docs/operations.md](docs/operations.md) describes `sync` and `backfill`.

## API keys for each source

Only German legislation search needs a key today. The table lists every source Sourcebook connects to or plans to connect to, and where to find public keys or request your own.

| Source | Used for | Key needed | Public key | Personal key or account |
|---|---|---|---|---|
| Bundestag DIP | German legislation search | Yes, `DIP_API_KEY` | [Official DIP API page](https://dip.bundestag.de/%C3%BCber-dip/hilfe/api), valid until the end of May 2027; also listed on GitHub at [bundesAPI/dip-bundestag-api](https://github.com/bundesAPI/dip-bundestag-api) | E-mail parlamentsdokumentation@bundestag.de |
| Bundestag Lobbyregister | Lobbying search | No. Sourcebook uses the register's public search | The register's REST API needs a key, published on the [official Lobbyregister open data page](https://www.lobbyregister.bundestag.de/informationen-und-hilfe/open-data-1049716). API reference: [Swagger UI](https://api.lobbyregister.bundestag.de/rest/v2/swagger-ui/). GitHub: [bundesAPI/bundestag-lobbyregister-api](https://github.com/bundesAPI/bundestag-lobbyregister-api) documents only the older keyless endpoints | E-mail lobbyregister@bundestag.de for a permanent personal key |
| Destatis GENESIS-Online | Planned statistics tables; not connected yet (`GENESIS_TOKEN`) | Yes | None. The [official API guide](https://genesis.destatis.de/datenbank/online/docs/GENESIS-Webservices_Einfuehrung.pdf) requires a login or token. GitHub: [bundesAPI/destatis-api](https://github.com/bundesAPI/destatis-api) | Register free of charge on [GENESIS-Online](https://genesis.destatis.de/datenbank/online), then copy your token from the **Webservice-Schnittstelle (API)** dialog. See the [Destatis API overview](https://www.destatis.de/DE/Service/OpenData/genesis-api-webservice-oberflaeche.html) |
| EUR-Lex web service | Planned EU full-text search; not connected yet (`EURLEX_USERNAME`, `EURLEX_PASSWORD`) | Yes | None | Free after registration, as described on the [EUR-Lex web service page](https://eur-lex.europa.eu/content/help/data-reuse/webservice.html) |
| GovData, European Parliament, EU WhoisWho, EU Transparency Register | Datasets, MEPs, EU officials, EU lobbying | No | Not needed | Not needed |

Public keys are shared by everyone who uses them, so the provider can replace them at short notice. Use a personal key if you rely on a source every day.

## Troubleshooting

Run a general check from the Sourcebook folder:

```bash
./bin/policy-mcp doctor
```

On Windows PowerShell, run `& ".\bin\policy-mcp.exe" doctor`.

A public source can occasionally be slow or unavailable. Sourcebook reports that source separately and still returns results from the other available sources. An `ERROR` line from `doctor` means the program, data folder, database, or client registration needs attention.

If every public source reports `temporarily_unavailable`, check whether a firewall such as Little Snitch blocks `policy-mcp`. Each release is a new unsigned program, so firewall rules for an earlier version may not apply.

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
- German Bundestag procedure search queries DIP live after you add a free DIP API key.
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

GovData is catalogue discovery only. Sourcebook lists distributions but does not execute files or queries from them. German legislation searches send your search words and your DIP API key to the Bundestag's DIP API. Other planned source routes remain unavailable until their contracts and live-data checks pass.
