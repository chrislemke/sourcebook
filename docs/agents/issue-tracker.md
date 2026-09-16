# Issue tracker: local Markdown

Issues and specs for this repo live as Markdown files in `.scratch/`.

## Conventions

- One feature per directory: `.scratch/<feature-slug>/`
- The spec is `.scratch/<feature-slug>/spec.md`
- Implementation issues are stored as individual files at `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01`
- Triage state is recorded as a `Status:` line near the top of each issue file
- Comments and conversation history are appended under a `## Comments` heading

## When a skill says "publish to the issue tracker"

Create a file under `.scratch/<feature-slug>/`, creating the directory if needed.

## When a skill says "fetch the relevant ticket"

Read the referenced file. The user will normally provide its path or issue number.

## Wayfinding operations

The map is `.scratch/<effort>/map.md`. Each ticket is a separate child file.

- Child ticket: `.scratch/<effort>/issues/NN-<slug>.md`
- Type: `research`, `prototype`, `grilling`, or `task`
- Status: `claimed` or `resolved`
- Blocking: record dependencies as `Blocked by: NN, NN`
- Frontier: choose the first numbered ticket that is open, unblocked, and unclaimed
- Claim: set `Status: claimed` before starting work
- Resolve: append the result under `## Answer`, set `Status: resolved`, and add a summary and link to the map
