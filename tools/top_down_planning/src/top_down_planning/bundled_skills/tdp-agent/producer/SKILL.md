---
name: tdp-agent-producer
description: >-
  TDP producer role: record production batches, completion claims, blockers, and
  amendment requests via production commands. Auto-injected with the shared
  tdp-agent skill.
---

# TDP producer

You record **production batches** and evidence for approved plan items. Production state advances only through persisted `tdp agent production` commands.

## Commands you use

| Task | Command |
| --- | --- |
| Production state | `tdp agent production snapshot --run <run-id> [--view tree\|ready\|dispositions]` |
| Record batch | `tdp agent production apply --run <run-id> --request $TDP_AGENT_REQUESTS_DIR/production-apply-batch-01-a01.json` |
| Validate | `tdp agent production check --run <run-id>` |
| Submit completion | `tdp agent production submit-completion --run <run-id> --request ...` |
| Report blocked | `tdp agent production report-blocked --run <run-id> --request ...` |
| Request plan amendment | `tdp agent production request-amendment --run <run-id> --request ...` |
| Run status | `tdp agent run status --run <run-id>` |

## Examples to copy

| Task | `tdp agent example` name |
| --- | --- |
| Production batch | `batch-result` |
| Evidence revision (whole-output review) | `evidence-revision` |
| Evidence revision (focused output) | `evidence-revision-focused` |
| Completion claim | `completion-claim` |
| Blocker report | `blocker-report` |
| Plan amendment request | `amendment-request` |

Discover schema: `tdp agent schema production-apply`

## Production apply essentials

1. Set `production_revision` from the latest `production snapshot`.
2. `plan_items` lists work leaves in this batch; set `dispositions` per item.
3. Declare **every changed snapshot-bound workspace path** in `outputs` (`id`, `type`, `ref` only — service captures hashes).
4. On `production_evidence_incomplete`: add missing paths to `outputs` and retry with current `production_revision`.
5. On `production_context_mutation_unauthorized`: revert unauthorized skill/guidance drift (not authorizable via outputs).

## Workflow

1. `production snapshot --view ready` → pick `ready_item_ids` / `ready_items`.
2. Implement work in the workspace → `production apply` with evidence (one batch per provider turn; the orchestrator closes the turn when apply persists, waits for the provider session to settle, then queues the next turn). Requesting focused output review also closes the current turn — end the turn after `tdp agent review request`. Do not `report-blocked` merely because a focused review is pending.
3. When all applicable items have terminal dispositions, `submit-completion` with `goal_assessment`. The orchestrator closes that turn when the completion claim persists; stop immediately afterward.

## Evidence revision

After reviewer `changes_requested` on output:

- `production apply` with `evidence_revision: true` and **new** output evidence IDs on targeted terminal items (dispositions unchanged).
- During `production` focused-output loops: also set `focused_review_loop_id`; `production apply` closes the owner revision turn when the batch persists.
- Record owner `family_fix` sweeps via `tdp agent review record-actions` when using finding families. `target_revision` and `target_digest` must match the current artifact snapshot; stale digests are rejected. To correct a sweep after the artifact advances, call `record-actions` again at the new revision and digest — existing owner fix actions are not duplicated.
- During mandatory whole-output review: re-submit completion with `goal_assessment`; the owner revision turn closes when that claim persists.

## Discover

```bash
tdp agent readme
tdp agent schema production-apply
tdp agent example batch-result
tdp agent example completion-claim
```
