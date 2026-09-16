# Actors and public disclosures

Status: ready-for-agent

## Problem statement

Researchers need to identify public officeholders, institutions, and disclosed interest representatives connected to a subject. The available sources describe roles and self-reported disclosures, but they do not prove political influence, alignment, causation, or complete historical state. Combining names, organisations, procedures, and register entries without evidence would create misleading relationships.

## Solution

Implement the actor profile with compact search, selected actor views, interest-disclosure search, and capability reporting. Use the German Lobbyregister, European Parliament data, EU WhoisWho, and EU Transparency Register only after each source's contract gate passes. Store dated, evidence-bearing relationships and label text-based candidate matches as candidates.

## User stories

1. As a researcher, I want to search for a public officeholder by name and scope, so that I can find a published identity without knowing a provider identifier.
2. As a researcher, I want to search for an institution or parliamentary body, so that I can inspect its documented organisational role.
3. As a researcher, I want to search for an interest representative, so that I can find its public register entry.
4. As a researcher, I want actor results to distinguish people, institutions, and interest representatives, so that unlike entities are not merged.
5. As a researcher, I want an overview of a selected actor, so that I can see the key published identity and source dates.
6. As a researcher, I want roles returned as a separate view, so that a long disclosure does not crowd out the requested facts.
7. As a researcher, I want organisational relationships returned as a separate view, so that membership, employment, and representation remain distinct predicates.
8. As a researcher, I want a disclosure section on demand, so that I can inspect declared interests, clients, projects, or resources without loading a complete entry.
9. As a researcher, I want every relationship to carry its source and validity dates when available, so that a current role is not presented as timeless.
10. As a researcher, I want an explicit limitation when a historical role cannot be answered, so that the system does not reconstruct the past from a current snapshot.
11. As a researcher, I want organisations matching a topic or procedure, so that I can discover relevant disclosed regulatory projects.
12. As a researcher, I want disclosure wording and financial ranges preserved, so that normalization does not imply more precision than the source provides.
13. As a researcher, I want explicit procedure links distinguished from title or text matches, so that a candidate association is not treated as a documented connection.
14. As a researcher, I want disappearance from a snapshot distinguished from confirmed deregistration, so that observed data changes are described accurately.
15. As a user, I want actor searches to report freshness and source configuration, so that unavailable registers do not produce false negative claims.
16. As a user, I want updated-since queries described as locally observed changes, so that they are not mistaken for an upstream change feed.
17. As a user, I want register membership and declared spending reported without an influence score, so that the tool does not manufacture political judgments.
18. As a maintainer, I want the official Lobbyregister v2 schema pinned before implementation, so that auth, filters, paging, and version fields are not guessed.
19. As a maintainer, I want EU register snapshots downloaded outside interactive calls, so that search remains bounded and reproducible.
20. As a maintainer, I want people with duplicate or multilingual names resolved through source identifiers and dated roles, so that names alone do not collapse identities.
21. As a privacy reviewer, I want only business-relevant public personal data retained, so that the local index does not copy unnecessary personal detail.
22. As an analyst, I want conflicting dated records returned together, so that I can assess the discrepancy rather than receive a hidden winner.

## Implementation decisions

- The actor server exposes four tools: actor search, selected actor retrieval, disclosed-interest search, and capabilities.
- Actor search requires a query, scope, and kind. The interest tool requires at least a topic query, procedure reference, or actor reference.
- Result cards remain small. Detailed roles, relationships, disclosures, and evidence are separate requested views with pagination.
- The German Lobbyregister adapter is blocked until the official v2 schema is downloaded, checksummed, and inspected for authentication, search parameters, cursor rules, and version fields.
- German register indexing covers public names, interest areas, clients, and disclosed regulatory projects when the pinned schema makes those fields available.
- Explicit provider links to procedures become documented relationships. Title and text matches remain candidates with their matching basis.
- The European Parliament adapter is reused for member and body records. Collection-specific identifiers and dates remain authoritative.
- EU WhoisWho uses bounded SPARQL templates that select names, role labels, organisation identifiers, and available validity metadata. It does not infer policy responsibility from a title.
- EU Transparency Register data is ingested from validated official distributions. Every snapshot records provider time when present, download time, schema version, and content hash.
- Observed snapshot diffs support updated-since filtering. They do not claim provider event time or confirmed deregistration without source evidence.
- Actor identity resolution keeps provider identifiers separate and records merges or candidate matches as evidence-bearing relations.
- A current record cannot satisfy an unsupported historical as-of request. The tool returns a typed coverage limitation.
- Search and retrieval never generate influence, alignment, lobbying-success, or causal scores.
- The capability tool returns only relevant source state, coverage, freshness, and limitations, not the complete registry.
- Public data remains subject to authorization because search history, watched topics, and local relation work may reveal confidential research interests.

## Testing decisions

- The primary seam is the actor MCP contract with frozen register, EP, and WhoisWho fixtures. Tests assert public cards, views, relations, warnings, and errors.
- German Lobbyregister contract tests cover one current entry, one historical version, search continuation, a regulatory-project link, and schema drift in organisational recipient fields.
- EU register tests cover a current distribution, stale timestamps, an HTML error page posing as XML, a schema change, an observed disappearance, and a later reappearance.
- WhoisWho tests cover multiple roles, missing dates, multilingual organisation labels, and a title that must not be converted into a policy-responsibility claim.
- Identity tests cover duplicate names, changed names, provider identifiers, exact explicit links, and candidate text matches.
- Historical tests reject unsupported as-of requests and prove that retrieval time is not substituted for effective time.
- Interpretation tests assert that outputs use disclosure language and never emit influence or alignment judgments.
- Pagination and response-budget tests retain evidence and source warnings while limiting large disclosure sections.
- Security tests cover forged actor references, cross-principal cursors, malicious register text, and personal fields excluded by the retention policy.
- Small live checks run independently for each enabled source. Download sources test manifests, bytes, freshness, and parser behavior instead of pretending to be interactive APIs.
- Prior art comes from the legislation profile's typed models, common envelope, references, cursors, budgets, provenance, and source-health behavior.

## Out of scope

- Private contact data, outreach, automated messaging, and register changes.
- Influence, alignment, lobbying-success, or corruption scores.
- Reconstructed historical biographies where no archive exists.
- General social-network analysis based on co-occurrence.
- Sources beyond the German Lobbyregister, EP, EU WhoisWho, and EU Transparency Register.

## Further notes

The words "connected" and "relationship" must always resolve to an explicit predicate and evidence basis. A shared topic is useful for discovery, but it is not proof of institutional or political influence.
