# Quantitative and financial evidence

Status: ready-for-agent

## Problem statement

Researchers need official statistics, budget data, procurement notices, funding calls, funded projects, and catalogue discovery through one bounded workflow. These sources have incompatible schemas and meanings. A budget authorization is not actual spending, a procurement notice is not a contract award, and a funding call is not a funded project. Raw tables and broad provider responses are too large for model context.

## Solution

Implement the evidence profile with metadata search, dataset description, validated slice queries, selected record retrieval, and capabilities. Integrate GovData discovery, GENESIS statistics, federal budget downloads, TED Search API, and Funding & Tenders collections only after their individual gates pass. Normalize units and dimensions while preserving each source's distinctions and limits.

## User stories

1. As a researcher, I want to search official statistical datasets by topic and scope, so that I can find a relevant table before requesting values.
2. As a researcher, I want to inspect a dataset's units, dimensions, periods, and permitted selections, so that I can form a valid query.
3. As a researcher, I want large dimension member lists paginated, so that dataset discovery remains compact.
4. As a researcher, I want to query a typed slice using returned dimension and member codes, so that the model cannot submit arbitrary query language.
5. As a researcher, I want schema-version validation before a numeric query, so that a changed table structure cannot produce a misleading result.
6. As a researcher, I want units, scale, period, population, territory, footnotes, and missing-value symbols preserved, so that numbers retain their meaning.
7. As a researcher, I want oversized selections rejected before retrieval, so that the system does not silently sample or truncate a table.
8. As a researcher, I want to search federal budget data by year, stage, section, chapter, title, and function, so that I can locate a specific allocation.
9. As a researcher, I want draft, enacted, supplementary, and actual stages kept separate when the source provides them, so that authorization is not called spending.
10. As a researcher, I want hierarchical budget totals protected from double counting, so that parent totals are not added to their children.
11. As a researcher, I want to find a TED procurement notice through topic, buyer, country, date, or classification, so that I can inspect official notice metadata.
12. As a researcher, I want notice, procurement procedure, lot, correction, and award kept distinct, so that publication is not mistaken for expenditure.
13. As a researcher, I want to find an EU funding call, so that I can inspect its programme, status, deadline, and documents.
14. As a researcher, I want to find a funded project separately from a call, so that awarded work is not replaced by an open opportunity.
15. As a researcher, I want to retrieve one selected procurement, funding, project, or catalogue record, so that detail follows search rather than arriving in bulk.
16. As a researcher, I want GovData to locate unknown public datasets, so that catalogue discovery can point me to an official distribution.
17. As a researcher, I want GovData results to default to non-queryable, so that catalogue metadata is not treated as an integrated dataset.
18. As a user, I want missing credentials, unavailable collections, and unsupported resources reported separately from no matches, so that negative results remain honest.
19. As a user, I want output rows and cells bounded with continuation where valid, so that evidence fits model context without losing units.
20. As an operator, I want GENESIS token authentication and application-level status errors handled, so that HTTP 200 cannot hide a failed request.
21. As an operator, I want TED expert queries compiled from typed inputs, so that the model never receives or writes provider query syntax.
22. As a maintainer, I want budget and downloaded datasets parsed through versioned column maps, so that upstream column changes fail visibly.
23. As a maintainer, I want Funding & Tenders calls and projects validated as separate collections, so that a working endpoint for one does not enable the other.
24. As a security reviewer, I want spreadsheet formulas, archives, documents, and provider links treated as untrusted data, so that retrieval cannot execute source content.

## Implementation decisions

- The evidence server exposes five tools: search, describe, query, selected record retrieval, and capabilities.
- Search returns at most ten compact cards and defaults to five. Dataset values are never embedded in general search results.
- Dataset description paginates dimensions and members and returns a version tied to the stored structure.
- Dataset query accepts only typed selections of dimension identifiers and member identifiers, plus bounded periods, measures, rows, and continuation. SQL, Python, SPARQL, and raw provider bodies are rejected.
- Numeric results default to at most 25 rows and 250 cells. Preflight rejects larger selections with a typed oversized-result error rather than sampling.
- GENESIS uses authenticated POST requests, checks its application-level status, starts at one concurrent request, and normalizes formatted output into typed rows while retaining source symbols and notes.
- Federal budget files are ingested into versioned local tables. Source amount units, revenue and expenditure, fiscal year, publication stage, and classifications remain explicit.
- Budget comparisons disclose classification changes and prevent summing parent and child totals in the same result.
- TED uses server-compiled, tested expert-query templates and a small pinned field projection. Interactive requests use normal bounded pagination; scroll belongs only to ingestion.
- Notice, procedure, lot, award, and correction are separate entity kinds connected by explicit identifiers.
- Funding & Tenders uses separately validated templates for calls and funded projects. Each collection remains disabled until official serialization, pagination, facets, and detail lookup pass.
- GovData uses documented CKAN package search and selected package retrieval. HTTP success is not enough; the CKAN success envelope must also pass.
- GovData distributions remain non-queryable unless an allowlisted adapter validates their licence, format, and schema.
- Download sources use manifests, hashes, parser versions, source timestamps, and replacement versions. Interactive source APIs use typed provider pages and request budgets.
- Credentials never appear in MCP inputs. Public collection keys documented as collection identifiers are not treated as private user secrets.
- Search dates and locally observed update dates remain distinct. Unsupported date bases are rejected rather than ignored.

## Testing decisions

- The main seam is the evidence MCP contract against frozen provider and download fixtures. Tests use search, describe, query, and get exactly as a user or model would.
- GENESIS tests cover token authentication, discovery, metadata, a small slice, changed metadata, suppressed values, German numeric formatting, and a nonzero application status inside HTTP 200.
- Budget tests validate source units, revenue versus expenditure, stage separation, classification changes, and double-count prevention.
- TED tests cover bounded search, field errors, correction notices, stable de-duplication, paging while new notices appear, and the difference between a notice and award.
- Funding tests independently cover a call, a funded project, pagination, detail retrieval, and one collection unavailable while the other remains usable.
- GovData tests cover package search, selected metadata, a broken external distribution, licence and format gating, and non-queryable defaults.
- Dataset contract tests reject stale schema versions, unknown dimensions, unknown members, duplicate selections, excess rows or cells, and arbitrary query languages.
- Numeric output tests retain units, periods, footnotes, missing markers, and source references under response budgets.
- Security tests cover formula-bearing spreadsheets, archive bombs, HTML error pages, malicious document instructions, private-network redirects, and oversized payloads.
- Live checks remain low volume and source-specific. Download adapters test the published manifest and file rather than pretending to have search endpoints.
- Prior art comes from the common MCP response envelope and the legislation profile's snapshot cursors, provenance, typed errors, and capability reporting.

## Out of scope

- Arbitrary execution of datasets found through GovData.
- Unbounded statistical tables, silent sampling, and raw upstream table strings.
- Claims that budget authorization equals actual spending.
- Claims that a procurement notice proves a contract or payment.
- Commercial data, paid search, and non-public sources.
- Generic model-authored provider expert queries.

## Further notes

This milestone can enable sources independently. The evidence capability response must say which kinds are ready. A working GENESIS adapter does not justify advertising procurement or funding coverage.
