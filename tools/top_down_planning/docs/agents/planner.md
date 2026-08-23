# Planner protocol

**Audience:** the planner agent in a provider session.

Construct and revise the [plan tree](../concepts/plan-tree.md). Do not record production batches. Shared request-file and revision rules: [protocol](protocol.md).

## Commands

| Task | Command | Example |
| --- | --- | --- |
| Read plan | `tdp agent plan snapshot --run <id> --view active` | — |
| Mutate plan | `tdp agent plan apply --run <id> --request $TDP_AGENT_REQUESTS_DIR/...` | `expand-branch` |
| Validate | `tdp agent plan check --run <id>` | — |
| Focused review | `tdp agent review request --run <id> --request ...` | `focused-review-request` |
| Done | Emit `candidate_plan_ready` | — |

Schema: `tdp agent schema plan-transaction`

Snapshot views: `active`, `audit`, `ready`, `issues`, `budget`. Check modes: `draft` (default) and `approval` (`tdp agent plan check --run <id> --mode approval`).

For a plan amendment session, emit `amendment_revision_ready` when the revised candidate is ready (not `candidate_plan_ready`).

## Plan mutations: `depends_on`

Set dependencies **inline** on `add_item.item.depends_on` when adding new items in the same batch:

```json
"depends_on": ["item-api"]
```

- `item-api` may be a stable id or a `temp_id` from another `add_item` in the same batch.
- String form (`"item-api"`) or array form both work.
- Operation order within the batch does not matter; temp ids are pre-registered.
- Each `temp_id` must be unique within one `plan apply` batch.
- See `tdp agent example expand-branch`.

To change dependencies on an **existing** item, use `add_dependency`, `remove_dependency`, or `replace_dependencies` — not `update_item` patch.

## Apply and check behavior

`plan apply` requires `base_revision` from the latest `plan snapshot`. Mutations that would introduce **new** hard validation errors are rejected before persistence (`operation_error`); the plan revision is unchanged.

`plan snapshot`, `plan apply`, and `plan check` exit 0 only when `ok` is true. Responses separate validation `issues` from `warnings`. Compact apply responses omit `changed_subtree` and per-item `planning_budget`; refresh with `plan snapshot`.

When `item-root` has active children, draft validation errors on a seeded root title `Root` (`default_root_title`) or `missing_root_outcome`. Every active `work` leaf must set item-level `scope.includes`, `scope.excludes`, and/or `boundaries` (plan-level fields do not satisfy this). Field semantics (acceptance, risks, assumptions, constraints, boundaries, scope, `depends_on`, `source_refs`) are in `tdp agent readme` under Plan field semantics.

Plan `ready` views exclude items blocked by unresolved `focused_plan` / `whole_plan` findings.

## Focused plan review

Optional. `tdp agent schema focused-review-request` and `tdp agent example focused-review-request`. Copy `target_revision` and `target_digest` from `plan_digest` on `tdp agent plan snapshot`. Scope lists `item_ids` only.

Related: [agent CLI](cli.md), [troubleshooting](troubleshooting.md).
