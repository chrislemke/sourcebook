# Political research MCP: implementation plan

Version: 1.2  
Research date: 16 September 2026  
Scope: public, no-fee German federal and EU information sources; local desktop and CLI distribution  
Primary hosts: Claude Desktop, Claude Code CLI, ChatGPT desktop app and Codex CLI  
Audience: engineers implementing and packaging a local political-research MCP for Anthropic and OpenAI desktop/CLI clients

## 1. Decision and scope

Build **one Python codebase with three small local MCP servers**, backed by shared source adapters, a local search index and a document store. Expose **15 task-oriented tools**, not one tool for every upstream HTTP endpoint. Run the same local `policy-mcp` executable in all supported clients and change only the packaging layer. No hosted MCP service is required for the primary product.

The supported client set is deliberately broader than the desktop-only packaging in v1.1:

- **Claude Desktop:** three MCP Bundles (`.mcpb`), one per domain profile.
- **Claude Code CLI:** one Claude Code plugin that bundles the same three local `stdio` MCP servers.
- **ChatGPT desktop app:** one OpenAI Agent Plugin that bundles the same three local `stdio` MCP servers.
- **Codex CLI:** the same OpenAI Agent Plugin used by ChatGPT Desktop; direct `codex mcp` registration remains a development/support fallback.

This means four primary clients but only three distribution families: MCPB for Claude Desktop, a Claude Code plugin, and an OpenAI Agent Plugin shared by ChatGPT Desktop and Codex CLI.

| MCP server | Research question | Tools | Default connection |
|---|---|---:|---|
| `policy-legislation` | What is proposed, discussed, amended, voted on or published? | 6 | Enabled |
| `policy-actors` | Which organisations and public officeholders are connected to a subject through documented roles or disclosures? | 4 | Enable for institutional and register research |
| `policy-evidence` | What do official statistics, budgets, procurement notices and funding records show? | 5 | Enable for quantitative and funding research |

These are three servers implementing the same Model Context Protocol, not three new protocols. The primary runtime is three local `stdio` processes launched by the client host. All three use the same executable with a different `--profile` argument and share the same local storage and source adapters. Do not implement three copies of authentication, storage or HTTP handling.

Client packaging is a first-class requirement, not a deployment afterthought. Claude Desktop receives MCP Bundles (`.mcpb`). Claude Code receives a native Claude Code plugin with bundled `stdio` MCP servers. ChatGPT Desktop and Codex CLI share one OpenAI Agent Plugin built around the portable Agent Plugins package format. Direct MCP registration remains the development and recovery fallback. See section 2.5 and section 11.1.

The architecture covers all 13 source groups in the earlier shortlist. Treat EUR-Lex search and CELLAR retrieval as separate adapters, producing 14 adapters. Add **Gesetze im Internet** as a fifteenth, optional adapter because parliamentary records alone do not provide a consolidated German statute collection.

The initial product is a read-only research system. It retrieves evidence and reports source limitations. It does not submit consultations, contact officials, file register changes, generate political influence scores or automate persuasive outreach.

### What this document verifies

The research reviewed official documentation, the European Parliament and TED machine-readable specifications, DIP documentation and indexed schema information, the GENESIS manual, official download catalogues, Claude Desktop MCPB packaging, Claude Code MCP/plugin packaging, OpenAI local MCP documentation, OpenAI plugin packaging and the Agent Plugins 1.0 specification. Links appear beside each source description and in the reference register.

**This is a documentation-grounded implementation plan, not a tested integration.** Authenticated API calls, rate-limit behaviour, full download ingestion and client package interoperability were not tested. Network restrictions prevented successful runtime probes. Some JavaScript pages and the Lobbyregister YAML could not be fully retrieved. The Claude MCPB, Claude Code plugin and OpenAI Agent Plugin paths are supported by current documentation, but the release artifacts still need host-level smoke tests. Those gaps are explicit implementation gates, not assumed capabilities.

All limits marked **project default**, **target** or **proposed** are engineering choices. They are not provider guarantees or measured benchmark results.

### Reading order

Implement sections 2-6 first. Section 7 contains the adapter specifications. Sections 8-13 cover storage, safety, deployment and acceptance tests. Section 14 supplies request examples. Section 15 lists unresolved checks.

Do not load this entire plan, its documentation links or upstream specifications into the research model's system prompt. They are implementation material. The model receives the compact tool contracts in section 4.

## 2. Design constraints that determine the architecture

### 2.1 More servers do not automatically mean fewer tokens

MCP supplies tool discovery and invocation. The host decides how the model sees the tools. Splitting 100 tools across ten servers does not reduce the tool-schema payload when the host still presents all 100 tools. Likewise, `tools/list` pagination is not a guarantee of on-demand model exposure. [M1]

Use two supported operating modes:

| Mode | Host behaviour | Our implementation |
|---|---|---|
| Portable default | Host exposes all tools from connected servers | Keep each server small; connect only the needed domains; stable, short schemas |
| Discovery-aware host | Host selects and loads tools on demand | Let it index the same 15 descriptions; load the selected tool's full schema before invocation |

Do not depend on host-specific tool search for correctness. Do not add a universal `execute(endpoint, arguments)` tool as the default. It would move endpoint selection and schema reconstruction back to the model.

Client packaging must preserve the three-server split. Claude Desktop uses three small MCPB bundles; the Claude Code plugin and OpenAI Agent Plugin each declare the same three bundled MCP servers. This keeps installation simple without collapsing all tools into one large server.

### 2.2 MCP version and SDK selection

At research time, the official `latest` specification redirected to **2026-07-28**. This revision changes transport and lifecycle behaviour, including stateless requests, `server/discover` and explicit cross-call handles. It does not permit tool lists to vary as a side effect of earlier requests on the same connection. The current official Python SDK documentation describes v2 as the stable line supporting this and earlier protocol revisions. [M2] [M3]

Use the official Python SDK v2, resolve an exact tested patch release during implementation and commit the lockfile. Start dependency resolution with `mcp[cli]>=2,<3`; do not treat that range as a production lock. Use Python 3.12 as a project baseline.

Let the SDK handle protocol envelopes and compatibility. Test both 2026-07-28 and a required legacy client, for example one using 2025-11-25. Do not mix the old initialization handshake with new request metadata by hand. The code examples below describe application arguments, not raw MCP wire messages.

Publish a stable tool list for each endpoint and authorization scope. Change deployment profiles through configuration or separate endpoint registration, not a conversation-specific `load_tools()` side effect.

### 2.3 Search first, fetch selected evidence second

A normal task should take two or three model-visible calls:

1. Search for small metadata cards.
2. Select a returned reference and fetch its procedure, record or dataset structure.
3. Read a relevant passage or retrieve a bounded numeric slice, when necessary.

The backend performs pagination, joins, format conversion and source selection. The model should not receive raw JSON-LD graphs, complete register entries, SPARQL bindings, an entire CSV file or a 100-page parliamentary transcript.

Do not use an LLM inside every adapter to compress output. Begin with deterministic field projection, metadata search and query-matched excerpts. This avoids another model bill and keeps the evidence traceable.

### 2.4 Free access is different from anonymous access

DIP and the German Lobbyregister require keys. EUR-Lex SOAP search requires registration and approval. The June 2026 GENESIS manual requires authentication for data requests, despite the public website's general statement about free, unregistered use. Its authenticated requests use POST. [D1] [A1] [E3] [S1] [S2]

The source-access policy is `no_fee_sources_only`. Accounts and free keys are allowed. Hosted infrastructure, model inference and optional commercial search services are separate costs; this plan does not assume those are free. The local baseline needs no paid database, embedding API or search subscription.

### 2.5 Client-first local distribution

The primary product runs locally. Do not require a remote MCP endpoint, tunnel or cloud deployment for normal use.

| Host | Primary package | Local transport | User installation | Notes |
|---|---|---|---|---|
| Claude Desktop | Three `.mcpb` bundles | `stdio` | Install the extensions in Claude Desktop | Native local MCP packaging. Each bundle launches one domain profile. [C1] [C2] |
| Claude Code CLI | One Claude Code plugin | `stdio` | Add a plugin marketplace, install `policy-research`, reload plugins | The plugin can define MCP servers in `.mcp.json`; enabled plugin servers start automatically. [C3] [C4] [C5] |
| ChatGPT desktop app | One OpenAI Agent Plugin | `stdio` | Install from a local/repo marketplace in the Plugins Directory | Portable plugin root contains `plugin.json`, `mcp.json`, optional skills and the bundled executable. [O2] [O3] |
| Codex CLI | The same OpenAI Agent Plugin | `stdio` | Use the same local/repo marketplace; enable for the user or repo | Local-marketplace plugins are supported in Codex CLI. Marketplace sources can be added with `codex plugin marketplace add`. [O2] |
| ChatGPT Desktop / Codex direct fallback | Direct MCP registration | `stdio` | Desktop MCP settings or `codex mcp add` / `config.toml` | ChatGPT Desktop, Codex CLI and the IDE extension share MCP configuration for the same Codex host. [O1] |
| Claude Code direct fallback | Direct MCP registration | `stdio` | `claude mcp add` or `.mcp.json` | Useful for development and support; not the normal end-user package. [C3] |
| ChatGPT web / Codex cloud | Not an MVP target | Remote/hosted mechanisms | Separate future product decision | Do not add a tunnel merely to claim web compatibility. |

This plan separates **runtime** from **distribution**. The runtime is the same local executable everywhere. Distribution only tells each host how to install and launch it.

Use one executable with profile arguments:

```text
policy-mcp serve --profile legislation
policy-mcp serve --profile actors
policy-mcp serve --profile evidence
```

This keeps the source tree, tests, API adapters and data model identical across clients. Packaging differences must not leak into tool names, schemas or source semantics.

For the first release, build self-contained executables for macOS Apple Silicon and Windows x64. Add other targets only when required. Do not require end users to install Python, Node.js or `uv`. A Python bundler such as PyInstaller or Nuitka is acceptable after smoke tests confirm startup time, certificate handling and SQLite behaviour. This is a project choice, not an MCP requirement.

The three packaging families are:

1. **Claude Desktop MCPB:** package each profile as a small `.mcpb` extension. This keeps domain activation explicit and avoids exposing all tools when only legislation research is needed. [C1] [C2]
2. **Claude Code plugin:** package all three profiles in one Claude Code plugin. Define the servers in the plugin root `.mcp.json` and launch the bundled binary through `${CLAUDE_PLUGIN_ROOT}`. Claude Code manages their lifecycle when the plugin is enabled. [C3] [C4]
3. **OpenAI Agent Plugin:** package all three profiles in one portable Agent Plugin with root `plugin.json` and `mcp.json`. OpenAI documents local-marketplace plugins for supported local clients including Codex CLI and Codex in the ChatGPT desktop app. [O2] [O3]

Do not use the Secure MCP Tunnel for the primary desktop/CLI implementation. It is only relevant to a later workflow where a cloud-only ChatGPT surface must reach a private local server.

### 2.6 Plugins are distribution, not routing logic

Use plugins to install the MCP processes and, optionally, a very small cross-server skill. Do not move the upstream API documentation or endpoint-routing tables into plugin instructions.

Both the Claude Code plugin and the OpenAI Agent Plugin may include an optional `policy-research` skill with only these rules:

