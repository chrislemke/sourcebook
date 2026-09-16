# Prove the client package paths

Status: ready-for-human

## Problem statement

The political research MCP must run as the same local, read-only product in Claude Desktop, Claude Code CLI, ChatGPT Desktop, and Codex CLI. The package formats and host behavior have not yet been tested with the proposed Python executable. If packaging waits until the adapters are complete, the project may discover too late that process launch, bundled paths, updates, or local data handling differ across hosts.

## Solution

Build one small `policy-mcp` executable that exposes three profile-specific local MCP servers and a trivial diagnostic tool. Package that executable as three Claude Desktop MCP Bundles, one Claude Code plugin, and one portable OpenAI Agent Plugin. Install each package through its normal user path, compare the host-visible MCP contracts, and prove that updates and uninstalls preserve shared user data and credentials.

## User stories

1. As a Claude Desktop user, I want to install the legislation profile as an extension, so that I can use the MCP without installing Python or editing configuration files.
2. As a Claude Desktop user, I want actor and evidence profiles to be optional extensions, so that unused tools do not occupy model context.
3. As a Claude Code user, I want one plugin to install all three servers, so that the CLI manages their lifecycle together.
4. As a ChatGPT Desktop user, I want one local Agent Plugin, so that all three profiles are available through the Plugins Directory.
5. As a Codex CLI user, I want to use the same OpenAI plugin artifact as ChatGPT Desktop, so that the project does not maintain a Codex-specific fork.
6. As a developer, I want direct MCP registration to work in Claude Code and Codex, so that I have a recovery path when plugin packaging is disabled or broken.
7. As a user, I want each profile to expose only its intended tools, so that connecting one domain does not reveal unrelated tools.
8. As a maintainer, I want tool names, descriptions, schemas, and annotations to match across hosts, so that packaging cannot change product behavior.
9. As a user, I want package updates to preserve indexes, downloaded documents, and credentials, so that upgrades do not destroy local state.
10. As a user, I want uninstalling a package to leave user data intact unless I explicitly request deletion, so that removal is reversible.
11. As an operator, I want a doctor command for each client, so that launch, registration, storage, and credential problems are reported without exposing secrets.
12. As a security reviewer, I want package manifests to contain no upstream credentials, so that distributing an artifact cannot leak account access.
13. As a macOS user, I want a signed Apple Silicon artifact that passes Gatekeeper checks, so that normal installation does not require security workarounds.
14. As a Windows user, I want a signed x64 artifact that passes SmartScreen smoke checks, so that normal installation is understandable and safe.
15. As a maintainer, I want plugin skill text generated from one shared source, so that Claude and OpenAI packages do not drift.
16. As a maintainer, I want package locations to be disposable, so that all mutable state remains in an OS-standard user data directory.
17. As a user running two clients, I want both processes to read the same local store safely, so that I do not need duplicate corpora.
18. As a release engineer, I want reproducible artifacts for each platform and package family, so that a release can be audited and rebuilt.

## Implementation decisions

- One executable named `policy-mcp` serves all domains. A required profile argument selects legislation, actors, or evidence.
- The runtime uses local `stdio`. The default installation opens no listening network port and requires no tunnel or hosted endpoint.
- Claude Desktop receives one MCP Bundle per profile. Legislation is the required first-install profile; actors and evidence remain optional.
- Claude Code receives one native plugin that declares three bundled MCP servers and launches the executable from the plugin root.
- ChatGPT Desktop and Codex CLI receive the same portable Agent Plugin with root portable manifests and three bundled `stdio` server declarations.
- OpenAI local and repository marketplaces are the private and development distribution route. Public submission is a later release decision.
- The current official OpenAI documentation confirms that portable packages use a root manifest plus a root MCP configuration, and that supported local clients share local-marketplace settings. Host-level smoke tests remain mandatory because local MCP availability varies by surface and release.
- Direct Claude and OpenAI MCP registration remains a documented development and support fallback.
- A shared package template owns version, binary metadata, icons, and the optional policy-research skill. Vendor-specific trees are generated artifacts.
- The optional skill contains only domain selection, search-then-fetch guidance, and interpretation limits. Its rendered body must stay below 400 tokens.
- The executable resolves an OS-standard user data directory. Plugin and extension directories contain no mutable index, document store, or credentials.
- All local profiles share one SQLite store configured for concurrent readers, busy timeouts, and serialized ingestion.
- The configure command writes credentials to the OS credential store. Development deployments may forward existing environment variables, but manifests never contain keys.
- Initial self-contained binaries target macOS Apple Silicon and Windows x64. Users do not install Python, Node.js, or uv.
- Packaging may use PyInstaller or Nuitka only after startup time, certificates, SQLite, and data-directory behavior pass smoke tests.

