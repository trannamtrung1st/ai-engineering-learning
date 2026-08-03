# TDP agent documentation hub

Navigation for **runtime TDP agents** (planner, producer, reviewer) inside provider sessions. For operator and maintainer docs, see the [package README](../README.md).

## Start here

1. `tdp agent help` — command cheat sheet with role skill paths
2. `tdp agent readme` — full agent protocol (authorization, workflow, run store)
3. Role skill (loaded via `agent_context.*.skills` when configured):
   - Shared: `tools/top_down_planning/skills/tdp-agent`
   - Planner: `tools/top_down_planning/skills/tdp-agent/planner`
   - Producer: `tools/top_down_planning/skills/tdp-agent/producer`
   - Reviewer: `tools/top_down_planning/skills/tdp-agent/reviewer`
4. `tdp agent schema <name>` / `tdp agent example <name>` — exact request shapes

Example config with skills wired: [examples/top-down-planning.yaml](../examples/top-down-planning.yaml). Launch `tdp` from the **repository root** when `project.workspace: .` and skill paths use `tools/top_down_planning/skills/...`.

## By role

### Planner

| Task | Command | Example |
| --- | --- | --- |
| Read plan | `tdp agent plan snapshot --run <id> --view active` | — |
| Mutate plan | `tdp agent plan apply --run <id> --request $TDP_AGENT_REQUESTS_DIR/...` | `expand-branch` |
| Validate | `tdp agent plan check --run <id>` | — |
| Focused review | `tdp agent review request --run <id> --request ...` | `focused-review-request` |
| Done | Emit `candidate_plan_ready` | — |

Schema: `tdp agent schema plan-transaction`

### Producer

| Task | Command | Example |
| --- | --- | --- |
| Ready items | `tdp agent production snapshot --run <id> --view ready` | — |
| Record batch | `tdp agent production apply --run <id> --request ...` | `batch-result` |
| Completion | `tdp agent production submit-completion --run <id> --request ...` | `completion-claim` |
| Evidence revision | `production apply` with `evidence_revision: true` | `evidence-revision` |
| Amendment | `tdp agent production request-amendment --run <id> --request ...` | `amendment-request` |
| Batch done | Emit `batch_complete` | — |

Schema: `tdp agent schema production-apply`

### Reviewer

| Task | Command | Example (whole-plan) |
| --- | --- | --- |
| Respond | `tdp agent review respond --run <id> --request ...` | `review-respond-family-discovery` |
| Owner actions | `tdp agent review record-actions --run <id> --request ...` | `review-record-family-fix` |
| Verification | same `review respond` | `review-respond-family-verification` |
| Scope review | same `review respond` | `review-respond-scope` |

Whole-output examples append `-output` (e.g. `review-respond-family-discovery-output`).

Schema: `tdp agent schema review-respond`

List all examples: `tdp agent example`

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

## Contracts

| Schema | Purpose |
| --- | --- |
| `plan-transaction` | `plan apply` |
| `production-apply` | `production apply` |
| `review-respond` | `review respond` |
| `review-record-finding-actions` | `review record-actions` |
| `focused-review-request` | `review request` |
| `completion-claim` | `submit-completion` |
| `amendment-request` | `request-amendment` |
| `blocker-report` | `report-blocked` |

## Troubleshooting

| Error | What to do |
| --- | --- |
| `revision_conflict` | `tdp agent plan snapshot` or `production snapshot`; retry with current revision |
| `capability_denied` | Ensure `TDP_CAPABILITY_TOKEN` is exported; mutating commands need an active session |
| `operation_error` + `hint` | Read `hint` in the JSON error; often points to `tdp agent example <name>` |
| `unknown item id: <id>` | Unknown dependency target; check temp_id spelling and `tdp agent example expand-branch` |
| `duplicate temp_id in transaction` | Each `temp_id` must be unique within one `plan apply` batch |
| `production_evidence_incomplete` | Add every changed workspace path to batch `outputs` |
| `production_context_mutation_unauthorized` | Revert unauthorized skill/guidance drift |

Run status and `agent_requests_dir`: `tdp agent run status --run <id>`
