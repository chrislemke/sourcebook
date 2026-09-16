# EU legislation and document retrieval

Status: ready-for-agent

## Problem statement

Researchers need to find EU procedures, speeches, questions, and legal texts without relying on search parameters that the European Parliament API does not provide. They also need to follow the distinction between parliamentary procedure metadata, EUR-Lex search, CELLAR metadata, and language-specific document files. A naive adapter would flatten these sources, overstate coverage, or return large JSON-LD graphs and documents to the model.

## Solution

Add collection-specific European Parliament routing, local metadata indexes, native speech search where documented, and CELLAR identifier and file resolution. Enable registered EUR-Lex SOAP search only after its account and contract gates pass. Reuse the legislation MCP contracts so a user can search, inspect a procedure, find a record, and read a cited passage through bounded responses.

## User stories

1. As a researcher, I want to find an EU procedure by topic, so that I can discover relevant parliamentary work without knowing its identifier.
2. As a researcher, I want to resolve a known EU procedure identifier, so that I can reach the exact procedure and its events.
3. As a legal researcher, I want to resolve a CELEX identifier, so that I can inspect official metadata and available language files.
4. As a researcher, I want procedure events shown separately from linked documents, so that institutional events are not mistaken for legal acts.
5. As a researcher, I want to search EU plenary speeches by supported text and date filters, so that the query uses the source's documented capability.
6. As a researcher, I want parliamentary questions and committee documents discoverable through metadata indexes, so that unsupported generic provider search is not invented.
7. As a researcher, I want a selected question or document to resolve its linked file, so that I can read the evidence rather than only metadata.
8. As a researcher, I want the selected language reported, so that a translation or fallback is never hidden.
9. As a researcher, I want works, language expressions, manifestations, and files kept distinct, so that a metadata record is not mistaken for a complete text.
10. As a researcher, I want amended and consolidated works distinguished, so that I know which version I am reading.
11. As a researcher, I want publication, legal status, applicability, and procedure dates stored separately, so that one date does not stand in for every legal meaning.
12. As a researcher, I want a missing translation reported, so that another language file is not silently presented as the requested version.
13. As a user without EUR-Lex credentials, I want CELLAR identifier retrieval to remain available, so that the product degrades without misrepresenting full-text search.
14. As a user with an approved EUR-Lex account, I want typed topic and identifier queries compiled server-side, so that the model never writes SOAP or expert query syntax.
15. As a user, I want source and coverage warnings when an EP collection has limited periods or text, so that results do not imply complete EU legislative coverage.
16. As a user, I want bounded excerpts from selected files, so that the model does not receive an entire debate or legal instrument.
17. As a maintainer, I want each EP collection's filters and pagination tested independently, so that a capability from one feed is not assumed for another.
18. As a maintainer, I want JSON-LD links and multilingual labels normalized behind the adapter, so that tool output remains compact and stable.
19. As an operator, I want EUR-Lex registration, faults, limits, and retrieval caps surfaced as source state, so that account problems do not look like empty search results.
20. As a security reviewer, I want SPARQL and SOAP built from allowlisted templates, so that model input cannot execute an arbitrary query.

## Implementation decisions

- The existing legislation tools remain the public contract. No source-specific MCP tools are added.
- The deterministic router selects an EP collection, CELLAR operation, or configured EUR-Lex search based on intent, jurisdiction, kind, identifier, and explicit source.
- Procedure and general document topic search use local indexes because those EP collections do not document a generic topic parameter.
- Native EP speech search uses only documented text, title, search-language, date, pagination, and enrichment fields.
- EP JSON-LD is normalized into compact records. Requested languages and linked identifiers are resolved server-side.
- Procedure, event, document, work, language expression, manifestation, and file remain separate entity kinds linked by evidence-bearing relations.
- CELLAR uses fixed SPARQL templates for identifier lookup, bounded metadata search, and related-document retrieval. Typed compilers validate identifiers and escape literal values.
- Document URLs come from returned identifiers or documented stable links. The application does not guess download paths.
- Structured XML or HTML is preferred for extraction. Text-based PDF extraction is the fallback, and OCR is reserved for image-only sources with an extraction-quality flag.
- The system stores selected language, source version, content hash, retrieval time, and locator data with every extracted section.
- EUR-Lex search remains a separate adapter from CELLAR. It is enabled only after registration, WSDL validation, credential setup, paging, fault, and cap tests pass.
- When EUR-Lex is unavailable, the capability response states that registered full-text search is absent. CELLAR retrieval and any local corpus search remain separately described.
- Interactive fan-out remains bounded. A normal EU query uses the most specific source and at most one necessary linked source.
- The response envelope reports per-source completeness and failure. A partially successful linked lookup returns usable evidence with warnings.
- EU integration does not claim Council, consultation, ministry, or complete legislative-process coverage.

## Testing decisions

- The primary seam is the legislation MCP contract backed by frozen EP, CELLAR, and EUR-Lex fixtures. Complete tests start with a public tool call and assert normalized external behavior.
- Procedure tests cover topic search through the local index, exact identifier resolution, event pagination, linked documents, and stable language selection.
- Speech tests prove that native text search is used only for the speech collection and that selected text enrichment remains bounded.
- Document tests cover a parliamentary question with a linked file, a committee document, an adopted text, and missing file text.
- CELLAR tests resolve a CELEX identifier, an amended or consolidated work, multiple language expressions, a missing translation, and a timeout.
- EUR-Lex tests cover approved account setup, SOAP faults, paging, typed field selection, credentials remaining out of output, and a result set above the retrieval cap.
- Schema tests pin representative EP collection responses independently. A field or operation disappearing fails closed for that route.
- Excerpt tests preserve version, language, heading, locator, and surrounding qualifications.
- Routing tests prove that EU procedure topic search does not call an invented EP full-text parameter and that CELEX lookup does not broadcast to unrelated adapters.
- Live provider checks stay small and separate from frozen tests. They record redacted fixtures only after schema validation.
- Prior art comes from the working DIP search-to-evidence path and its common MCP response, reference, budget, and security assertions.

## Out of scope

- Council public-register integration, Have Your Say consultations, and national ministry drafts.
- Actor roles and interest-representation disclosures.
- Statistical, budget, procurement, and funding evidence.
- Claims of complete EU legislative or legal-history coverage.
- Arbitrary model-authored SPARQL, SOAP, or upstream expert queries.

## Further notes

The EP adapter is shared later with actor work, but this milestone only enables procedure and legislative record capabilities. A collection is advertised only after its own filters, pagination, text links, and representative historical periods pass.
