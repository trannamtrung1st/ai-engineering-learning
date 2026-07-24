# Review-phase example skill

When reviewing a todos-tool item:

1. Compare acceptance criteria, evidence, and validation results first.
2. Run `todos-review-tool scaffold`, fill in evidence and summary, then submit with `todos-review-tool submit --json '<decision>'`. Use the scaffold strings for `acceptance_criteria[].criterion` — do not paraphrase.
3. When UI/browser/screenshot verification applies, confirm artifacts via Read or shell `ls` using paths from the work summary — Glob/Grep skip gitignored directories. Cite verified paths in each visual criterion's `evidence` field; a work-summary claim alone is not enough.
4. Inspect checklist state in the item YAML and work summary.
5. If any checklist entry is still open and was not completed, removed, or moved with justification, set `instruction_compliance.passed=false` and list the open step ids in violations.
6. Submit only through `todos-review-tool submit --json '<decision>'` (optional dry-run: `validate --json` first).
