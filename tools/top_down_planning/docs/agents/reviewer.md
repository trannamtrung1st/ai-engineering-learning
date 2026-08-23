# Reviewer protocol

**Audience:** the reviewer agent (and owner advisory turns) in a provider session.

Judge a plan or output artifact against the review package. Do not apply plan mutations or production batches. Shared request-file rules: [protocol](protocol.md). Stages and loop types: [lifecycle terms](../concepts/lifecycle-terms.md).

## Commands

| Task | Command | Example (whole-plan) |
| --- | --- | --- |
| Respond | `tdp agent review respond --run <id> --request ...` | `review-respond-family-discovery` |
| Owner actions | `tdp agent review record-actions --run <id> --request ...` | `review-record-family-fix` |
| Verification | same `review respond` | `review-respond-family-verification` |
| Scope review | same `review respond` | `review-respond-scope` |

Whole-output examples append `-output` (e.g. `review-respond-family-discovery-output`).

Schema: `tdp agent schema review-respond`

List all examples: `tdp agent example`

Whole-plan and focused_plan reviewers receive an embedded plan snapshot in the review package; call `tdp agent plan snapshot --run <id> --view active` to refresh before responding when the plan may have changed.

Reviewer turns close when `review respond` persists a decision: the orchestrator aborts the in-flight provider turn, waits for the session collector to settle, then releases the bounded reviewer session (`reviewer_session_ended`) before owner revision or the next gate. Owner advisory turns close when `review record-actions` persists. A turn that ends without `review respond` queues another reviewer turn with a nudge (bounded by `limits.review.max_agent_turns_per_gate`) before pausing with `limit_exhausted`. A background poll also watches for persisted review decisions while the turn is open so a stalled agent subprocess cannot block progress after respond.

## Mandatory whole-plan and whole-output

Mandatory discovery: `audit_attestation` rubric ids come from the review package `rubric_items`; `rule_id` values from `tdp agent readme` (section Built-in finding-family rule_id values) or `custom.<slug>`. Union of `rubric_item_ids` across audit passes must equal every `rubric_items[].id`. `pass_id` comes from `required_audit_passes`.

| Stage | Example (plan) | Example (output) |
| --- | --- | --- |
| `initial_review` (discovery) | `review-respond-family-discovery` | `review-respond-family-discovery-output` |
| `finding_verification` | `review-respond-family-verification` | `review-respond-family-verification-output` |
| `scope_review` | `review-respond-scope` | `review-respond-scope` (adapt ids) |

Copy `target_revision`, `target_digest`, `loop_id`, and `finding_set_id` from the review package. Do not read TDP Python source to discover `review respond` payload shapes.

Finding `severity` and `category` must match `review_policy` in the package (`tdp agent readme`, section Review finding categories).

## Focused reviews

Focused loops omit mandatory `stage` / audit-attestation contracts used by whole-plan and whole-output. Decisions are `approved`, `changes_requested`, or `blocked`.

| Situation | Example |
| --- | --- |
| Focused plan discovery | `review-respond` |
| Focused plan with `instance_ref` | `review-respond-focused-with-instance-ref` |
| Focused plan family discovery | `review-respond-family-discovery-focused-plan` |
| Focused output family discovery | `review-respond-family-discovery-focused-output` |
| Focused finding verification | `review-respond-verification` |

`instance_ref.item_id` must stay within `scope.item_ids`.

## Owner record-actions

Primary planner or producer records `fix`, `challenge`, `defer`, or `accept_as_is` on open findings after an advisory handoff. Required findings may only use `fix` or `challenge`. Optional findings may also use `defer` or `accept_as_is`. Challenges require `challenge_reason`, `proposed_disposition`, and `rationale`. `default_optional_action` batch-applies a default to remaining optional findings in the current finding set.

When `family_fixes` is present, `target_revision` and `target_digest` must match the current artifact. Repeat `record-actions` at the current digest to rebind an owner sweep without duplicating existing owner fix actions.

Examples: `review-record-finding-actions`, `review-record-family-fix` (plan), `review-record-family-fix-output` (producer). Schema: `tdp agent schema review-record-finding-actions`.

Related: [agent CLI](cli.md), [troubleshooting](troubleshooting.md), [review internals](../internals/reviews.md).
