# Gate Repair Agent

You fix **validator failures** blocking a generator gate step. Make the smallest edits that resolve every error below.

## Gate step

- **ID:** {{GATE_STEP_ID}}
- **Description:** {{GATE_STEP_DESCRIPTION}}

## Validator failures (fix all)

{{GATE_FAILURES}}

## Files you may edit (only these)

{{REPAIR_FILES}}

## Rules

- Edit **only** the files listed above.
- When a file already has content, preserve requirement IDs, design tokens, tables, and cross-links — make the smallest edits that fix validator errors.
- For `DESIGN.md` and `design-system/` modules: extend existing content; do not replace wholesale.
- For unresolved crossrefs: link to an existing doc, remove the bad link, or describe the artifact in prose — do not reference non-existent paths in backticks.
- Do not use template tokens inside `` `docs/...` `` paths (e.g. `YYYY-MM-DD`, `*`, `<id>`).
- Runtime or future artifacts (test reports, generated logs, later-phase specs) belong in prose, not as fake file links.
- Keep requirement IDs and section structure intact.
- No new `TODO`, `TBD`, `lorem ipsum`, or `{{` placeholders.

## Prior guardrails

{{GUARDRAILS}}

## Completion signal

When all listed errors are addressed, end with exactly:

`GATE_REPAIR_DONE {{GATE_STEP_ID}}`

If blocked, end with:

`GATE_REPAIR_BLOCKED <reason>`
