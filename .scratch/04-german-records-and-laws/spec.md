# Structured German parliamentary records and consolidated laws

Status: ready-for-agent

## Problem statement

DIP procedure metadata alone cannot answer questions about what a speaker said, how a recorded vote was cast, or what a consolidated federal provision currently says. Bundestag Open Data publishes structured transcripts, member data, and roll-call spreadsheets, while Gesetze im Internet publishes consolidated statutes in XML. These collections use versioned download formats and carry legal and interpretive limits that a simple endpoint wrapper would miss.

## Solution

Add versioned parsers and local indexes for Bundestag speeches and roll-call votes. Add the optional Gesetze im Internet adapter before advertising consolidated German-law coverage. Expose the records through the existing legislation tools and preserve speaker, agenda, motion, vote, provision, amendment, and source context.

## User stories

1. As a researcher, I want to find a Bundestag speech by topic, speaker, procedure, and date, so that I can locate relevant parliamentary debate.
2. As a researcher, I want a speech excerpt to retain its speaker and agenda item, so that the words are not detached from their setting.
3. As a researcher, I want paragraph locators in transcript excerpts, so that I can verify a quotation in the source record.
4. As a researcher, I want duplicate speaker names resolved against member identifiers where possible, so that remarks are not assigned by name alone.
5. As a researcher, I want unresolved speaker identity reported, so that uncertainty is visible rather than guessed away.
6. As a researcher, I want to find a roll-call vote connected to its motion, so that I know what was actually voted on.
7. As a researcher, I want individual recorded votes kept separate from aggregate results, so that neither one is inferred from the other.
8. As a researcher, I want missing, corrected, and non-vote spreadsheet values preserved, so that the system does not convert them into yes or no.
9. As a researcher, I want amendment votes distinguished from final votes, so that a vote is not attributed to the wrong legislative decision.
10. As a researcher, I want to look up a consolidated federal statute by exact title or identifier, so that I can find its current published text.
11. As a researcher, I want to read a selected provision with its heading and source notes, so that the excerpt retains legal context.
12. As a researcher, I want amendment and status notes preserved, so that consolidated wording is not presented without qualifications.
13. As a legal researcher, I want the consolidated source distinguished from the authoritative promulgation source, so that I understand its legal status.
14. As a legal researcher, I want historical questions rejected when retained versions do not cover the date, so that current text is not substituted for past law.
15. As a user, I want a clear not-configured response when the statute adapter is disabled, so that missing law coverage is not an empty search.
16. As a maintainer, I want transcript parser versions tied to each XML generation, so that structural differences do not corrupt older terms.
17. As a maintainer, I want roll-call headers validated by name and meaning, so that a column-order change cannot silently alter votes.
18. As a maintainer, I want official download manifests retained, so that each parsed record can be traced to the exact published file.
19. As a maintainer, I want corrections to create new versions, so that the original evidence trail remains intact.
20. As a user, I want records to follow the existing search, select, and read workflow, so that source format does not create new model tools.

## Implementation decisions

- Bundestag Open Data and Gesetze im Internet are download adapters behind the existing legislation tool contract. No source-specific model tools are added.
- The ingestion layer keeps a versioned manifest of official files, content hashes, parser versions, retrieval times, and normalized outputs.
- Structured plenary XML is parsed into document, sitting, agenda item, speech, speaker, and paragraph entities.
- Older and newer transcript structures have separate parser versions selected by validated document structure, not by a silent best effort.
- Member master data supports identity resolution. It is not treated as a guaranteed live directory of every current institutional role.
- Roll-call spreadsheets are parsed into vote events, underlying motions, member references, recorded choices, corrections, and explicit missing values.
- Spreadsheet columns are mapped from validated headers. Fixed column positions are forbidden.
- A party position or aggregate result never supplies an individual vote that is absent from the record.
- DIP metadata may link procedures and documents, but a relation is created only from an explicit identifier or retained candidate basis.
- Gesetze im Internet ingestion begins with the official contents list and follows its published XML links.
- Statute, regulation, provision, amendment note, procedure, proposed amendment, and resulting act remain distinct entities.
- Consolidated text is labelled as such and is not described as the authoritative gazette publication. An official promulgation link is included when validated and available.
- Historical law answers require a retained matching version or a separately validated archive. Current content cannot stand in for an unsupported date.
- Unsupported attachment or document formats return metadata-only results with a warning.
- Download and extraction limits apply to archives, XML expansion, spreadsheet size, document count, and processing time.

## Testing decisions

- The main seam is the legislation MCP contract using frozen transcript, vote, statute, and linked DIP fixtures. Users call records, search, and read tools rather than parser internals.
- Parser-level tests are added only where format generations and spreadsheet normalization cannot be diagnosed through the MCP seam.
- Transcript fixtures cover two XML generations, nested agenda structure, duplicate names, missing member identifiers, interruptions, and paragraph locators.
- Vote fixtures cover a corrected file, changed header order, missing values, an amendment vote, a final vote, and a vote linked to the underlying motion.
- Statute fixtures cover exact lookup, provision reading, amendment notes, language and encoding, a contents-list change, and a missing historical version.
- End-to-end tests prove that speech excerpts retain speaker and agenda context and that roll-call results do not infer individual choices.
- Legal-status tests ensure consolidated text is labelled correctly and never merged with a draft or procedure record.
- Version tests retain both the original and corrected file with separate hashes and normalized versions.
- Security tests use hostile XML, oversized archives, formula-bearing spreadsheets, malformed links, and arbitrary external URLs.
- Live download checks validate manifests and representative files separately from deterministic tests.
- Prior art comes from the DIP legislation path's references, evidence locators, immutable originals, response budgets, and capability reporting.

## Out of scope

- Land parliament records and statutes.
- Complete historical versions of German federal law without a validated archive.
- Inference of party discipline, motive, influence, or an absent member's vote.
- OCR for ordinary text-based parliamentary documents.
- New model tools for each document collection.

## Further notes

This milestone may ship speech and vote support before consolidated statutes if the optional statute adapter has not passed. Capability reporting must name the difference instead of advertising partial German-law coverage as complete.
