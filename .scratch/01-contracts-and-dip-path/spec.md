# Contracts and one working German legislation path

Status: ready-for-agent

## Problem statement

A researcher cannot yet find a German federal legislative procedure, inspect its recorded timeline, or read a supporting passage through a compact and traceable MCP workflow. Direct exposure of DIP endpoints would force the model to understand provider parameters, pagination, and document formats, while a large generic tool would hide validation and source limits.

## Solution

Implement the shared MCP contracts, storage boundaries, deterministic router, reference system, response budgets, and the first complete legislation path backed by DIP. The user searches a local metadata index, selects an opaque reference, inspects procedure detail, and reads a bounded cited passage. Every result reports freshness and incomplete coverage.

## User stories

1. As a researcher, I want to search German federal procedures by topic, so that I can discover relevant work without knowing a DIP identifier.
2. As a researcher, I want to search by a known identifier, so that I can resolve an exact procedure without a broad topic query.
3. As a researcher, I want search results to be small metadata cards, so that I can choose evidence without loading full records.
4. As a researcher, I want each card to contain a stable opaque reference and official source URL, so that later calls and citations resolve to the same record.
5. As a researcher, I want a procedure overview, so that I can see the provider's recorded status without the system reinterpreting it.
6. As a researcher, I want a dated timeline, so that I can distinguish procedure events from document publication dates.
7. As a researcher, I want linked documents listed separately from the procedure, so that drafts, positions, and resulting acts are not merged.
8. As a researcher, I want to read an outline or a bounded passage from a selected document, so that the model receives only relevant evidence.
9. As a researcher, I want passages to retain headings and paragraph or page locators, so that quotations can be checked.
10. As a researcher, I want coverage and freshness returned with results, so that an empty search is not mistaken for proof that nothing exists.
11. As a German-speaking researcher, I want German output by default while retaining source wording, so that the result fits the source corpus.
12. As an English-speaking researcher, I want supported English labels without a false claim of semantic translation coverage, so that I understand what was normalized.
13. As a user, I want invalid date bases and unsupported filters rejected, so that a silently ignored argument cannot distort the answer.
14. As a user, I want result continuation without skipped records, so that a small model-visible page does not lose the rest of a larger provider page.
15. As a user, I want expired cursors to return a restart instruction, so that an empty page cannot hide lost state.
16. As a security reviewer, I want references and cursors bound to the requesting principal and query, so that opaque identifiers do not become an authorization bypass.
17. As an operator, I want a source health view, so that missing credentials, warming indexes, and provider outages are distinct conditions.
18. As a maintainer, I want all tool inputs generated from typed models, so that JSON Schemas and runtime validation cannot drift.
19. As a maintainer, I want raw DIP responses and normalized records versioned separately, so that parser changes do not erase the evidence trail.
20. As a maintainer, I want incremental DIP ingestion by source modification time, so that refreshes do not recrawl the entire corpus.
21. As an analyst, I want a relation to carry evidence and a declared basis, so that a text match cannot silently become a documented fact.
22. As a user, I want typed errors for unavailable, unsupported, partial, and oversized results, so that failures remain actionable.
23. As a user, I want every tool to be read-only and idempotent with respect to upstream systems, so that research cannot modify public records.
24. As a maintainer, I want the server to support the current MCP revision and one required legacy client, so that supported hosts can initialize without custom wire handling.

## Implementation decisions

- The legislation server exposes six stable tools: search, procedure detail, parliamentary records, document reading, change listing, and capabilities. This milestone fully implements search, procedure detail, document reading, and filtered capability reporting for DIP-backed paths.
- The MCP layer stays thin. It validates typed inputs, calls application services, and returns a budgeted common response envelope with structured content and a compact text fallback.
- Tool schemas reject additional properties. Search limits default to five and allow at most ten.
- German legislative search requires an explicit jurisdiction and exactly one of a topic query or identifier.
- A deterministic registry maps intent and jurisdiction to an adapter. Interactive calls do not broadcast across every source.
- Internal references are opaque and distinct from provider identifiers. References encode no authority and must pass authorization checks on every lookup.
- Provider statuses and labels are preserved. The application does not invent a normalized legal state that the source did not publish.
- SQLite with FTS5 stores metadata, versions, relations, sections, dataset metadata, sync state, and stable search snapshots. A filesystem document store holds immutable originals and normalized derivatives.
- Storage is accessed through interfaces so a later multi-user deployment can replace SQLite and the filesystem without changing tool contracts.
- DIP topic search uses a local index over titles, abstracts, subject descriptors, and document references. The adapter never sends invented full-text parameters upstream.
- DIP ingestion uses documented modification timestamps, overlapping windows, provider identifiers, version identifiers, and content hashes.
- Provider pagination is wrapped in an opaque application cursor. Search snapshots retain leftovers from larger upstream pages and expire after a configured lifetime.
- A document outline is the safe default when no excerpt query or section is supplied. Excerpts honor whole passage boundaries and include enough surrounding text to preserve qualifications.
- Response trimming removes optional metadata or whole cards before it removes provenance, warnings, units, or contradictory evidence.
- Credentials come from the OS credential store or forwarded development environment. They never appear in MCP arguments, resources, URLs, logs, or error text.
- HTTP defaults use bounded connect, request, and total deadlines, conservative concurrency, at most two transient retries, and `Retry-After` support.
- The adapter allowlists official hosts, validates redirects, limits downloads and decompression, and treats retrieved documents as untrusted data.
- The official Python MCP SDK v2 is used. The implementation resolves and locks an exact tested patch release rather than treating a broad dependency range as the release artifact.

## Testing decisions

- The highest test seam is a real local legislation MCP server called through MCP with frozen DIP and document fixtures. Tests assert externally visible tool results, errors, cursors, budgets, and provenance rather than service call order.
- Contract snapshots cover all six legislation tool schemas, descriptions, annotations, and serialized size.
- A complete path test performs topic search, procedure detail, and passage reading without exposing a raw provider page.
- DIP adapter contract tests cover authentication, metadata, detail, multi-position procedures, a Bundesrat-linked record, provider cursor exhaustion, and modification-window ingestion.
- Pagination tests use an upstream page larger than the model-visible page and prove that continuation neither skips nor duplicates records.
- Versioning tests retain the original object, normalized record, parser version, source timestamp, and retrieval timestamp across an update.
- Excerpt tests preserve headings, locators, negations, exceptions, and continuation boundaries.
- Security tests cover forged references, modified cursors, unauthorized principals, arbitrary URLs, redirects to private addresses, oversized responses, hostile XML, and prompt injection in a retrieved document.
- Budget tests use the actual serialized host-visible tool schemas and result payloads. Oversized mandatory content returns a typed error instead of malformed truncation.
- Protocol tests cover the current MCP revision and one required legacy revision through the SDK.
- Small live DIP checks run separately from deterministic fixtures and never gate local unit runs on network availability.
- There is no application test suite to copy. The implementation plan's request flow and DIP acceptance cases become the first end-to-end fixtures.

## Out of scope

- EU procedures, legal texts, speeches, and documents.
- Actor, disclosure, statistics, budget, procurement, and funding tools.
- Bundestag speech XML and roll-call spreadsheet parsing.
- Consolidated German statutes.
- A complete historical DIP backfill or claims of Land parliament coverage.
- Hosted MCP transport and multi-user authorization infrastructure.

## Further notes

This milestone establishes the contracts that later adapters must reuse. A source adapter is not integrated merely because a class exists. The route is enabled only after retrieval, normalization, provenance, pagination, errors, and the model-facing path pass together.
