# Review architecture

**Audience:** maintainers of focused and mandatory review loops.

Reviewer protocol (payloads, examples): [reviewer](../agents/reviewer.md). Vocabulary: [lifecycle terms](../concepts/lifecycle-terms.md). Domain types: [domain model](../architecture/domain.md).

## Loop types

| Type | When | Gate |
| --- | --- | --- |
| `focused_plan` | Optional during planning | Scoped `item_ids` |
| `focused_output` | Optional during production | Scoped `item_ids` |
| `whole_plan` | Mandatory after `candidate_plan_ready` | Entire plan revision |
| `whole_output` | Mandatory after completion claim | Entire output revision |

Focused loops use `approved` / `changes_requested` / `blocked`. They omit mandatory audit attestation and `scope_review`. Whole-plan/output packages include `rubric_items`, `required_audit_passes`, and `analysis_context`.

Whole-plan and focused-plan reviewer packages embed a plan snapshot; refresh with `tdp agent plan snapshot --view active` if the plan may have changed.

## Mandatory stages

On `whole_plan` / `whole_output`:

1. `initial_review` — discovery: findings, finding families, `audit_attestation`
2. `finding_verification` — `verified` / `needs_revision` / `blocked` per finding/family
3. `scope_review` — fresh look without prior finding framing; still requires audit attestation and families (empty when clear)

Owner advisory handoff uses `tdp agent review record-actions`. `next_required_actor` is planner or producer during advisory, reviewer when scope_review approval is still required. Status reflects finding disposition policy, not gate clearance.

## Finding families and `rule_id`

Families group findings under a `rule_id`: a built-in from `tdp agent readme` (Built-in finding-family rule_id values) or `custom.<slug>` plus `rule_definition`. Built-ins currently include:

`dependency.acceptance_capability_available`, `hierarchy.aggregate_executable_work`, `requirements.modality_preservation`, `acceptance.branch_completeness`, `hierarchy.executable_parent_overlap`, `dependencies.duplicate_target`, `dependencies.cycle`, `contract.ownership_placement`, `coverage.traceability_gap`, `scope.field_placement`.

Prefer the readme list at runtime. Finding `severity` / `category` come from `review_policy` in the package, not from rubric theme names.

## Audit attestation

Union of `rubric_item_ids` across `required_audit_passes` must equal every `rubric_items[].id`. `pass_id` must match a required pass. Mismatch: `audit attestation rubric_item_ids union mismatch` ([agent troubleshooting](../agents/troubleshooting.md)).

## Verification and scope review

Verification targets previously reported findings (`finding_set_id` echo). New direct side-effect findings have their own field on family-verification examples. Scope review is a **round** counter (`scope_review_rounds`) distinct from verification `revision_cycles`. Convergence warning after several scope rounds is an advisory, not a stop code.

Whole-plan approval binds `plan`, `config_contract`, `input`, `output_goal`, and `context_spec`. Approved whole-output approval binds those keys plus `output` and `context_snapshot`. A pending `whole_output` loop does not require the extra output snapshot keys on the plan approval. Operator table: [configuration](../manual/configuration.md#resume-and-drift). Rationale: [split-digest decision](../decisions/split-config-digests.md).

## Loop limits

Exact-N semantics (maximum allowed attempts, not N+1). Package defaults:

| Path | Default | Meaning |
| --- | --- | --- |
| `limits.focused_plan_review.max_loops` | 5 | Focused plan loops |
| `limits.focused_plan_review.max_revision_cycles_per_loop` | 3 | Owner revisions per focused plan loop |
| `limits.focused_output_review.max_loops` | 8 | Focused output loops |
| `limits.focused_output_review.max_revision_cycles_per_loop` | 3 | Owner revisions per focused output loop |
| `limits.whole_plan_review.max_revision_cycles` | 5 | Owner revisions (mandatory plan) |
| `limits.whole_plan_review.max_scope_review_rounds` | 3 | Scope-review rounds (mandatory plan) |
| `limits.whole_output_review.max_revision_cycles` | 5 | Owner revisions (mandatory output) |
| `limits.whole_output_review.max_scope_review_rounds` | 3 | Scope-review rounds (mandatory output) |
| `limits.review.max_agent_turns_per_gate` | 5 | Reviewer turns without `review respond` |

Review-driver enforcement: increment on `changes_requested` / `needs_revision`, then block when `revision_cycles > max` before the next owner revision. Gate turns pause with `limit_exhausted` when `gate_agent_turns` reaches the max; resume requires the candidate limit **strictly above** consumed. Raising the limit revives the **same** loop; it does not reset counters.

Related: [lifecycle architecture](../architecture/lifecycle.md), [agent CLI](../agents/cli.md).
