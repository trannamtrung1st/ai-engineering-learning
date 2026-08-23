# Producer protocol

**Audience:** the producer agent in a provider session.

Record [production batches](../concepts/quality-loop.md) and evidence for approved **work** items. Stay within each item’s `effective_scope` and `effective_boundaries`. Shared request-file and revision rules: [protocol](protocol.md).

## Commands

| Task | Command | Example |
| --- | --- | --- |
| Ready items | `tdp agent production snapshot --run <id> --view ready` | — |
| Record batch | `tdp agent production apply --run <id> --request ...` | `batch-result` |
| Completion | `tdp agent production submit-completion --run <id> --request ...` | `completion-claim` |
| Evidence revision | `production apply` with `evidence_revision: true` | `evidence-revision` |
| Amendment | `tdp agent production request-amendment --run <id> --request ...` | `amendment-request` |
| Blocked | `tdp agent production report-blocked --run <id> --request ...` | `blocker-report` |
| Validate | `tdp agent production check --run <id>` | — |

Schema: `tdp agent schema production-apply`

Snapshot views: `tree`, `ready`, `dispositions`. Empty-output batches: `tdp agent example empty-output`.

Producer batch turns close when `production apply` persists a batch; completion turns close when `submit-completion` persists a valid completion claim. In both cases the orchestrator aborts the in-flight provider turn, waits for the session collector to settle, then queues the next turn on the same session. A background poll also watches for persisted batches and completion claims while the turn is open so a stalled agent subprocess cannot block progress after apply or submit-completion.

Record **one production batch per provider turn**. Stop working after submit-completion; no summary or cleanup turn is required.

## Production apply

1. Set `production_revision` from the latest `production snapshot`.
2. `plan_items` lists work leaves in this batch; set `dispositions` per item (`completed`, `satisfied_without_change`, `not_applicable`, `superseded`, `blocked`).
3. Declare **every changed snapshot-bound workspace path** in `outputs` (`id`, `type`, `ref` only — the service captures hashes). Evidence IDs must be unique across the full run history.
4. On `production_evidence_incomplete`: add every listed workspace path to `outputs` and retry with the current `production_revision`.
5. On `production_context_mutation_unauthorized`: revert unauthorized skill/guidance drift. Those paths cannot be authorized through `outputs`.
6. On `capability_denied`: `TDP_CAPABILITY_TOKEN_FILE` is missing or the session has no bound capability. Retry apply without caching capability state in the shell.

`not_applicable` requires `reason`. `superseded` requires `replacement_ref`. `blocked` requires `evidence`.

## Completion

When all applicable items have terminal dispositions, `tdp agent production submit-completion` with `production_revision` and non-empty `goal_assessment` (`tdp agent example completion-claim`). The submit-completion command implies `goal_met`; do not invent extra request fields. The persisted claim binds to the current plan and output revisions.

## Evidence revision

After reviewer `changes_requested` on output:

- `production apply` with `evidence_revision: true` and **new** output evidence IDs on targeted terminal items (dispositions unchanged).
- During `production` focused-output loops: also set `focused_review_loop_id`; the loop’s `target_revision` must match the current `output_revision`. Example: `evidence-revision-focused`.
- During mandatory whole-output review: re-submit completion with `goal_assessment` after evidence is revised; the owner revision turn closes when that claim persists.

Record owner `family_fix` sweeps via `tdp agent review record-actions` when using finding families. `target_revision` and `target_digest` must match the current artifact snapshot. Example: `review-record-family-fix-output`.

## Amendment and blockers

If the approved plan cannot be followed, `request-amendment` (`amendment-request`) or `report-blocked` (`blocker-report`). Do not expand the plan tree with `plan apply` in a producer session.

Related: [agent CLI](cli.md), [troubleshooting](troubleshooting.md), [operator-visible sessions](../workflows/agent-sessions.md).
