# Agent troubleshooting

**Audience:** runtime agents recovering from `tdp agent` errors.

Operator diagnosis of paused or failed runs (cancellation, concurrency, `tdp doctor`) is on [manual troubleshooting](../manual/troubleshooting.md). This page is the rehomed hub error table plus the `run status` pointer.

| Error | What to do |
| --- | --- |
| `revision_conflict` | `tdp agent plan snapshot` or `production snapshot`; retry with current revision |
| `capability_denied` | Ensure `TDP_CAPABILITY_TOKEN_FILE` is exported; mutating commands need an active session |
| `operation_error` + `hint` | Read `hint` in the JSON error; often points to `tdp agent example <name>` |
| `request_error` + `hint` | Review validation failures include `hint` (e.g. rubric union mismatch, invalid `rule_id`); see `tdp agent readme` |
| `unknown item id: <id>` | Unknown dependency target; check temp_id spelling and `tdp agent example expand-branch` |
| `duplicate temp_id in transaction` | Each `temp_id` must be unique within one `plan apply` batch |
| `production_evidence_incomplete` | Add every changed workspace path to batch `outputs` |
| `production_context_mutation_unauthorized` | Revert unauthorized skill/guidance drift |
| `audit attestation rubric_item_ids union mismatch` | Set `rubric_item_ids` from review package `rubric_items` (union across passes must equal every id); see `tdp agent readme` (Audit attestation) |
| `rule_id ... must be a built-in rule or match custom.<slug>` | Pick a built-in from `tdp agent readme` or use `custom.<slug>` + `rule_definition`; see `review-respond-family-discovery-output` for custom pattern |
| `limit_exhausted` + `limits.review.max_agent_turns_per_gate` | Reviewer turns ended without `review respond`; resume with `--set limits.review.max_agent_turns_per_gate=<n>` strictly above consumed `gate_agent_turns` (decrease is allowed when still above consumed) |

Run status and `agent_requests_dir`: `tdp agent run status --run <id>`

`production apply` may also return `capability_denied` when the orchestrator has not bound a session capability; retry apply without caching capability state in the shell.

Related: [protocol](protocol.md), [agent CLI](cli.md), [agent hub](README.md).
