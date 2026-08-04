---
name: tdp-agent-planner
description: >-
  TDP planner role: expand the plan tree via plan snapshot/apply/check, optional
  focused review requests, and candidate_plan_ready. Auto-injected with the shared
  tdp-agent skill.
---

# TDP planner

You expand the **TDP plan tree** stored in the run store. Planning means plan-tree decomposition, not a host-IDE plan document.

## Commands you use

| Task | Command |
| --- | --- |
| Read plan | `tdp agent plan snapshot --run <run-id> --view active` |
| Mutate plan | `tdp agent plan apply --run <run-id> --request $TDP_AGENT_REQUESTS_DIR/plan-apply-r<rev>-a01.json` |
| Validate | `tdp agent plan check --run <run-id> [--mode draft\|approval]` |
| Request focused review | `tdp agent review request --run <run-id> --request $TDP_AGENT_REQUESTS_DIR/review-request-<scope>-a01.json` |
| Run status | `tdp agent run status --run <run-id>` |

## Examples to copy

| Task | `tdp agent example` name |
| --- | --- |
| Expand plan branch | `expand-branch` |
| Focused plan review request | `focused-review-request` |

Discover schema: `tdp agent schema plan-transaction`

## Plan apply essentials

1. Set `base_revision` from the latest `plan snapshot`.
2. Root item is `item-root` (`aggregate`). Before adding children, `update_item` on `item-root` for a meaningful title and outcome; use `update_plan` for plan-level metadata.
3. Every `add_item` requires `kind`: `work` (batchable leaf) or `aggregate` (grouping only).
4. Every `work` leaf needs item-level `scope.includes`, `scope.excludes`, and/or `boundaries`.
5. Use `temp_id` on `add_item` to reference new items in the same transaction.

### Dependencies (`depends_on`)

Set dependencies **inline** on `add_item.item.depends_on` when adding new items in the same batch:

```json
{
  "op": "add_item",
  "temp_id": "item-ui",
  "parent_id": "item-root",
  "item": {
    "kind": "work",
    "title": "UI layer",
    "depends_on": ["item-api"]
  }
}
```

- Values may be stable item ids **or** `temp_id` strings from other `add_item` ops in the same batch.
- Accepts a **string** (`"item-api"`) or **array** (`["item-api"]`).
- Operation order within the batch does not matter; temp ids are pre-registered.
- Each `temp_id` must be unique within one `plan apply` batch.

To add a dependency to an **existing** item in the same batch, use `add_dependency` (see `tdp agent schema plan-transaction`).

Run `tdp agent example expand-branch` for a full transaction.

## Workflow

1. `plan snapshot --view active` → plan `apply` in coherent batches → `plan check`.
2. Optionally `review request` for focused plan review on bounded `scope.item_ids`.
3. When the plan satisfies `stop_hint` and passes check, emit `candidate_plan_ready`.

## After whole-plan review

When revising after `changes_requested`, treat each **finding family** as one repair unit. Search the whole active plan, fix all equivalent locations in one apply where possible, then record owner sweeps via `tdp agent review record-actions` at the current `target_revision` and `target_digest` (see reviewer skill for family protocol). `record-actions` rejects stale `target_digest` values. After the artifact revision advances, call `record-actions` again at the new revision and digest to rebind sweeps without duplicating fix actions.

## Discover

```bash
tdp agent readme
tdp agent schema plan-transaction
tdp agent example expand-branch
```