```text
Choose legislation for laws, procedures, debates, votes and parliamentary documents.
Choose actors for officeholders, institutions and disclosed interest representation.
Choose evidence for statistics, budgets, procurement and funding.
Search first. Fetch detail only for selected references.
Use capability tools only when coverage is unclear.
Do not infer influence, political alignment or legal effect beyond the returned evidence.
```

Keep the skill short enough to remain cheap when loaded. It is a workflow aid, not a dependency for correct routing. The MCP tool descriptions and deterministic backend router remain sufficient on clients that do not load the skill.

The plugin package can also contain installation metadata, icons and a local setup command. Those files never belong in model context unless the host explicitly invokes them.

## 3. System layout

```text
Claude Desktop / Claude Code / ChatGPT Desktop / Codex CLI
    |
    +-- local stdio: policy-legislation  [6 tools]
    +-- local stdio: policy-actors       [4 tools]
    +-- local stdio: policy-evidence     [5 tools]
                |
        Shared application services
        - typed request validation
        - deterministic routing registry
        - source-specific query compilation
        - canonical reference resolution
        - excerpts and numeric projections
        - provenance and response budgets
                |
        Source adapters and background ingestion
        - REST / SOAP / SPARQL
        - documented XML / JSON / CSV / XLSX downloads
                |
        Local stores
        - metadata and lexical search index
        - immutable document versions
        - dataset metadata and selected slices
        - sync watermarks and source health
```

Use SQLite with FTS5 and a filesystem document store for the first single-user deployment. Put storage interfaces around them so a multi-user installation can move to PostgreSQL and object storage without changing tool contracts. These are proposed implementation choices, not source requirements.

Separate two workloads:

| Workload | Purpose | Can hold large responses? | Model sees |
|---|---|---|---|
| Interactive request | Answer a bounded research question | Only within strict request limits | Cards, selected sections or small tables |
| Ingestion job | Refresh indices and download published datasets | Yes, under separate ingestion quotas | Only freshness and coverage metadata |

A local index is required for useful topic search where the upstream source only lists or filters records. Downloaded-data sources cannot be made into low-latency search tools merely by wrapping their download URL.

## 4. The model-facing contract

### 4.1 Names and descriptions

Use the following descriptions nearly verbatim. They explain the information boundary without teaching the underlying APIs.

| Tool | Description presented to the model |
|---|---|
| `leg_search` | Find German or EU legislative procedures and legal texts by topic or identifier. Returns metadata and references, not full documents. |
| `leg_procedure` | Get a known procedure's recorded status, timeline and linked documents. Use a procedure reference returned by search. |
| `leg_records` | Find parliamentary speeches, questions, votes, meetings and documents, or implementation documents. Choose one record kind and jurisdiction. |
| `leg_read` | Read a bounded passage or outline from a known legislative document. Use a returned document reference, not an arbitrary URL. |
| `leg_changes` | List recorded legislative changes within a time window. Reports source coverage; not a forecast or a complete record of all government activity. |
| `leg_capabilities` | Check available legislation sources, date coverage and unsupported features. Use only when scope or source availability is unclear. |
| `actor_search` | Find public officeholders, institutional bodies or disclosed interest representatives by name and scope. Does not assess influence or political alignment. |
| `actor_get` | Get a known actor's published roles, organisational relationships or register disclosure sections, with dates and sources. |
| `actor_interests` | Find organisations' disclosed interests, clients or regulatory projects matching a topic or procedure. Reports disclosures, not proof of influence. |
| `actor_capabilities` | Check available actor and register collections, freshness and limitations. Use only when coverage is unclear. |
| `evidence_search` | Find official statistical datasets, federal budget datasets, procurement notices, funding calls or funded projects. Returns small metadata cards. |
| `evidence_describe` | Inspect a dataset's units, dimensions, available periods and permitted selections before querying its values. |
| `evidence_query` | Retrieve a bounded, validated slice of a known statistical or budget dataset. Use dimension codes returned by evidence_describe. |
| `evidence_get` | Get one known procurement, funding, project or catalogue record, or a bounded excerpt from its available documents. |
| `evidence_capabilities` | Check available evidence sources, supported datasets and refresh status. Use only when coverage is unclear. |

The three capability tools are fallbacks. Do not require a capability call before every search. They should return only the relevant source subset, not the whole registry.

### 4.2 Shared input types

Use JSON Schema with `additionalProperties: false`. Keep enumerations short. Do not expose the entire list of EU bodies, budget chapters, statistical dimensions or provider fields as enum values in tool definitions.

```text
Jurisdiction = "DE" | "EU" | "BOTH"
Language = "de" | "en"
Reference = opaque string returned by this system
Date = ISO 8601 calendar date
Timestamp = ISO 8601 timestamp with timezone
Cursor = opaque string returned by this system

SearchWindow = {
  date_from?: Date,
  date_to?: Date,
  date_basis?: "published" | "source_modified" | "observed_changed"
}

Search defaults:
  limit = 5; allowed 1..10
  language = deployment default
  cursor omitted on first page
```

Use required `jurisdiction` for legislative searches rather than silently treating every question as German. `BOTH` is an explicit request to search both collections. Actor and evidence searches use `scope` where an institution or dataset scope is more precise.

Dates must have stated semantics. Publication date, meeting date, effective date, source modification date and our ingestion time are not interchangeable. Some searches support fewer date bases; reject unsupported ones rather than ignoring them.

Use `updated_since` on actor and evidence searches for observed local changes. Report `date_basis=observed_changed`. Do not present this as a provider's complete change feed.

### 4.3 Tool arguments

A question mark marks an optional field. Constraints here are part of the contract, not suggestions to the model.

| Tool | Inputs beyond shared language, limit and cursor |
|---|---|
| `leg_search` | `jurisdiction`; `query?`; `identifier?`; `kind=procedure\|legal_text`; `date_from?`; `date_to?`; `date_basis?`; `source?` |
| `leg_procedure` | `ref`; `view=overview\|timeline\|documents`; `as_of?`; `cursor?`; `limit?` |
| `leg_records` | `jurisdiction`; `kind=speech\|question\|vote\|meeting\|document\|implementation_document`; `query?`; `procedure_ref?`; `actor_ref?`; `date_from?`; `date_to?`; `source?` |
| `leg_read` | `ref`; `view=excerpt\|outline`; `query?`; `section_id?`; `cursor?`; `max_tokens?` |
| `leg_changes` | `jurisdiction`; `since`; `until?`; `query?`; `procedure_refs?` with maximum 10; `cursor?`; `limit?` |
| `leg_capabilities` | `topic?`; `source?`; `jurisdiction?` |
| `actor_search` | `query`; `scope=DE\|EU\|BOTH`; `kind=person\|institution\|interest_representative`; `as_of?`; `updated_since?`; `source?` |
| `actor_get` | `ref`; `view=overview\|roles\|relationships\|disclosures\|evidence`; `as_of?`; `section_id?`; `query?`; `cursor?`; `limit?` |
| `actor_interests` | `scope`; `query?`; `procedure_ref?`; `actor_ref?`; `updated_since?`; `cursor?`; `limit?` |
| `actor_capabilities` | `topic?`; `source?`; `scope?` |
| `evidence_search` | `query`; `kind=statistics\|budget\|procurement\|funding_call\|funded_project\|catalogue`; `scope=DE\|EU\|BOTH`; `date_from?`; `date_to?`; `updated_since?`; `source?` |
| `evidence_describe` | `ref`; `dimension_id?`; `member_query?`; `cursor?`; `limit?` |
| `evidence_query` | `ref`; `schema_version`; `selections`; `period_from?`; `period_to?`; `measures?`; `row_limit?`; `cursor?` |
| `evidence_get` | `ref`; `view=overview\|details\|excerpt`; `query?`; `section_id?`; `cursor?`; `max_tokens?` |
| `evidence_capabilities` | `topic?`; `source?`; `scope?` |

Validation rules:

- `leg_search` requires exactly one of `query` and `identifier`. An identifier from an ambiguous numbering system also needs jurisdiction or source information.
- `leg_records` requires a query, a parent reference, an actor reference or a bounded date window. Do not allow an unbounded corpus dump.
- `actor_interests` requires at least one query or reference.
- `leg_read(view="excerpt")` requires a query, section or continuation cursor. Default to an outline when none is supplied, and say that explicitly.
- `evidence_describe` returns at most ten dimension members at a time. Return `member_count` and a cursor for large dimensions.
- `evidence_query` accepts typed selections only: `[{"dimension_id":"...","member_ids":["..."]}]`. No SQL, Python, SPARQL or arbitrary upstream JSON.
- Validate `schema_version` against the stored dataset structure. On mismatch, request a fresh `evidence_describe` call.
- Reject `as_of` when the source and stored versions cannot support the requested historical answer. A current record is not an acceptable silent substitute.

### 4.4 Example JSON Schema

This example is intentionally small. Generate the remaining schemas from typed application models and snapshot-test their serialized size.

```json
{
  "name": "leg_search",
  "description": "Find German or EU legislative procedures and legal texts by topic or identifier. Returns metadata and references, not full documents.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "jurisdiction": {"type": "string", "enum": ["DE", "EU", "BOTH"]},
      "query": {"type": "string", "minLength": 1, "maxLength": 300},
      "identifier": {"type": "string", "minLength": 1, "maxLength": 120},
      "kind": {"type": "string", "enum": ["procedure", "legal_text"], "default": "procedure"},
      "date_from": {"type": "string", "format": "date"},
      "date_to": {"type": "string", "format": "date"},
      "date_basis": {"type": "string", "enum": ["published", "source_modified", "observed_changed"]},
      "source": {"type": "string", "maxLength": 40},
      "language": {"type": "string", "enum": ["de", "en"]},
      "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
      "cursor": {"type": "string", "maxLength": 2048}
    },
    "required": ["jurisdiction"],
    "oneOf": [
      {"required": ["query"], "not": {"required": ["identifier"]}},
      {"required": ["identifier"], "not": {"required": ["query"]}}
    ],
    "additionalProperties": false
  },
  "annotations": {
    "readOnlyHint": true,
    "destructiveHint": false,
    "idempotentHint": true,
    "openWorldHint": true
  }
}
```

Annotations describe behaviour; enforce read-only operation in application code. Internal caching does not authorize changes to upstream systems. [M1]

### 4.5 Response envelope

Return a compact common envelope and small, kind-specific records. Omit empty optional fields. Never omit warnings, reference identifiers, source URLs or a material freshness limitation merely to hit a token target.

```json
{
  "schema_version": "1.0",
  "request_id": "example-request",
  "status": "partial",
  "items": [
    {
      "ref": "example-opaque-ref",
      "kind": "procedure",
      "title": "Illustrative title, not a real research result",
      "source": "dip",
      "source_id": "example-id",
      "source_url": "https://example.invalid/source-record",
      "recorded_status": "provider status, preserved without reinterpretation",
      "source_modified_at": "2026-09-15T10:00:00+02:00",
      "next": {"tool": "leg_procedure", "arguments": {"ref": "example-opaque-ref", "view": "overview"}}
    }
  ],
  "coverage": [
    {
      "source": "dip",
      "retrieval_mode": "local_index",
      "indexed_from": "2026-01-01",
      "synced_at": "2026-09-16T05:00:00Z",
      "complete_for_request": false
    }
  ],
  "warnings": ["Example: older material has not been backfilled."],
  "next_cursor": null,
  "truncated": false
}
```