## Testing decisions

- The primary test seam is the packaged MCP contract. Start each packaged profile, complete MCP initialization, list tools, and call the diagnostic tool through the same boundary a host uses.
- Compare cross-client snapshots for tool names, input schemas, annotations, and normalized diagnostic output. A packaging-specific difference fails the build.
- Test fresh install, update, disable, re-enable, and uninstall for every supported host. Assert that user data and credentials survive each operation.
- Test package launch from paths containing spaces and from read-only package directories.
- Test simultaneous read-only connections from at least two local hosts against the shared SQLite store.
- Inspect every produced manifest and archive for known credential names and seeded secret values.
- Run macOS Gatekeeper and Windows SmartScreen smoke checks on the signed release candidates.
- Test direct registration separately from plugin installation because it is a support path with different configuration behavior.
- No prior application tests exist. The plan's cross-client acceptance matrix is the initial prior art and becomes an executable snapshot suite.
- Lower-level bundler tests are useful for build diagnostics, but release confidence comes from installing and launching the final artifacts.

## Out of scope

- Public plugin-directory submission and marketplace governance.
- ChatGPT web, Codex cloud, remote MCP hosting, and Secure MCP Tunnel support.
- Real political source adapters, ingestion, search, and evidence retrieval.
- Linux and additional CPU architectures.
- Deleting user data as part of uninstall.

## Further notes

This milestone intentionally uses a diagnostic tool rather than a source adapter. Its job is to invalidate packaging assumptions before adapter work makes the executable expensive to change. The package contracts must later be replaced by the real profile tools without changing the launch model.

## Implementation result

Implemented on 16 September 2026:

- One MCP 2.x `stdio` executable now serves the `legislation`, `actors`, and `evidence` profiles. Each profile exposes the same read-only `policy_diagnostic` contract under its own stable server name.
- All profiles use one operating-system user-data directory and one SQLite database configured for WAL, a 5-second busy timeout, foreign keys, and serialized first-open initialization.
- `policy-mcp doctor` checks the executable, data directory, database, credential backend, and optional client registration without reading secret values. `policy-mcp configure` stores named credentials in the OS keyring.
- One deterministic generator creates three MCPBs, one Claude Code plugin, one portable OpenAI Agent Plugin, and local marketplace trees from a single native binary and shared skill source.
- The macOS arm64 PyInstaller build passed the direct and packaged MCP contract suite. The suite also covered paths containing spaces, read-only package trees, concurrent clients, reproducible outputs for every package family on both targets, archive-member credential scans, and data and external credential-state preservation across artifact lifecycle operations.
- Windows MCPB manifests select `policy-mcp.exe` for both the binary entry point and launch command; target-specific tests lock that contract before the native Windows build runs.
- The official MCPB validator accepted the generated manifest. Claude Code accepted its plugin and marketplace, detected all three MCP servers, and passed install, disable, re-enable, update, and uninstall checks. Codex accepted the same portable OpenAI package through its local marketplace and passed install and uninstall checks.
- Claude Code connected to the packaged legislation server through a temporary direct registration. Codex CLI accepted the equivalent direct `stdio` registration. Both registrations were removed after the check.

Human release gates remain:

- Install the MCPBs through the Claude Desktop extension UI and verify update and uninstall behavior.
- Install the portable plugin through the ChatGPT Desktop Plugins Directory and verify all three local servers. Current public OpenAI submission documentation describes remote HTTPS MCP; local `stdio` support therefore remains host-version-specific.
- Sign and notarize the macOS artifact with a release identity. The local ad-hoc signature passes `codesign --verify`, but Gatekeeper rejects it as a release artifact.
- Build and sign the Windows x64 artifact on Windows, then run the SmartScreen smoke test.
