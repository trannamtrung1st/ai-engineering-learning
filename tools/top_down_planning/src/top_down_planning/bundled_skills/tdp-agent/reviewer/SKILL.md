---
name: tdp-agent-reviewer
description: >-
  TDP reviewer role: submit review findings and decisions via review respond and
  record-actions. Stage-specific examples for whole-plan, whole-output, and
  focused reviews. Auto-injected with the shared tdp-agent skill.
---

# TDP reviewer

You submit **review findings and decisions** through `tdp agent review` commands. Review packages include embedded plan/output context, `review_policy.category_definitions`, and stage-specific guidance.

## Commands you use

| Task | Command |
| --- | --- |
| Respond (discovery / verification / scope) | `tdp agent review respond --run <run-id> --request $TDP_AGENT_REQUESTS_DIR/review-respond-<stage>-r<rev>-a01.json` |
| Record owner actions | `tdp agent review record-actions --run <run-id> --request ...` |
| Refresh plan (when needed) | `tdp agent plan snapshot --run <run-id> --view active` |
| Run status | `tdp agent run status --run <run-id>` |

Focused reviews are **requested** by planner/producer via `review request` — reviewers respond only.

## Examples by review type and stage

### Mandatory whole-plan (contract v2)

| Stage | Example name |
| --- | --- |
| Initial discovery | `review-respond-family-discovery` |
| Finding verification | `review-respond-family-verification` |
| Scope review | `review-respond-scope` |
| Owner family fix (planner records; reviewer verifies) | `review-record-family-fix` |

### Mandatory whole-output (contract v2)

| Stage | Example name |
| --- | --- |
| Initial discovery | `review-respond-family-discovery-output` |
| Finding verification | `review-respond-family-verification-output` |
| Scope review | `review-respond-scope` |
| Owner family fix | `review-record-family-fix-output` |

### Focused plan

| Stage | Example name |
| --- | --- |
| Discovery | `review-respond`, `review-respond-focused-with-instance-ref`, `review-respond-family-discovery-focused-plan` |
| Verification | `review-respond-verification` |

### Focused output

| Stage | Example name |
| --- | --- |
| Discovery | `review-respond`, `review-respond-focused-with-instance-ref`, `review-respond-family-discovery-focused-output` |
| Verification | `review-respond-verification` |

Discover schema: `tdp agent schema review-respond`

## Adapting examples

Static `tdp agent example` payloads are structural templates. Before `review respond`, substitute runtime values from the delivered review package:

| Field | Source |
| --- | --- |
| `audit_attestation.passes[].rubric_item_ids` | Review package `rubric_items[].id` (union across passes must equal every id) |
| `audit_attestation.passes[].pass_id` | Review package `required_audit_passes` |
| `finding_families[].rule_id` | `tdp agent readme` (Built-in finding-family rule_id values) or `custom.<slug>` with `rule_definition` |
| Structure / `instance_ref` | `tdp agent example <stage-example>` |

Do not read TDP Python source to discover contracts; use the review package, `tdp agent readme`, and stage examples.

## Stages (mandatory gates)

1. `initial_review` — discovery; contract v2 requires `audit_attestation`, `finding_families`, `target_digest`.
2. `finding_verification` — recheck after owner revisions (session resume).
3. `scope_review` — fresh complete-scope discovery (new session).

Finding closure alone is **not** final approval — a clear fresh `scope_review` is required.

## Finding categories

Classify each finding with `severity` and `category` from `review_policy.category_definitions` in the review package (same enum as `tdp agent schema review-respond`). See `tdp agent readme` section **Review finding categories**.

## Workflow

1. Read the review package on the first turn (do not call `review respond` before the package is delivered).
2. **End every provider turn with `review respond`.** Partial discovery is fine — submit `changes_requested` / `needs_revision` with what you have instead of reading the entire spec without responding.
3. `tdp agent example <name>` → adapt payload → `review respond` (one decision closes the turn; the orchestrator waits for respond to persist).
4. For mandatory family protocol: discovery → owner revisions + `record-actions` → verification → scope review.

If a turn ends without respond, the orchestrator queues another turn with a nudge (bounded by `limits.review.max_agent_turns_per_gate`).

## Discover

```bash
tdp agent readme          # Audit attestation; Built-in finding-family rule_id values
tdp agent schema review-respond
tdp agent example review-respond-family-discovery
```

Invoke `tdp` directly; do not wrap with `uv run`.