`next` is an optional navigation hint, not an instruction that must be executed. Include at most one useful next action per card. Real `source_url` values must come from a provider record or a validated official permalink rule.

Keep detailed provenance in storage. Return a small `evidence_id` when the user requests a passage, number or relationship. It resolves to the original URL, version, locator and retrieval timestamp.

For MCP results, provide `structuredContent` with a bounded output schema. Keep a compact serialized text fallback for portable clients. When controlling the host, project one representation into model context rather than presenting both. Measure the actual host payload; SDKs or clients may duplicate the JSON. Do not claim structured output is token-free. [M1]

### 4.6 Resources and discovery

Publish optional resources such as `policy://legislation/catalog` and `policy://source/dip`. They can hold source summaries and coverage metadata. Resource contents are application-controlled and are not guaranteed to reach the model automatically. The capability tools provide a tools-only fallback. [M4]

Do not put complete API documentation in automatically supplied resource content. A capability card should contain:

```json
{
  "source": "ep",
  "supports": ["procedures", "parliamentary_records", "institutional_roles"],
  "topic_search": "mixed_native_and_local_index",
  "record_text": "collection_dependent",
  "state": "ready",
  "coverage_ref": "example-coverage-ref"
}
```

## 5. Routing without repeated model deliberation

### 5.1 Deterministic routing table

The model chooses the task-oriented tool. The backend chooses the actual API operation. This is the main mechanism for avoiding token-heavy endpoint exploration.

| Intent / input | Tool | Adapter route | Search method |
|---|---|---|---|
| German federal legislative procedure | `leg_search`, `leg_procedure` | DIP | Local topic index; exact provider lookup and linked positions |
| German parliamentary speech or vote | `leg_records` | Bundestag downloads, DIP metadata | Parsed speech/vote index; fetch selected source |
| German consolidated statute | `leg_search`, `leg_read` | Optional Gesetze im Internet | XML catalogue and local provision index |
| EU procedure | `leg_search`, `leg_procedure` | EP; linked EUR-Lex/CELLAR where explicit | Local procedure index, then exact procedure/events lookup |
| EU legal text or CELEX identifier | `leg_search`, `leg_read` | CELLAR; EUR-Lex search when configured | Identifier/metadata query; registered SOAP full-text search if needed |
| EU plenary speech | `leg_records` | EP speeches collection | Native documented text filters, then bounded text retrieval |
| EU parliamentary question or document | `leg_records` | EP document collections | Metadata index; document extraction when available |
| EU implementation committee document | `leg_records` | Comitology datasets | Local dataset/document index |
| German interest-representation disclosure | `actor_search`, `actor_interests` | German Lobbyregister | Register search plus indexed disclosure fields |
| EU interest-representation disclosure | `actor_search`, `actor_interests` | EU Transparency Register | Local snapshot index |
| EP member or parliamentary body | `actor_search`, `actor_get` | EP | Exact lookup or indexed name/role search |
| EU institution's organisational role | `actor_search`, `actor_get` | EU WhoisWho | Bounded SPARQL templates or local role index |
| German statistical table | `evidence_search`, `evidence_describe`, `evidence_query` | GENESIS | Find, inspect metadata, then selected values |
| Federal budget allocation | Same three evidence tools | Federal budget downloads | Versioned local tables |
| Public procurement notice | `evidence_search`, `evidence_get` | TED Search API | Server-compiled expert query with field projection |
| EU funding call or funded project | `evidence_search`, `evidence_get` | Funding & Tenders | Documented corporate-search collection |
| Unknown public dataset location | `evidence_search(kind="catalogue")` | GovData | CKAN catalogue search, not arbitrary dataset execution |

Source capabilities behind these routes are documented in section 7. A route is enabled only after its adapter acceptance tests pass.

### 5.2 Route selection algorithm

```text
validate input and enforce authorization
if ref is present:
    resolve ref to source, entity kind and version
    call the matching adapter operation
else if an explicit source is present:
    validate that source supports this intent and scope
    route only there
else if a recognised identifier is present:
    choose the configured identifier resolver
    reject ambiguous identifiers rather than guessing
else:
    use the intent + jurisdiction routing table
    search the relevant local index or native search operation
    expand to at most one additional source when the intent requires it
project, attach evidence and coverage, apply response budget
```

Do not broadcast every query to every source. Default interactive fan-out is two adapters; one is preferable. A user request for a cross-source comparison can explicitly use a larger bounded plan.

Use deterministic identifier mapping where possible. Store provider IDs separately from internal references. A procedure, a draft document and the resulting act remain different entities even when their titles are similar.

### 5.3 No hidden completeness claims

Distinguish:

- `no_matches`: the queried, available collection returned no matching records.
- `not_covered`: the source or requested period is outside implemented coverage.
- `not_configured`: credentials or a documented distribution are missing.
- `temporarily_unavailable`: a source request failed.

An empty result from a partially indexed corpus must not become "nothing happened" in the answer. Return the corpus boundary with the result.

## 6. Token and request budgets

These are initial project targets. Measure them against the chosen host and tokenizer before changing the design.

| Item | Default / target | Enforcement |
|---|---|---|
| Connected tool definitions | At most 3,000 tokens per domain; target at most 7,000 for all three | CI snapshot using host-visible descriptions and schemas |
| Search response | 5 cards; target at most 1,000 tokens | Drop optional card fields, then return fewer cards with continuation |
| Procedure or actor overview | Target at most 1,200 tokens | Fixed summary view, bounded relationships |
| Document excerpt | Default 1,200; hard interactive ceiling 2,400 tokens | Whole passage boundaries; explicit continuation |
| Dataset description | Target at most 1,200 tokens | Dimension/member pagination |
| Numeric result | Default at most 25 rows and 250 cells; target at most 1,800 tokens | Preflight selected slice size; no silent sampling |
| Capability response | Target at most 500 tokens | Filtered cards only |
| Provider requests per interactive call | Default maximum 6 | Adapter budget; partial result on exhaustion |
| Model-visible calls per simple task | Target 2-3 | Evaluation, not a hard correctness rule |

A budget is a ceiling on a response, not permission to remove contradictory evidence or necessary units. If the mandatory fields exceed the ceiling, return fewer records or a typed `RESULT_TOO_LARGE` response.

Trim in this order: unused languages, transport metadata, redundant labels, optional descriptions, unrelated relationships, then whole result cards. Never cut raw serialized JSON mid-string or remove legal qualifications from an extracted passage.

Use excerpts with paragraph IDs, headings and enough surrounding text to preserve meaning. The query match is not the whole evidence if an exception, negation or definition changes it.

Prompt caching may reduce billed input processing in a particular host, but it does not eliminate context occupancy. Report both schema tokens and complete turn tokens. Do not publish a percentage saving without a controlled comparison.

## 7. Adapter specifications

### 7.1 DIP: German parliamentary procedures and materials

**Verified contract.** Base URL: `https://search.dip.bundestag.de/api/v1`. Read-only resources include procedures, positions, activities, people, printed papers and plenary records. Use `Authorization: ApiKey <key>`; obtain a free public or individual key through the official help page. [D1] [D2]

Selected operations from the schema are `GET /vorgang`, `/vorgang/{id}`, `/vorgangsposition`, `/drucksache`, `/drucksache/{id}`, `/plenarprotokoll`, `/aktivitaet` and `/person`. Documented filters include `f.vorgang`, `f.dokumentnummer`, `f.wahlperiode`, `f.datum.start`, `f.datum.end` and `f.aktualisiert.start`. Apply only parameters declared for the particular operation. [D3]

Pagination repeats the original query with its returned `cursor`; the documentation defines an unchanged cursor as exhaustion. The short guide describes up to 100 metadata records per page and generally ten full-text records. It advises no more than 25 simultaneous requests; that is not a published universal requests-per-second allowance. [D2]

**Implementation.** Build a local index of titles, abstracts, subject descriptors and document references. Do not invent `q`, `f.titel` or a general full-text search parameter. Resolve supported text-resource paths from the pinned OpenAPI and fetch selected documents only. Use modification timestamps, not document dates, for incremental ingestion. Persist the raw provider status.

**Acceptance.** Capture metadata, cursor, detail and modification-window fixtures. Test multi-position procedures and a Bundesrat-linked record. Never describe DIP as covering all Land parliaments or every ministry publication.

Docs: [API help][D1], [short guide][D2], [OpenAPI][D3], [Swagger][D4].

### 7.2 Bundestag Open Data: structured speeches, biographies and votes

**Verified contract.** The official Open Data page publishes parliamentary documents in machine-readable formats, member master data as XML and roll-call lists as spreadsheet downloads. The page links a plenary-record DTD for the structured XML used from the nineteenth parliamentary term. This is a download collection, not a single uniform REST API. [D5]

**Implementation.** Resolve published links and retain a versioned download manifest. Parse structured speech records into document, agenda item, speaker and paragraph units. Use DIP to find related procedure metadata. Parse vote spreadsheets into vote event, member reference and recorded vote; keep corrections and missing values explicit. Do not infer an individual's vote from an aggregate result or a party's position.

Treat older and newer XML structures as different parser versions. Do not assume that every historical text has identical speaker-level structure. Member master data supports identity resolution, not a guaranteed current committee-membership directory.

**Acceptance.** Test two XML generations, duplicate name handling, a corrected roll-call file and a vote linked to its underlying motion. Validate spreadsheet headers rather than relying on fixed column positions.

Docs: [Open Data and download links][D5], [plenary-record publication information][D6].

### 7.3 German Lobbyregister API v2

**Verified contract.** Base URL: `https://api.lobbyregister.bundestag.de/rest/v2`. Official documentation offers read access to public register content, a published key and individual keys on request. API v1 was replaced by v2 in June 2025. The indexed Swagger lists `GET /registerentries`, `/registerentries/{registerNumber}`, `/registerentries/{registerNumber}/{version}` and `/statistics/registerentries`. [A1] [A2]

**Implementation gate.** The YAML body was not successfully retrieved in this research environment. Before coding, download it through the official page, pin its checksum, and confirm the exact authentication scheme, search parameters, cursor rules and version fields. Do not copy those details from a similarly named API or an unofficial wrapper.

**Implementation.** Index names, interest areas, clients and disclosed regulatory projects where the public fields provide them. Keep original disclosure wording and reported financial ranges. Join to DIP through explicit document or procedure references where available. Label title-based matches as candidates requiring verification.

`actor_get` returns only the requested section. Do not place a complete organisation disclosure and every attachment into each search response. A published disclosure records what was declared, not a verified causal account of influence.

**Acceptance.** Validate one current entry, one historical version, search continuation and a regulatory-project link. Add a schema-drift test for organisational recipient fields.

Docs: [Open Data/API][A1], [Swagger v2][A2], [YAML link][A3].

### 7.4 European Parliament Open Data API v2

**Verified contract.** Base URL: `https://data.europarl.europa.eu/api/v2`. The specification exposes procedures and events, members, bodies, meetings, speeches and document collections. Common list pagination uses `offset` and `limit`; responses include JSON-LD. The published request limit is 500 per endpoint in five minutes. [E1] [E2]

