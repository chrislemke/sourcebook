# Implementation documents, operations, and release readiness

Status: ready-for-agent

## Problem statement

The product is not ready when adapter classes merely exist. Every advertised route needs tested retrieval, normalization, provenance, freshness, bounded responses, and recovery behavior. The remaining Comitology collections, schema drift, background ingestion, backups, routing evaluation, and packaged cross-client tests must work together before the system can make reliable coverage claims.

## Solution

Integrate the documented Comitology dataset families, complete incremental sync and reconciliation, add operator commands and source health checks, run the versioned routing and evidence evaluation suite, and release only from tested packaged artifacts. Make source failure and incomplete backfill visible without changing the meaning of healthy tools.

## User stories

1. As a researcher, I want to find EU implementation committee documents, so that I can inspect draft measures, agendas, votes, and summary records linked by published identifiers.
2. As a researcher, I want draft measures, committee meetings, votes, and final acts kept separate, so that implementation stages are not collapsed.
3. As a researcher, I want unsupported attachment formats returned as metadata-only results, so that missing text is explicit.
4. As a researcher, I want source coverage dates and backfill state visible, so that recent bootstrap data is not mistaken for a complete archive.
5. As a user, I want `no_matches`, `not_covered`, `not_configured`, and temporary failure to remain distinct, so that an empty result never hides a source problem.
6. As a user, I want a partially successful multi-source result to retain usable evidence and name failed sources, so that one outage does not erase the answer.
7. As a user, I want stable continuation across local result snapshots, so that refreshes do not skip or duplicate records during research.
8. As a user, I want source conflicts returned as dated evidence, so that the system does not silently choose a preferred record.
9. As an operator, I want a doctor command, so that executable, storage, credential, index, and client-registration failures are diagnosed without secrets.
10. As an operator, I want targeted sync and backfill commands, so that administrative work stays outside model-facing tools.
11. As an operator, I want schema verification, so that an upstream contract change disables only the affected route and produces an actionable alert.
12. As an operator, I want watermarks committed only after a complete window persists, so that a failed sync cannot skip records.
13. As an operator, I want overlapping polling windows and hash de-duplication, so that delayed publications are captured without duplicate versions.
14. As an operator, I want ingestion serialized across local processes, so that two clients cannot run conflicting refresh jobs.
15. As an operator, I want backups and recovery checks for metadata, document files, and sync state, so that local research state can be restored.
16. As a maintainer, I want a versioned 60-prompt bilingual evaluation set, so that routing, unsupported cases, and evidence quality are measured consistently.
17. As a maintainer, I want correct first-tool selection measured separately from retrieval recall, so that small responses do not hide missed evidence.
18. As a maintainer, I want tool-schema and complete-turn token measurements on real hosts, so that context-efficiency claims use observed payloads.
19. As a maintainer, I want scheduled low-volume contract checks, so that expired keys, stale downloads, and schema drift are found outside user conversations.
20. As a release engineer, I want final artifacts tested rather than only the source tree, so that bundling failures block release.
21. As a release engineer, I want cross-client contract snapshots, so that tool behavior remains the same in every supported package.
22. As a security reviewer, I want secret scans of outputs, logs, manifests, and fixtures, so that credentials cannot enter release artifacts.
23. As a security reviewer, I want prompt injection and hostile document cases in the evaluation suite, so that retrieved text cannot expand permissions.
24. As a maintainer, I want a source to be disabled without renaming tools or changing other source semantics, so that partial operations remain stable.
25. As a user, I want releases to preserve my data and credential store, so that operational hardening does not make updates destructive.
26. As an analyst, I want a route advertised only after its acceptance gate passes, so that the source list reflects working research paths.

## Implementation decisions

