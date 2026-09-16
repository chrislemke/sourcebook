# Domain docs

This repository uses a single-context domain layout.

## Before exploring

Read these when they exist:

- `CONTEXT.md` at the repository root
- Relevant ADRs under `docs/adr/`

If these files do not exist, continue without calling attention to their absence. The domain-modeling skill creates them when the project resolves domain terms or architectural decisions.

## File structure

```text
/
├── CONTEXT.md
├── docs/adr/
└── src/
```

## Use the glossary vocabulary

Use terms defined in `CONTEXT.md` when naming domain concepts in issues, proposals, tests, and code. Do not replace defined terms with synonyms.

If a required concept is missing, reconsider whether it belongs to the project vocabulary or record the gap for the domain-modeling skill.

## Flag ADR conflicts

Call out any proposal that contradicts an existing ADR and name the conflicting ADR.