Key distinction: `/procedures` and `/documents` do not declare a generic topic-search parameter. `/speeches` does declare `text`, `title`, `search-language`, date filters and optional text enrichment. `/procedures/{process-id}/events` supplies linked events. Feed capabilities differ by collection. [E2]

**Implementation.** Index procedure/document metadata locally. Use native speech search where supported; fetch text enrichment only for selected records. Support `/meps`, `/corporate-bodies`, `/meetings`, `/parliamentary-questions`, `/committee-documents` and `/adopted-texts` through the shared adapter, not separate model tools.

Flatten requested languages and resolve linked identifiers server-side. Preserve work, language-expression and file distinctions. A record may point to text or votes in another file; do not assume a metadata record contains the full text or roll-call rows. The speech schema has differing prose and enum indications for term coverage, so test periods rather than promising a historical range.

**Acceptance.** Verify native speech search, procedure events, a question's linked file and a vote with its resolution/amendment context. Test each collection's pagination and feed separately.

Docs: [developer portal][E1], [OpenAPI JSON][E2].

### 7.5 EUR-Lex search

**Verified contract.** EUR-Lex provides a free SOAP search service after registration and approval. It supports expert queries, including full-text search, and returns XML metadata. Document files must be retrieved separately. From 1 January 2026, one search is limited to 10,000 results. Access details and the WSDL are supplied through registration. [E3]

**Implementation.** Keep this a separate adapter from CELLAR. Compile approved expert-query templates from typed inputs. Store credentials outside model context. Apply the allowance granted to the account; do not assume an unlimited daily quota. Partition ingestion by documented date/type filters when the result cap is reached.

The no-registration deployment can still perform CELLAR identifier and metadata retrieval. It must state that equivalent full-text search is unavailable unless a local corpus supplies it.

**Acceptance.** Test account setup, XML fault handling, paging, query field selection and a query exceeding the retrieval cap. Never expose the SOAP envelope or expert language to the model.

Docs: [service and registration][E3].

### 7.6 CELLAR: EU legal metadata and document retrieval

**Verified contract.** CELLAR is publicly accessible. Query metadata at `https://publications.europa.eu/webapi/rdf/sparql`. The official guide documents Common Metadata Model queries and links between works, language expressions, manifestations and downloadable items; it also documents REST dissemination of metadata. [E4] [E5]

**Implementation.** Use tested SPARQL templates for identifier lookup, bounded metadata search and related-document retrieval. A template compiler validates identifiers and escapes literal values; the model does not generate SPARQL. Resolve document URLs from returned item identifiers or documented stable links rather than constructing guessed file paths.

Prefer structured XML or HTML when present, with PDF text extraction as a fallback. Record the selected language and version. Maintain separate fields for publication, legal status and applicable dates; do not infer an entire act's applicability from one general date.

**Acceptance.** Resolve a CELEX reference to metadata and an available language-specific file. Test an amended/consolidated work, a missing translation and a timeout. Keep large text outside the response until `leg_read` requests a passage.

Docs: [CELLAR documentation][E4], [knowledge graph and examples][E5].

### 7.7 EU WhoisWho: public institutional roles

**Verified contract.** CELLAR's official query guide includes EU WhoisWho examples linking a person, membership, organisation and position through FOAF, ORG and EU vocabulary properties. Use the same public SPARQL service with a distinct collection adapter. [E5]

**Implementation.** Select only names, role labels, organisation identifiers and available validity metadata. Make optional fields optional in queries; the example's gender or honorific requirements are unnecessary for our research use. Store the original institutional identifiers.

`actor_get(view="roles")` describes published organisational roles. It must not infer policy responsibility solely from a job title. Current snapshots do not establish historical membership, and the date a record was downloaded is not its effective date.

**Acceptance.** Test people with multiple roles, missing dates and organisation names in different languages. Do not promise complete departmental reporting trees before validating the available relations.

Docs: [WhoisWho query example][E5], [directory][E6].

### 7.8 EU Transparency Register

**Verified contract.** The official dataset catalogue advertises public XML and spreadsheet distributions of registered interest representatives, including daily current lists and historical snapshots. Its description also retains old transition-period language. The advertised cadence is not proof that a particular distribution is fresh. [A4]

**Implementation.** Resolve current distribution URLs from the official catalogue, download snapshots off the interactive path and build an index. Validate the file's schema and actual timestamp. Record download time separately when no provider timestamp exists.

Store the register identifier, organisation name, interests, declared resources and other permitted public fields. Limit personal details to the business purpose. Compute observed diffs between retained versions; distinguish disappearance from confirmed deregistration.

There is no verified general REST search contract in this plan. A catalogue's own "API" button does not establish an API for every field in its underlying dataset.

**Acceptance.** Validate one current distribution and the chosen fields before enabling the adapter. Detect HTML error pages downloaded as XML, stale files and schema changes.

Docs: [dataset and distributions][A4].

### 7.9 Comitology Register

**Verified contract.** The register provides reusable CSV datasets for committees, agendas, draft measures, voting sheets, summary records and other documents. The official dataset description explains the collection's relation to implementing measures. [E7] [E8]

**Implementation.** Use a versioned manifest of official CSV distributions for a selected language, then index metadata. Follow published document references for detail retrieval. Keep the draft measure, committee meeting, vote and final legal act separate, joining only through explicit identifiers.

Treat these as download adapters, not a documented interactive REST search API. If the dynamic page does not expose a retrievable distribution URL in the deployment environment, leave the adapter `not_configured` until the operator supplies the official download URL. Do not silently reverse-engineer private application endpoints.

**Acceptance.** Test all six dataset families, language fallback, document-reference resolution and snapshot changes. Unsupported attachment formats produce metadata-only results.

Docs: [download page][E7], [dataset catalogue][E8].

### 7.10 GovData

**Verified contract.** GovData advertises CKAN at `https://www.govdata.de/ckan/api` and SPARQL at `https://www.govdata.de/sparql`. CKAN action operations include `package_search` and `package_show`; the public catalogue is a metadata collection, not a guarantee of uniform access to every underlying dataset. [S3] [S4]

**Implementation.** Use `GET /ckan/api/3/action/package_search` with documented `q`, `fq`, `rows` and `start` parameters; retrieve selected entries with `package_show?id=...`. Project title, publisher, dates, licence and a small list of distributions. Parse `success` and `result` rather than treating HTTP 200 alone as success.

Default GovData results to `queryable=false`. A resource becomes queryable only after an allowlisted adapter validates its format, licence and schema. Do not assume CKAN DataStore is enabled for all resources. SPARQL is an optional catalogue enrichment path, not necessary for the first release.

**Acceptance.** Test a public package search, a selected package and a broken external distribution without treating the latter as a GovData outage.

Docs: [GovData interfaces][S3], [CKAN API reference][S4].

### 7.11 Destatis GENESIS

**Verified contract.** Base URL: `https://genesis.destatis.de/genesisWS/rest/2020`. The manual dated 1 June 2026 requires authentication except for `helloworld/whoami`. Use POST with credentials in headers and form-encoded parameters. A personal token replaces the username; a password is then unnecessary. Relevant methods include `find/find`, `catalogue/tables`, `metadata/table` and `data/table`. Check the returned `Status`, not only HTTP status. [S1]

The public access page describes free use and the attribution licence. Do not confuse that with anonymous API access. [S2]

**Implementation.** Resolve tables by topic, inspect structure, validate dimension codes and retrieve a narrow slice. Preserve units, scale, reference periods, territorial definitions, footnotes and missing-value symbols. Return normalized rows, not the raw formatted table string. Use token-compatible non-job requests initially; large selections should be narrowed rather than submitted as account jobs.

Start with one concurrent request. Inspect provider errors and current account limits before increasing concurrency. Redact credentials even if an upstream response echoes request parameters.

**Acceptance.** Verify token authentication, a small table, metadata changes, suppressed values and a nonzero status inside HTTP 200. Test German numeric formatting.

Docs: [manual, version 5.1][S1], [access and licensing][S2].

### 7.12 German federal budget downloads

**Verified contract.** The budget download portal publishes datasets such as CSV/XML and distinguishes official budget documents from reusable data. It permits processing and commercial reuse while directing users to the official documents as the binding source. [S5]

**Implementation.** Ingest published files into local tables with fiscal year, publication stage, version, budget section, chapter, title, function and amount where present. Keep the source's amount unit and separate expenditure from revenue.

Model `draft`, `enacted`, `supplementary` and `actual` as distinct stages only when the source identifies them. An available draft is not an enacted allocation. When comparing years, explain classification changes and do not sum hierarchical totals together with their children.

Map file columns through a versioned parser rather than assuming stable names. A budget dataset can be searched, described and queried through the same evidence tools as a statistical dataset.

**Acceptance.** Validate numeric units against the original file, detect double counting and compare two stages without merging them. Resolve official download URLs before enabling ingestion.

Docs: [download portal][S5], [BMF dataset overview][S6].

### 7.13 TED Search API v3

**Verified contract.** The documented public operation is `POST https://api.ted.europa.eu/v3/notices/search`. The Search API requires no key, unlike some other TED services. It accepts an expert query and projected fields. The specification describes pagination and scroll modes; normal pagination has a 15,000-result retrieval boundary and a maximum of 250 notices per page. [F1] [F2] [F3]

**Implementation.** Compile topic, buyer, country, publication-date and classification filters into tested expert-query templates. Pin a small field projection and validate it against the current field catalogue. Use five results by default, not the upstream maximum. Preserve notice identifiers, type, publication date, buyer and links.

Keep notice, procurement procedure, lot and contract award distinct. An announcement is not proof of a contract or actual expenditure. Use scroll only in ingestion jobs, respecting token expiry and upstream semantics; do not fabricate a uniform pagination model.

**Acceptance.** Test a bounded search, field errors, a correction notice and repeated pages while new notices arrive. De-duplicate by identifier and version.

Docs: [Search API][F1], [OpenAPI][F2], [API access guidance][F3], [download guidance][F4].

### 7.14 EU Funding & Tenders

**Verified contract.** The official page documents public REST search services for grants/tenders, topics, updates, organisations, partner searches and projects. It gives `POST https://api.tech.ec.europa.eu/search-api/prod/rest/search?apiKey=SEDIA&text=...` and describes JSON search criteria in POST form data. `SEDIA` is a documented public collection key, not a private credential to obtain. [F5]

**Implementation.** Add separate query templates for funding calls and funded projects. Do not assume every collection shares the same key or field names. Obtain current pagination, form-data encoding, facet and document-detail examples from the official documentation/Postman material before enabling each collection.

Translate programme and status codes through documented reference data. Preserve deadline, call status and document timestamps. Query narrowly and return identifiers; retrieve a selected topic or project record only on demand.

**Acceptance.** The public page rendered inconsistently during research, so request serialization and pagination remain deployment checks. Validate a call, a funded project and their detail lookup independently. Do not substitute calls for funded projects when one collection is unavailable.

Docs: [official APIs and examples][F5].

### 7.15 Optional addition: Gesetze im Internet

**Verified contract.** The official site provides consolidated federal statutes and regulations, XML downloads, a public DTD and a daily XML contents list at `https://www.gesetze-im-internet.de/gii-toc.xml`. It distinguishes these consolidated texts from the official promulgation source. [D7]

**Implementation.** Ingest the contents list, follow published XML links and index provisions. Keep the source's amendment and status notes. Use `leg_search(kind="legal_text", jurisdiction="DE")` and `leg_read` without adding more model tools.

