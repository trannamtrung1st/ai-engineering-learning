# Review-phase example skill

When reviewing a todos-tool item:

1. Compare acceptance criteria, evidence, and validation results first.
2. Inspect checklist state in the item YAML and work summary.
3. If any checklist entry is still open and was not completed, removed, or moved with justification, set `instruction_compliance.passed=false` and list the open step ids in violations.
4. Submit the decision only through `todos-review-tool`.
