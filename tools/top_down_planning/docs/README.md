# TDP agent documentation hub

Navigation for **runtime TDP agents** (planner, producer, reviewer) inside provider sessions. For operator and maintainer docs, see the [package README](../README.md).

## Start here

1. `tdp agent help` — command cheat sheet
2. `tdp agent readme` — full agent protocol (authorization, workflow, run store)
3. Packaged role skills — auto-injected into `agent_context.skills` on every session (`agent_context.bundled_skills`, default true): shared protocol plus planner, producer, or reviewer guide
4. `tdp agent schema <name>` / `tdp agent example <name>` — exact request shapes

Example config: [examples/top-down-planning.yaml](../examples/top-down-planning.yaml). Set `agent_context.bundled_skills: false` only when you want to disable packaged skills. Add extra project skills under `agent_context.*.skills`.

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

Schema: `tdp agent schema production-apply`

Producer turns close when `production apply` persists a batch; the orchestrator also polls for new batches while the turn is open so a stalled agent cannot block progress after apply.

### Reviewer

| Task | Command | Example (whole-plan) |
| --- | --- | --- |
| Respond | `tdp agent review respond --run <id> --request ...` | `review-respond-family-discovery` |
| Owner actions | `tdp agent review record-actions --run <id> --request ...` | `review-record-family-fix` |
| Verification | same `review respond` | `review-respond-family-verification` |
| Scope review | same `review respond` | `review-respond-scope` |

Whole-output examples append `-output` (e.g. `review-respond-family-discovery-output`).

Schema: `tdp agent schema review-respond`

Mandatory discovery: `audit_attestation` rubric ids come from the review package `rubric_items`; `rule_id` values from `tdp agent readme` (section Built-in finding-family rule_id values) or `custom.<slug>`.

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
| `request_error` + `hint` | Review validation failures include `hint` (e.g. rubric union mismatch, invalid `rule_id`); see `tdp agent readme` |
| `unknown item id: <id>` | Unknown dependency target; check temp_id spelling and `tdp agent example expand-branch` |
| `duplicate temp_id in transaction` | Each `temp_id` must be unique within one `plan apply` batch |
| `production_evidence_incomplete` | Add every changed workspace path to batch `outputs` |
| `production_context_mutation_unauthorized` | Revert unauthorized skill/guidance drift |
| `audit attestation rubric_item_ids union mismatch` | Set `rubric_item_ids` from review package `rubric_items` (union across passes must equal every id); see `tdp agent readme` (Audit attestation) |
| `rule_id ... must be a built-in rule or match custom.<slug>` | Pick a built-in from `tdp agent readme` or use `custom.<slug>` + `rule_definition`; see `review-respond-family-discovery-output` for custom pattern |

Run status and `agent_requests_dir`: `tdp agent run status --run <id>`