Do not label the consolidated text as the authoritative gazette publication. Link the relevant official promulgation source when available. Historical questions require retained versions or another validated historical source.

**Acceptance.** Test an exact statute lookup, one provision, an amendment note and a missing historical version. The minimum release must reject German consolidated-law queries clearly if this adapter is not enabled.

Docs: [formats, DTD, contents list and status explanation][D7].

## 8. Indexing, refresh and historical correctness

### 8.1 Data model

Use a few explicit tables rather than one undifferentiated document blob.

```text
sources
  id, capability_version, enabled, health, last_success_at, last_error_code

records
  internal_ref, source_id, provider_id, kind, canonical_url, title,
  published_at, source_modified_at, first_seen_at, last_seen_at

record_versions
  record_ref, version_id, content_hash, retrieved_at, raw_object_path,
  normalized_object_path, parser_version, licence_ref

relations
  subject_ref, predicate, object_ref, evidence_id,
  valid_from, valid_to, relation_basis

text_sections
  document_ref, version_id, section_id, heading, locator,
  language, text, text_hash, extraction_method

dataset_schemas
  dataset_ref, schema_version, dimensions, measures, units,
  coverage, permitted_selections

sync_state
  source_id, collection, scope, completed_watermark, cursor,
  snapshot_id, coverage_from, coverage_to, backfill_complete

search_snapshots
  handle, principal_id, normalized_query_hash, ordered_refs,
  snapshot_id, offset, expires_at
```

Internal references are opaque. Canonical provider identifiers remain separate fields. A relation needs an evidence reference and a basis such as `explicit_provider_link` or `candidate_text_match`. Candidate matches do not silently become factual relationships.

### 8.2 Proposed refresh schedule

These cadences are starting configuration values, not statements about publication speed.

| Collection | Proposed schedule | Incremental strategy |
|---|---|---|
| DIP metadata | Every 30 minutes | Modification window with overlap and ID/hash de-duplication |
| EP supported feeds | Every hour | Per-collection feed handling, bounded reconciliation |
| EP metadata without suitable feeds | Nightly bounded refresh | Paged collection refresh and hash comparison |
| Selected parliamentary/legislative files | On demand, plus tracked-document refresh | Conditional retrieval where supported |
| German register, EU register, WhoisWho | Daily | Provider update/version support or snapshot diff |
| Comitology, budget, statute downloads | Daily manifest check | Fetch changed distributions, then compare parsed versions |
| GENESIS metadata and used tables | Daily metadata check; selected values on demand | Invalidate cached slices on schema/data changes |
| TED and funding collections | Every few hours for configured searches | Date-bounded search with overlap |
| GovData queries | Cache for several hours | Refresh catalogue metadata on demand |

Do not run a full historic crawl every hour. Bootstrap a clearly stated recent period first, then backfill separately. Coverage must remain visible until a backfill completes.

### 8.3 Watermarks and feeds

Commit a watermark only after all records for that window have been persisted successfully. Store in-progress cursors separately. Overlap polling windows so delayed publications are not lost; de-duplicate by provider ID, version and content hash.

A local `observed_changed` event means the system observed a changed record. It does not prove the event occurred at the observation time. Preserve both times.

EP feeds have collection-specific windows and parameters. Do not assume all feeds support `since`, arbitrary historical windows or identical payload formats. DIP cursor behaviour also differs from offset pagination. [D2] [E2]

### 8.4 Pagination presented to the model

Wrap provider pagination in an opaque application cursor. Bind it to source, normalized query, version/snapshot, projection, language and authorization principal. Give search snapshots a proposed 30-minute lifetime.

The cursor must preserve leftover records when an upstream page is larger than the model-visible page. Otherwise, returning five items from an upstream page of 100 would silently skip 95 records.

For a local search, preserve a stable ordered result snapshot. For a live provider whose results can move, report consistency limitations and de-duplicate. An expired cursor returns `CURSOR_EXPIRED` with a restart hint, not an empty page.

### 8.5 Evidence extraction

Prefer published structured data, then HTML, then text-based PDF extraction. Use OCR only for genuinely image-only material, with an extraction-quality flag and human verification for exact quotations.

Store the unmodified original and the extracted version. Record page numbers, paragraph IDs, spreadsheet sheet/row positions or XML identifiers. A parser update must not overwrite the original evidence trail.

Create title/abstract and section-level lexical indices first. Optional local multilingual embeddings can supplement recall later. They must not replace exact identifiers, date filters or explicit relationships.

## 9. Source and capability registry

Keep this registry in version control. The runtime model receives filtered capability cards, not the full YAML.

```yaml
registry_version: 1
policy:
  no_fee_sources_only: true
  public_read_only: true
  default_search_limit: 5
  interactive_max_provider_requests: 6

sources:
  dip:
    adapter: DipAdapter
    transport: rest
    auth_env: DIP_API_KEY
    documentation: https://dip.bundestag.de/%C3%BCber-dip/hilfe/api
    intents: [procedure_search, procedure_get, parliamentary_metadata]
    scopes: [DE]
    topic_search: local_index
    native_changes: modification_filter
    enable_after: [schema_pin, authentication_test, pagination_test]

  ep:
    adapter: EuropeanParliamentAdapter
    transport: rest_jsonld
    documentation: https://data.europarl.europa.eu/api/v2
    intents: [procedure_search, procedure_get, parliamentary_records, actor_roles]
    scopes: [EU]
    topic_search: collection_specific
    native_changes: collection_specific_feeds
    enable_after: [schema_pin, collection_contract_tests]

  eu_transparency:
    adapter: TransparencySnapshotAdapter
    transport: published_download
    intents: [actor_search, interest_disclosures]
    scopes: [EU]
    topic_search: local_index
    native_changes: false
    enable_after: [distribution_resolution, schema_test, freshness_test]
```

Extend this pattern for all 14 planned adapters and the optional statute adapter. Each registry entry also needs:

```text
allowed_hosts
allowed_operations
credential_transport
request/response schema fixture hashes
licence and attribution policy
collection-specific date support
pagination implementation
refresh policy and freshness threshold
supported languages and fallback policy
known coverage limits
parser version
```

Generated HTTP clients may be useful internally, but they must not automatically publish every generated operation as an MCP tool. The registry must fail closed when an operation or required field disappears.

## 10. Reliability, safety and interpretation

### 10.1 HTTP and service behaviour

Proposed interactive defaults: five-second connect timeout, 20-second request timeout, 30-second total tool deadline and at most two retries for transient read failures. Respect `Retry-After`; use exponential backoff and jitter. Apply limits per upstream service and across all processes sharing an account.

Start unknown providers at one concurrent request. Do not infer permission for high request rates from the absence of a published limit. Keep interactive and ingestion quotas separate.

Check content type, response size and application-level error envelopes. XML, JSON and CSV endpoints may return an HTML error page. Handle 204 separately from a parsing failure. Do not retry invalid credentials or invalid queries indefinitely.

Typed application errors should include:

```text
AUTH_NOT_CONFIGURED | AUTH_REJECTED | SOURCE_UNAVAILABLE | RATE_LIMITED
UNSUPPORTED_CAPABILITY | UNSUPPORTED_FILTER | NOT_COVERED | NOT_FOUND
INVALID_REFERENCE | CURSOR_EXPIRED | SCHEMA_CHANGED | INDEX_WARMING
RESULT_TOO_LARGE | PARTIAL_RESULT | DOCUMENT_TEXT_UNAVAILABLE
```

Use a tool execution error for failed operations; reserve JSON-RPC errors for protocol problems. A partially successful multi-source call can return ordinary structured content with `status=partial`, source failures and usable evidence. Do not convert failure into `items=[]` without explanation.

### 10.2 Local host boundary and credentials

The primary client mode uses `stdio`. Claude Desktop, Claude Code, ChatGPT Desktop and Codex CLI launch the process locally. Do not open a listening TCP port for the default installation. Remote Streamable HTTP support may remain in the codebase for testing or a later hosted edition, but it is not part of the MVP install path. [O1]

Keep upstream API credentials separate from MCP tool arguments. Never accept DIP, Lobbyregister, GENESIS or EUR-Lex credentials as model-visible inputs. Never include secrets in resource contents, generated source URLs, traces or logs.

Use this credential order:

1. OS credential store through the local `policy-mcp configure` helper.
2. Host-provided environment variables for development and managed enterprise deployments.
3. No plaintext fallback in project files or plugin manifests.

Claude MCPB supports user configuration fields, including sensitive values, which may be mapped to the server environment. This is the easiest Claude Desktop onboarding route. [C2]

The Claude Code plugin must not embed upstream API keys in `.mcp.json` or `plugin.json`. The bundled executable should read the same OS credential store used by the desktop bundles. Environment-variable substitution is acceptable for development and managed deployments. [C3] [C4]

Agent Plugins v1 intentionally does not define a portable secret field for `mcp.json`; configured `env` and HTTP headers are visible package data and must not contain credentials. For the OpenAI package, run a small local setup helper that writes credentials to the OS credential store, then let the bundled MCP executable read them at startup. [O3]

Direct Codex development configuration may use `env_vars` to forward existing local environment variables. Do not hard-code keys in `config.toml`. [O1]

Authorize every reference, cursor and stored evidence lookup. An opaque ID is not authorization. Local search histories and watched topics can contain confidential client work even when the underlying documents are public.

### 10.3 Retrieval safety

The model may provide a reference, not an arbitrary URL. Adapters follow only allowlisted official hosts and validated source-provided links. Revalidate redirects and resolved addresses, disallow private-network destinations, and keep file-download limits separate from metadata limits.

For interactive retrieval, begin with a proposed 10 MiB response limit. Batch distribution limits must be configured per source. Set decompression, archive-entry and extraction-time limits. Disable external XML entities and untrusted DTD retrieval; use locally pinned DTDs where necessary. Cache or pin approved JSON-LD contexts instead of following arbitrary remote contexts.

Treat every document as untrusted data. Embedded instructions cannot modify tool selection, credentials, permissions or the assistant's system instructions. Preserve text for quotation, but do not execute scripts, formulas, macros or commands from it.

### 10.4 Research correctness

Preserve original labels and their source. Separate a documented fact, an inferred link and an analyst interpretation. Do not treat register membership, disclosed spending or an institutional role as proof of influence or a preferred political position.

For legal records, keep procedure stage, document version and legal effect separate. For votes, distinguish an amendment vote from a final vote. For statistics, retain denominator, units, population and period. For budgets, distinguish authorization from actual spending. For funding, distinguish a call from an awarded project.

Do not fabricate historical states from current records. Disclose an unavailable source, unindexed period or missing text before making a negative claim. Where sources conflict, return both dated records for the user to assess.

## 11. Implementation structure