- Comitology is a versioned download adapter behind legislation records. It ingests official committee, agenda, draft-measure, voting-sheet, summary-record, and document datasets for a selected language.
- The adapter follows published document references and keeps implementation entities separate. It does not reverse-engineer private dynamic-page endpoints.
- A missing official distribution URL leaves the adapter not configured until the operator supplies or the project validates a published URL.
- Every registry entry declares allowed operations, hosts, credential transport, fixture hashes, licence and attribution, dates, pagination, refresh policy, languages, coverage limits, and parser version.
- The registry fails closed when an operation or required field disappears. One failing source does not disable unrelated routes.
- Interactive work and ingestion use separate quotas. Full backfills never run inside an MCP request or health check.
- Sync watermarks commit only after all records in a window persist. In-progress cursors remain separate, polling windows overlap, and provider IDs, versions, and hashes de-duplicate results.
- Locally observed changes record both source time and observation time. Observation time is never presented as the event's effective time.
- Operator commands include doctor, targeted sync, bounded backfill, schema verification, routing evaluation, and host-visible tool-token measurement.
- Administrative commands are not MCP research tools and are never exposed to the model.
- Source contract checks run on a schedule with conservative request volume. Download sources check manifests, files, freshness, parser contracts, and replacement versions.
- The evaluation set contains 60 versioned prompts across legislation, actors, evidence, and unsupported or ambiguous cases in German and English.
- Release targets include at least 95 percent correct first-tool selection on unambiguous prompts, zero undocumented operations, zero silent completeness errors, zero evidence facts without references, zero secret exposure, and no pagination duplicates or skips in frozen fixtures.
- Retrieval recall, response size, latency, schema tokens, duplicate structured and text content, and evidence quality are reported separately.
- Releases compare the proposed task-oriented design with an internal endpoint-per-tool baseline before publishing token-saving claims.
- The final release gate runs against signed, packaged artifacts for every supported host and target platform.

## Testing decisions

- The highest seam is the installed package running real MCP calls against frozen fixtures through each supported host. This proves the combined runtime, registry, store, contracts, and packaging behavior.
- Cross-client snapshots compare protocol initialization, tool names, JSON Schemas, annotations, normalized fixture results, and plugin instruction payloads.
- Comitology tests cover all six dataset families, language fallback, explicit entity links, document resolution, snapshot changes, and unsupported attachments.
- Sync tests inject failures before and after persistence to prove watermark safety, resumable cursors, overlap handling, and de-duplication.
- Reconciliation tests cover delayed publication, corrected versions, disappearance from snapshots, source conflicts, and a source disabled during a request.
- Storage tests cover concurrent readers, one serialized ingestion job, busy timeouts, crash recovery, backup, and restore.
- Reliability tests cover timeouts, transient retries, `Retry-After`, invalid credentials, application-level errors, HTML error bodies, partial results, and response-size limits.
- The 60-prompt evaluation asserts expected tool family, route, required warnings, evidence references, and unsupported-case behavior. Live answer quality review is separate from deterministic routing assertions.
- Host token tests measure actual rendered tool definitions and one complete representative turn per profile. They do not infer savings from server count.
- Scheduled live checks never perform a full historical crawl and store only redacted fixtures suitable for the repository.
- Release tests cover fresh install, update, disable, re-enable, direct fallback, concurrent clients, data preservation, signed-artifact checks, and uninstall without data loss.
- Prior art comes from every earlier milestone's MCP contract fixtures and package proof. This milestone unifies those suites rather than replacing them with implementation-level tests.

## Out of scope

- New Council, consultation, ministry, or Land parliament sources.
- ChatGPT web, Codex cloud, remote hosting, and tunnel deployment.
- A universal claim of complete German or EU political activity.
- Full historical backfill as a release prerequisite when the product reports the bounded coverage accurately.
- Token-saving claims without measured cross-host comparisons.
- Multi-user hosted infrastructure.

## Further notes

Release readiness is route-specific. The product may ship with a source disabled, but it may not pretend that the disabled source returned no matches. The registry, capabilities, and response envelope all need to tell the same story.