```text
political-research-mcp/
  pyproject.toml
  uv.lock
  README.md
  .env.example
  src/policy_mcp/
    servers/
      legislation.py
      actors.py
      evidence.py
    contracts/
      inputs.py
      outputs.py
      errors.py
    services/
      routing.py
      references.py
      search.py
      excerpts.py
      datasets.py
      provenance.py
      budgets.py
    adapters/
      base.py
      dip.py
      bundestag_open_data.py
      de_lobbyregister.py
      ep.py
      eurlex.py
      cellar.py
      eu_whoiswho.py
      eu_transparency.py
      comitology.py
      govdata.py
      genesis.py
      de_budget.py
      ted.py
      funding_tenders.py
      gesetze_im_internet.py
    ingestion/
      scheduler.py
      manifests.py
      sync.py
      reconciliation.py
    storage/
      metadata.py
      document_store.py
      migrations/
  config/
    sources.yaml
    profiles/
      minimal.yaml
      full.yaml
  packaging/
    shared/
      skills/
        policy-research/
          SKILL.md
      assets/
      templates/
    claude-desktop/
      legislation/
        manifest.json
      actors/
        manifest.json
      evidence/
        manifest.json
    claude-code-plugin/
      .claude-plugin/
        plugin.json
      .mcp.json
      skills/
        policy-research/
          SKILL.md
      bin/
    openai-agent-plugin/
      plugin.json
      mcp.json
      skills/
        policy-research/
          SKILL.md
      assets/
      bin/
    marketplaces/
      claude/
        .claude-plugin/
          marketplace.json
      openai/
        .agents/
          plugins/
            marketplace.json
    installers/
      macos/
      windows/
  schemas/upstream/
  tests/
    fixtures/
    contract/
    routing/
    extraction/
    security/
    budgets/
    integration/
    packaging/
    evaluation/
```

Generate vendor-specific plugin trees from shared templates and payloads. Do not maintain three hand-edited copies of the same skill text, binary metadata or version number.

Suggested packages are the official `mcp` SDK, `httpx`, `pydantic`, a safe XML parser and format-specific parsers. Use standard-library SQLite initially. Add a SOAP client only for EUR-Lex. Pin dependencies, audit them and avoid adding a large agent framework merely to dispatch deterministic source calls.

Define adapter capabilities explicitly rather than requiring every source to implement every method:

```text
SourceAdapter
  capabilities() -> SourceCapabilities
  health() -> SourceHealth

SearchAdapter
  search(request, request_budget) -> ProviderPage

RecordAdapter
  get(provider_id, requested_view, request_budget) -> NormalizedRecord

DocumentAdapter
  resolve_document(provider_id, language, version) -> StoredDocumentRef

DatasetAdapter
  describe(dataset_id) -> DatasetSchema
  query(validated_slice, request_budget) -> NumericResult

IncrementalAdapter
  changes(window, cursor, request_budget) -> ProviderPage

SnapshotAdapter
  fetch_manifest() -> PublishedDistributionManifest
  ingest(distribution, ingestion_budget) -> IngestionReport
```

These are project interfaces, not upstream API methods. The MCP layer should remain thin: validate typed input, call a service, return a budgeted response.

### 11.1 Client packages

Build a single executable named `policy-mcp` and use `--profile` to select the exposed tool set. Keep all routing and adapter code in that executable. Client packages must not contain forks of the business logic.

Release the same runtime through three package families:

| Distribution | Hosts | Package contents | Normal install |
|---|---|---|---|
| Claude Desktop MCPB | Claude Desktop | One profile per `.mcpb`, bundled executable, manifest | Install extension in Claude Desktop |
| Claude Code plugin | Claude Code CLI | `.claude-plugin/plugin.json`, `.mcp.json`, shared executable, optional small skill | Claude plugin marketplace + install command |
| OpenAI Agent Plugin | ChatGPT Desktop, Codex CLI; also useful for Codex IDE | root `plugin.json`, `mcp.json`, shared executable, optional small skill, assets | OpenAI local/repo marketplace |

All packages must expose the same MCP server names and tool contracts. A host-specific package may add installation metadata or an optional skill, but it may not rename `leg_search`, change reference semantics or bypass the backend router.

#### Claude Desktop: MCP Bundles

Ship three MCPB artifacts built from the same executable:

```text
policy-legislation-<version>-<platform>.mcpb
policy-actors-<version>-<platform>.mcpb
policy-evidence-<version>-<platform>.mcpb
```

Each bundle declares a local binary server and launches the matching profile over `stdio`. Use the MCPB manifest's compatibility fields to restrict platform builds. Pin the MCPB manifest/toolchain version at release time rather than assuming the current draft stays unchanged. [C2]

Conceptual bundle layout:

```text
policy-legislation.mcpb
  manifest.json
  server/
    policy-mcp
```

The legislation bundle launches:

```text
policy-mcp serve --profile legislation
```

The other bundles only change the profile. Claude users install them through the Claude Desktop extension UI. [C1]

For a lower-friction first release, make `policy-legislation` the required bundle and the actor/evidence bundles optional. This lets a user install only the domains they need and avoids exposing unused tools.

#### Claude Code CLI: native plugin

Ship one Claude Code plugin containing all three profiles. Claude Code plugins can bundle MCP servers in `.mcp.json`, start them automatically when the plugin is enabled and manage them through the plugin lifecycle. [C3] [C4]

Conceptual package:

```text
policy-research/
  .claude-plugin/
    plugin.json
  .mcp.json
  skills/
    policy-research/
      SKILL.md
  bin/
    policy-mcp
```

Conceptual `.mcp.json`:

```json
{
  "mcpServers": {
    "policy-legislation": {
      "command": "${CLAUDE_PLUGIN_ROOT}/bin/policy-mcp",
      "args": ["serve", "--profile", "legislation"]
    },
    "policy-actors": {
      "command": "${CLAUDE_PLUGIN_ROOT}/bin/policy-mcp",
      "args": ["serve", "--profile", "actors"]
    },
    "policy-evidence": {
      "command": "${CLAUDE_PLUGIN_ROOT}/bin/policy-mcp",
      "args": ["serve", "--profile", "evidence"]
    }
  }
}
```

Distribute the plugin through a private or public Claude Code marketplace. A typical private/team install is:

```text
/plugin marketplace add <org-or-repo>
/plugin install policy-research@<marketplace-name>
/reload-plugins
```

Claude Code also provides non-interactive `claude plugin ...` commands for scripted deployment. [C5]

For development or recovery, bypass plugin packaging and register profiles directly:

```text
claude mcp add --transport stdio --scope user policy-legislation -- \
  /absolute/path/to/policy-mcp serve --profile legislation
```

Repeat for the other profiles. `.mcp.json` or `claude mcp add-json` are equivalent development paths. Claude Code can also import compatible MCP configurations from Claude Desktop on supported platforms, but do not make that import step the primary installer. [C3]

#### OpenAI: one Agent Plugin for ChatGPT Desktop and Codex CLI

Package the same executable as one portable Agent Plugin. Use root `plugin.json` plus `mcp.json`; include an optional `skills/` directory. OpenAI documents the portable package as a way to bundle skills and MCP servers, and local-marketplace plugin settings apply to supported local clients including Codex CLI and Codex in the ChatGPT desktop app. [O2] [O3]

Conceptual package:

```text
policy-research/
  plugin.json
  mcp.json
  skills/
    policy-research/
      SKILL.md
  assets/
  bin/
    policy-mcp
```

Conceptual `mcp.json`:

```json
{
  "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
  "mcpServers": {
    "policy-legislation": {
      "type": "stdio",
      "command": "./bin/policy-mcp",
      "args": ["serve", "--profile", "legislation"]
    },
    "policy-actors": {
      "type": "stdio",
      "command": "./bin/policy-mcp",
      "args": ["serve", "--profile", "actors"]
    },
    "policy-evidence": {
      "type": "stdio",
      "command": "./bin/policy-mcp",
      "args": ["serve", "--profile", "evidence"]
    }
  }
}
```

Build separate plugin artifacts per operating system/architecture when the executable differs. Do not depend on shell wrappers or an existing Python installation.

Use a local or Git-backed marketplace for private/team distribution. OpenAI's documented local layout uses a marketplace file at repo or user scope. For example, a personal setup can place the plugin under `~/.codex/plugins/` and reference it from `~/.agents/plugins/marketplace.json`. [O2]

For ChatGPT Desktop, the user-friendly path is to install the plugin from the Plugins Directory after adding/selecting the marketplace.

For Codex CLI, use the same marketplace source. The CLI can register marketplace sources with:

```text
codex plugin marketplace add <repo-or-local-marketplace>
```

Then enable the plugin through user or trusted-project configuration, for example:

```toml
[plugins."policy-research@policy-tools"]
enabled = true
```

The exact marketplace name in the key must match the published catalog. Keep this configuration out of the plugin package itself so teams can choose user or project scope. OpenAI documents the same local-marketplace plugin system for Codex CLI and the ChatGPT desktop Codex host. [O2]

The OpenAI Agent Plugin is therefore the **single normal distribution artifact for both ChatGPT Desktop and Codex CLI**. Do not maintain a separate Codex-specific fork.

#### Direct OpenAI MCP registration: development and recovery fallback

During development, skip plugin packaging and add each profile directly in ChatGPT Desktop or through Codex CLI. OpenAI documents that ChatGPT Desktop, Codex CLI and the IDE extension share MCP configuration for the same Codex host. [O1]

CLI example:

```text
codex mcp add policy-legislation -- \
  /absolute/path/to/policy-mcp serve --profile legislation
```

A direct `config.toml` fallback looks like:

```toml
[mcp_servers.policy-legislation]
command = "/absolute/path/to/policy-mcp"
args = ["serve", "--profile", "legislation"]
enabled = true

[mcp_servers.policy-actors]
command = "/absolute/path/to/policy-mcp"
args = ["serve", "--profile", "actors"]
enabled = true

[mcp_servers.policy-evidence]
command = "/absolute/path/to/policy-mcp"
args = ["serve", "--profile", "evidence"]
enabled = true
```

Use direct config for developers, troubleshooting and installations where plugins are administratively disabled. The normal non-technical OpenAI experience should remain the Agent Plugin.

#### Optional shared `policy-research` skill

Both plugin families may include a small skill with the same workflow text. Generate the vendor-specific wrappers from one source file. The skill should explain only domain selection and the search-then-fetch pattern. Do not duplicate endpoint catalogs, API schemas or adapter documentation in the skill.

The skill is optional for three reasons:

1. MCP clients differ in how and when skills are loaded.
2. Tool descriptions must remain sufficient for routing on their own.
3. Loading a large skill would defeat the project's context-efficiency goal.

Set a CI target of at most 400 tokens for the shared skill body. Measure the actual rendered form in each host before release.

#### Local data and concurrent hosts

Default to an OS-standard user data directory resolved by the executable, for example through `platformdirs`, rather than storing indexes inside an extension/plugin package. Package locations may be read-only or replaced during updates.

All three profiles and all four clients may use the same SQLite database. Enable WAL mode, set busy timeouts and serialize ingestion jobs with an inter-process lock. Multiple read-heavy MCP processes are expected. Do not let each host create a separate full corpus unless isolation is explicitly requested.

Store downloaded source documents and indexes outside package directories. Package upgrades must leave user data and credentials intact.

#### Installation helper

Provide a small non-model-facing command:

```text
policy-mcp configure
policy-mcp doctor --client claude-desktop
policy-mcp doctor --client claude-code
policy-mcp doctor --client chatgpt-desktop
policy-mcp doctor --client codex-cli
```

`configure` writes upstream credentials to the OS credential store and validates them with low-volume requests. `doctor` checks the executable, data directory, database access, source credentials and the expected client registration. It must never print secrets.

### 11.2 Configuration and operations

Use `.env.example` placeholders such as `DIP_API_KEY`, `LOBBYREGISTER_API_KEY`, `GENESIS_TOKEN`, `EURLEX_USERNAME` and `EURLEX_PASSWORD`. Do not copy public sample keys into source control; their validity can change.

Add non-model-facing operator commands:

```text
policy-mcp doctor
policy-mcp sync --source SOURCE --scope CONFIGURED_SCOPE
policy-mcp backfill --source SOURCE --from DATE --to DATE
policy-mcp verify-schemas
policy-mcp evaluate-routing
policy-mcp measure-tool-tokens --profile minimal
```

These command names are proposed implementation tasks, not existing software. Keep administrative refresh, backfill and configuration actions out of the research model's tool list.

## 12. Delivery sequence

### Milestone 0: prove all client package paths

Before implementing the full source set, build one `policy-mcp` executable with a trivial read-only diagnostic tool and package it through every supported distribution path:

- **Claude Desktop:** install a local `.mcpb` and verify `stdio` launch, tool discovery, update and uninstall.
- **Claude Code CLI:** install the Claude Code plugin from a test marketplace; verify its three bundled MCP entries start automatically and `/mcp` identifies them as plugin-provided servers.
- **ChatGPT Desktop:** install the OpenAI Agent Plugin from a personal/local marketplace; verify all three `stdio` servers and the optional small skill.
- **Codex CLI:** use the same OpenAI marketplace/plugin; verify the enabled plugin is available in CLI sessions without creating a second package.
- **Direct fallbacks:** verify `claude mcp add` and `codex mcp add` against the same binary for support scenarios.
- Verify upgrades in all package paths without deleting the shared local data directory or credential store.
- Compare host-visible tool definitions and one diagnostic result across all four clients; packaging must not change the MCP contract.

Exit criteria: a non-developer can install the desktop package through the relevant extension/plugin UI, and a CLI user can install or enable the corresponding plugin without editing source code or installing a language runtime.

### Milestone 1: contracts and one working research path

Implement the three server entrypoints, shared models, references, response budgets and source health. Build DIP procedure ingestion, local topic search, procedure detail and a cited document passage. Connect only `policy-legislation` initially.

Exit criteria: a user can find a procedure, inspect its timeline and read the supporting paragraph without receiving a raw API page or guessing an endpoint. Partial coverage is visible.

### Milestone 2: EU procedure and document retrieval

Implement EP collection-specific routing and metadata ingestion, native speech search and CELLAR identifier/file retrieval. Add EUR-Lex SOAP when the free account is approved. Test language and version handling.

Exit criteria: EU procedure search does not rely on an invented EP full-text parameter. The user can retrieve a cited passage from a linked file.

### Milestone 3: actors and disclosures

Complete the German register contract gate. Add register indexing, selected disclosure views, EU register snapshots and WhoisWho queries. Share the EP adapter for parliamentary roles.

Exit criteria: documented relationships have evidence and dates. Candidate matches stay labelled as candidates. Missing historical records return a limitation rather than a reconstructed biography.

### Milestone 4: structured German records and legal texts

Add Bundestag speech/vote parsing. Add the optional Gesetze im Internet adapter before advertising consolidated German-law coverage.

Exit criteria: a speech excerpt retains speaker/agenda context; a roll-call record identifies the actual vote. Statutes and proposed amendments remain distinct objects.

### Milestone 5: quantitative and financial evidence

Implement GovData discovery, GENESIS describe/query, federal budget ingestion, TED search and Funding & Tenders collections. Complete the distribution and serialization gates first.

Exit criteria: numeric answers preserve units and periods. Unsupported catalogue resources cannot be queried as if they were already integrated datasets. Calls, awards and budget stages remain distinguishable.

### Milestone 6: implementation documents and operational checks

Add the Comitology datasets, source reconciliation, schema-drift checks, backups and client interoperability tests. Run the evaluation suite against the actual host.

Exit criteria: all advertised source routes have passing contract tests, bounded outputs, visible freshness and a recovery path. A source can be disabled without changing the meaning of the other tools.

Do not equate "adapter class exists" with "source integrated". Integration requires successful retrieval, normalization, provenance, pagination, error handling and a tested model-facing route.

## 13. Acceptance and evaluation

### 13.1 Test sets

Create a versioned evaluation set of 60 prompts, initially proposed as 20 legislation, 15 actors, 15 evidence and 10 unsupported/ambiguous cases. Use both German and English. Keep fixtures frozen for deterministic tests and run small live contract checks separately.

| Test | Expected behaviour |
|---|---|
| German procedure by topic | DIP/local index, not an EU-wide broadcast |
| EU procedure by identifier | Exact EP or identifier-linked legal lookup |
| EU speech mentioning a phrase | Supported speech text search, bounded date scope |
| German roll-call question | Actual vote record; no inference from party membership |
| Organisation's disclosed regulatory interests | Register fields with attribution and version |
| Current institutional role | Dated role record, not a timeless claim |
| Role at a historical date without archive | Explicit historical-coverage limitation |
| Official numeric evidence | Describe dimensions before requesting unknown selections |
| Spending question with only a budget draft | Draft label retained; no claim of actual spending |
| EU funded project request | Project collection, not merely an open call |
| Unsupported Land parliament | Clear scope limitation |
| Unavailable register distribution | Source failure, not "no organisations found" |
| Prompt injection in a document | Treated as quoted data; no extra permissions |
| Search page larger than output budget | No skipped records when continuing |

### 13.2 Metrics and release targets

These are proposed targets, not current results:

| Metric | Initial release target |
|---|---|
| Correct first tool on unambiguous evaluation questions | At least 95% |
| Requests to undocumented operations | Zero |
| Unsupported source/date scopes silently treated as complete | Zero |
| Evidence-bearing facts without source reference | Zero in deterministic output validation |
| Secret exposure in outputs and logs | Zero |
| Simple search-to-evidence task | Usually 2-3 model-visible calls |
| Token-budget compliance | 100%, or a typed oversized-result response |
| Pagination duplicates/skips in frozen fixtures | Zero |
| Citation/quotation locator accuracy | Human-reviewed sampled checks before release |

Evaluate retrieval recall separately from token count. A smaller response that omits the relevant document is not an improvement.

Compare the proposed design with an internal endpoint-per-tool baseline on the same questions. Measure tool definitions, discovery calls, returned content, duplicated structured/text content, latency and answer evidence quality. Do not claim a token-saving percentage until this comparison exists.

### 13.3 Contract tests by source

Every enabled source needs a low-volume test for its actual supported operations: authentication, one search/list, one selected record, continuation, language handling, malformed/empty response and schema validation. Download adapters instead need manifest, file, parser, freshness and replacement-version tests.

Run these on a schedule independent of user conversations. Alert the operator on schema drift, expired keys, stale distributions and prolonged failures. Never run a full historical backfill as a health check.

### 13.4 Client package acceptance

Release automation must test the actual packaged artifacts, not only the Python source tree.

| Check | Claude Desktop | Claude Code CLI | ChatGPT Desktop | Codex CLI |
|---|---|---|---|---|
| Fresh install without Python/Node | Required | Required | Required | Required |
| Primary package path | `.mcpb` | Claude Code plugin | OpenAI Agent Plugin | Same OpenAI Agent Plugin |
| Local `stdio` process starts | Required | Required | Required | Required |
| Three profiles expose only intended tools | Required | Required | Required | Required |
| Tool names/schemas match cross-client snapshot | Required | Required | Required | Required |
| Optional skill stays below its token budget | N/A unless separately packaged | Required if shipped | Required if shipped | Required if shipped |
| Upstream credentials absent from manifests/config | Required | Required | Required | Required |
| Missing credential produces actionable local error | Required | Required | Required | Required |
| Update preserves database and credential store | Required | Required | Required | Required |
| Disable/uninstall does not delete user data unless explicitly requested | Required | Required | Required | Required |
| Direct-MCP support fallback works | Optional | Required | Required | Required |
| macOS signing / Gatekeeper smoke test | Required for macOS build | Required for macOS build | Required for macOS build | Required for macOS build |
| Windows signing / SmartScreen smoke test | Required for Windows build | Required for Windows build | Required for Windows build | Required for Windows build |

Also test simultaneous read-only use from two or more local hosts against the shared SQLite store. For example, a Claude Code process and a Codex CLI process must not corrupt the index or block each other under normal research load.

Add a **cross-client contract snapshot** to CI. For each profile, start the packaged server from every client artifact and compare:

- MCP protocol initialization succeeds;
- tool names and JSON Schemas are identical;
- tool annotations are identical where the host supports them;
- a fixed fixture query produces the same normalized structured result;
- model-visible instructions added by plugins do not duplicate the full tool descriptions.

## 14. Example request flows and developer smoke checks

### 14.1 Model call flows

The examples below show request shapes only. References are placeholders for values returned by earlier calls, not real research findings.

German legislative research:

```text
leg_search(jurisdiction="DE", kind="procedure", query="data centres", limit=5)
leg_procedure(ref="<returned procedure ref>", view="overview")
leg_read(ref="<returned document ref>", view="excerpt", query="reporting obligation")
```

EU speech research:

```text
leg_records(jurisdiction="EU", kind="speech", query="energy efficiency",
            date_from="2026-09-01", date_to="2026-09-16", language="en")
leg_read(ref="<returned speech document ref>", view="excerpt", query="energy efficiency")
```

Disclosed interests connected to a procedure:

```text
actor_interests(scope="DE", procedure_ref="<returned procedure ref>", limit=5)
actor_get(ref="<returned organisation ref>", view="disclosures")
```

Statistical evidence:

```text
 evidence_search(kind="statistics", scope="DE", query="industrial electricity prices")
 evidence_describe(ref="<returned dataset ref>")
 evidence_query(ref="<same dataset ref>", schema_version="<returned schema version>",
                selections=[{"dimension_id":"<returned code>",
                             "member_ids":["<returned member code>"]}],
                row_limit=10)
```

The application may normalize known English topic aliases for German metadata retrieval. Make query expansion explicit in debug traces; do not assume an English phrase is a documented upstream semantic-search capability.

### 14.2 Documentation-derived smoke requests

These are development checks to run in an environment with network access. They were **not successfully executed during this research**. They are not model-facing tools.

DIP metadata, using the documented header scheme and filter:

```bash
: "${DIP_API_KEY:?Set a valid free DIP API key}"
curl --fail-with-body --silent --show-error --get \
  'https://search.dip.bundestag.de/api/v1/vorgang' \
  --header "Authorization: ApiKey ${DIP_API_KEY}" \
  --data-urlencode 'f.aktualisiert.start=2026-09-01T00:00:00+02:00' \
  --data-urlencode 'format=json'
```

GovData catalogue metadata:

```bash
curl --fail-with-body --silent --show-error --get \
  'https://www.govdata.de/ckan/api/3/action/package_search' \
  --data-urlencode 'q=Energie' \
  --data-urlencode 'rows=1' \
  --data-urlencode 'start=0'
```

GENESIS table discovery, following the 2026 manual's POST/header convention:

```bash
: "${GENESIS_TOKEN:?Set a personal GENESIS API token}"
curl --fail-with-body --silent --show-error \
  'https://genesis.destatis.de/genesisWS/rest/2020/find/find' \
  --header "username: ${GENESIS_TOKEN}" \
  --header 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode 'term=Energie' \
  --data-urlencode 'category=tables' \
  --data-urlencode 'pagelength=5' \
  --data-urlencode 'language=en'
```

After each request, inspect the source's own success/error envelope, save a redacted fixture and verify the expected schema. Do not include returned credentials or full personal records in a public test repository. Check the actual curl version's flag support in the development environment.

For EP and TED, generate smoke requests from their pinned OpenAPI operations and tested field definitions. For Lobbyregister, complete its YAML verification gate before writing the authentication/request fixture. For EUR-Lex, use the approved account's WSDL. This is preferable to publishing guessed request bodies.

## 15. Open checks and excluded assumptions

| Check | Why it remains open | Required implementation action |
|---|---|---|
| Lobbyregister search/auth/paging details | YAML retrieval failed here; endpoint list was documented | Download official schema, inspect security and parameters, record fixtures |
| Funding & Tenders collection serialization | Official dynamic page did not render consistently | Capture official request examples and validate each selected collection |
| Exact budget and Comitology download URLs | Dataset families verified, distribution bytes not inspected | Resolve published URLs; validate files and manifests |
| EU register distribution freshness/schema | Catalogue includes legacy text; no current dump parsed | Check actual distribution timestamp and parse a current snapshot |
| EP historical coverage and linked vote/text content | Collection-specific schema details do not prove complete coverage | Test representative periods and file resolution |
| Upstream throttling | No load tests performed; many providers publish no fixed request rate | Conservative defaults, error-aware backoff, operator configuration |
| MCP host token behaviour | Tool-schema and plugin/skill loading differ by host and version | Measure Claude Desktop, Claude Code, ChatGPT Desktop and Codex CLI separately; do not infer savings from server count alone |
| Claude MCPB packaging | Package format is supported, but the final binary/runtime choice is not tested | Build signed macOS/Windows bundles and verify install/update/uninstall |
| Claude Code plugin packaging | Plugin-provided MCP servers and marketplaces are documented, but this binary package is not tested | Test marketplace install, automatic MCP startup, reload/update/uninstall and `${CLAUDE_PLUGIN_ROOT}` paths |
| OpenAI Agent Plugin local MCP packaging | Portable `stdio` packaging and local-marketplace support are documented for local OpenAI clients | Test one plugin artifact in both ChatGPT Desktop and Codex CLI, including update and enable/disable behaviour |
| OpenAI MCP config sharing | OpenAI currently documents ChatGPT Desktop, Codex CLI and IDE as sharing MCP configuration for the same Codex host | Pin tested app versions in release notes and rerun interoperability tests on updates |
| Full legal-history answers | Current sources and future snapshots are insufficient for all past dates | Explicitly bounded coverage or a separately verified archive |

Do not claim complete coverage of the EU legislative process merely because EP and EUR-Lex are integrated. Council materials, consultations, ministry drafts and other early-stage documents can require additional sources.

The earlier discussion mentioned **Have Your Say** and the **Council public register**. They remain explicit extension candidates rather than fabricated REST integrations. The Council has published documentation for linked open datasets, including register metadata, so "no modern REST API verified" should not be rewritten as "no machine-readable access exists". Validate the currently available dataset/service and its document-access limits before adding it. [X1] [X2] [X3]

The first implementation should complete a few research paths, prove routing and evidence quality, then enable the remaining adapters as their gates pass. Do not connect an unvalidated source merely to make the source list appear complete.

## 16. Official documentation register

All references below are official publishers or maintainers. URLs were consulted or surfaced in their official documentation during this research; accessibility in the deployment environment still requires verification.

| Ref | Publisher / document | What to use it for |
|---|---|---|
| M1 | [MCP tools specification][M1] | Tool definitions, discovery, results and annotations |
| M2 | [MCP 2026-07-28 changelog][M2] | Lifecycle, statelessness and compatibility changes |
| M3 | [Official Python SDK README][M3] | Current SDK line and migration links |
| M4 | [MCP resources specification][M4] | Resource discovery and application-controlled context |
| M5 | [MCP authorization specification][M5] | Remote host-to-server authorization |
| C1 | [Claude local MCP / Desktop Extensions][C1] | Installing local `.mcpb` extensions in Claude Desktop |
| C2 | [MCP Bundles specification and toolchain][C2] | MCPB package layout, manifest, local binary/runtime configuration |
| C3 | [Claude Code MCP documentation][C3] | Local `stdio` MCP configuration, `claude mcp`, plugin-provided MCP servers |
| C4 | [Claude Code plugin authoring][C4] | Plugin structure and bundling MCP servers/skills |
| C5 | [Claude Code plugin installation and marketplaces][C5] | Marketplace distribution, install/update/reload and scopes |
| O1 | [OpenAI Codex MCP documentation][O1] | ChatGPT Desktop local MCP setup, shared Codex configuration, `stdio` and `config.toml` |
| O2 | [OpenAI plugin packaging][O2] | Local marketplaces, plugin structure and bundled MCP server packaging |
| O3 | [Agent Plugins 1.0 specification][O3] | Portable `mcp.json`, bundled `stdio` executable rules, plugin paths and secret constraints |
| D1 | [DIP API help][D1] | Keys and supported entities |
| D2 | [DIP short technical guide][D2] | Header, pagination and operational guidance |
| D3 | [DIP OpenAPI YAML][D3] | Exact per-operation schema; authoritative over the older short guide |
| D4 | [DIP Swagger UI][D4] | Interactive schema inspection |
| D5 | [Bundestag Open Data][D5] | Published documents, master data, votes and DTD links |
| D6 | [Bundestag plenary records][D6] | Publication context and document links |
| D7 | [Gesetze im Internet notes][D7] | XML, contents list, DTD and legal-status distinctions |
| A1 | [German Lobbyregister Open Data/API][A1] | Access and schema entrypoint |
| A2 | [Lobbyregister Swagger v2][A2] | Endpoint list and request inspection |
| A3 | [Lobbyregister v2 YAML][A3] | Required schema-verification gate |
| A4 | [EU Transparency Register dataset][A4] | Official downloadable distributions |
| E1 | [EP API developer page][E1] | API entrypoint and documentation |
| E2 | [EP OpenAPI JSON][E2] | Exact collection capabilities and limits |
| E3 | [EUR-Lex webservice help][E3] | Registration, SOAP search and retrieval limits |
| E4 | [CELLAR documentation][E4] | Dissemination and model documentation |
| E5 | [CELLAR knowledge-graph examples][E5] | SPARQL, legal metadata and WhoisWho queries |
| E6 | [EU WhoisWho][E6] | Official institutional directory |
| E7 | [Comitology reusable datasets][E7] | CSV distribution families |
| E8 | [Comitology dataset catalogue][E8] | Collection purpose and publisher |
| S1 | [GENESIS manual, June 2026][S1] | POST, credentials, methods, response envelopes |
| S2 | [Destatis API/access information][S2] | Free access and attribution licence |
| S3 | [GovData interfaces][S3] | CKAN and SPARQL endpoints |
| S4 | [CKAN API guide][S4] | Catalogue action contracts |
| S5 | [Federal budget download portal][S5] | Published files and reuse notice |
| S6 | [BMF budget dataset overview][S6] | Additional official budget metadata |
| F1 | [TED Search API][F1] | Public search operation |
| F2 | [TED OpenAPI][F2] | Body, fields, pagination and limits |
| F3 | [TED API access documentation][F3] | Search API authentication exception |
| F4 | [TED download guidance][F4] | Search-based notice retrieval |
| F5 | [Funding & Tenders APIs][F5] | Public corporate-search requests and examples |
| X1 | [Have Your Say][X1] | Future consultation-source investigation |
| X2 | [Council document access][X2] | Future register-source investigation |
| X3 | [Council open-dataset explanation][X3] | Evidence of machine-readable register datasets; validate current access |

[M1]: https://modelcontextprotocol.io/specification/2026-07-28/server/tools
[M2]: https://modelcontextprotocol.io/specification/2026-07-28/changelog
[M3]: https://github.com/modelcontextprotocol/python-sdk/blob/main/README.md
[M4]: https://modelcontextprotocol.io/specification/2026-07-28/server/resources
[M5]: https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization
[C1]: https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop
[C2]: https://github.com/modelcontextprotocol/mcpb
[C3]: https://code.claude.com/docs/en/mcp
[C4]: https://code.claude.com/docs/en/plugins
[C5]: https://code.claude.com/docs/en/discover-plugins
[O1]: https://developers.openai.com/codex/mcp
[O2]: https://developers.openai.com/plugins/build/plugins
[O3]: https://agent-plugins.org/specification
[D1]: https://dip.bundestag.de/%C3%BCber-dip/hilfe/api
[D2]: https://dip.bundestag.de/documents/informationsblatt_zur_dip_api.pdf
[D3]: https://search.dip.bundestag.de/api/v1/openapi.yaml
[D4]: https://search.dip.bundestag.de/api/v1/swagger-ui/
[D5]: https://www.bundestag.de/services/opendata
[D6]: https://www.bundestag.de/dokumente/protokolle/
[D7]: https://www.gesetze-im-internet.de/hinweise.html
[A1]: https://www.lobbyregister.bundestag.de/informationen-und-hilfe/open-data-1049716
[A2]: https://api.lobbyregister.bundestag.de/rest/v2/swagger-ui/
[A3]: https://api.lobbyregister.bundestag.de/rest/v2/R2.21-de.yaml
[A4]: https://data.europa.eu/data/datasets/transparency-register?locale=en
[E1]: https://data.europarl.europa.eu/en/developer-corner/opendata-api
[E2]: https://data.europarl.europa.eu/api/v2
[E3]: https://eur-lex.europa.eu/content/help/data-reuse/webservice.html
[E4]: https://op.europa.eu/en/web/cellar/documentation
[E5]: https://op.europa.eu/en/web/cellar/cellar-data/metadata/knowledge-graph
[E6]: https://op.europa.eu/en/web/who-is-who/
[E7]: https://ec.europa.eu/transparency/comitology-register/screen/datasets?lang=en
[E8]: https://data.europa.eu/data/datasets/comitology-register?locale=en
[S1]: https://genesis.destatis.de/datenbank/online/docs/GENESIS-Webservices_Introduction.pdf
[S2]: https://www.destatis.de/DE/Service/OpenData/genesis-api-webservice-oberflaeche.html
[S3]: https://www.govdata.de/sparql-assistent
[S4]: https://docs.ckan.org/en/2.11/api/index.html
[S5]: https://www.bundeshaushalt.de/DE/Download-Portal/download-portal.html
[S6]: https://www.bundesfinanzministerium.de/Datenportal/Daten/offene-daten/haushalt-oeffentliche-finanzen/s05-bundeshaushalt-Gesamtuebersicht/s05-bundeshaushalt-Gesamtuebersicht.html
[F1]: https://docs.ted.europa.eu/api/latest/search.html
[F2]: https://ted.europa.eu/api/documentation/api-docs
[F3]: https://docs.ted.europa.eu/api/latest/index.html
[F4]: https://docs.ted.europa.eu/ODS/latest/reuse/search-api.html
[F5]: https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/support/apis
[X1]: https://ec.europa.eu/info/law/better-regulation/
[X2]: https://www.consilium.europa.eu/de/documents/
[X3]: https://www.consilium.europa.eu/media/29364/understanding-open-data-datasets.pdf
