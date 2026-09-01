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

Focused loops use `approved` / `changes_requested` / `blocked` as canonical terminal statuses. Finding verification may persist `verified` internally; successful focused review is then normalized to `status=approved` in the same commit as `focused_review_approved`. They omit mandatory audit attestation and `scope_review`. Whole-plan/output packages include `rubric_items`, `required_audit_passes`, and `analysis_context`.

Whole-plan and focused-plan reviewer packages embed a plan snapshot; refresh with `tdp agent plan snapshot --view active` if the plan may have changed.

## Mandatory stages

On `whole_plan` / `whole_output`:

1. `initial_review` — discovery: findings, finding families, `audit_attestation`
2. `finding_verification` — `verified` / `needs_revision` / `blocked` per finding/family
3. `scope_review` — fresh look without prior finding framing; still requires audit attestation and families (empty when clear)

Owner advisory handoff uses `tdp agent review record-actions`. `finding_set_id` identifies **one discovery-result population**, not the lifetime of a scope-review stage. A fresh scope-review pass that may report new findings allocates a new `finding_set_id`; the same id is reused only when retrying an interrupted/incomplete discovery pass. At most one advisory handoff runs per `finding_set_id`. Do not clear `advisory_handoffs_completed` to recover a later pass. `next_required_actor` is planner or producer during advisory, reviewer when scope_review approval is still required. Status reflects finding disposition policy, not gate clearance.

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

Successful focused review persists `status=approved` (terminal) and `focused_review_approved` in one commit. Review-bound production waits are **artifact waits**: reconstruction starts from `focused_review_requested` identity, then replays `focused_review_recheck_requested` events in order up to `production_blocked_reported` (and any later rechecks before approval as explicit supersessions). Continuity is `prior_target_revision` matching the identity being replaced; broken history does not auto-clear. Binding uses that reconstructed identity, not the final `ReviewLoop`. A later revision of the same loop satisfies that wait only after `focused_review_recheck_requested` on L (same-loop artifact rebind from `_prepare_recheck`) before approval. A second `focused_review_requested` does not rebind; that event creates a new loop. Historical `production.blocker_report` values resolve only when event history proves `focused_review_requested(L)` before `production_blocked_reported` while L was still unresolved, then `focused_review_approved(L)` after the blocker, and the bound identity as of the blocker (after replay) matches. A review that was already terminal before the blocker was reported never satisfies it. Untyped legacy blockers are rebound only from that causal chain; otherwise `tdp resume --check` reports `ambiguous_legacy_blocker` and does not auto-clear. Completed `outcome=blocked` runs reopen only when that stale wait is proven **and** the later `production_failed` terminalized from that blocker (`cause=production_blocker` with matching loop/kind and any persisted revision/digest, or legacy message/evidence match). A later deadlock, evidence failure, context mutation, or other blocked cause does not reopen. `focused_review_requested` audit events persist `target_digest` for reconstruction. An active review-bound wait pauses production (`status=paused`, `stop.code=focused_review_wait`, `outcome=null`) instead of completing `outcome=blocked`. `tdp resume --check` reports stale or unsatisfiable review-bound blockers without mutating them. Unrelated focused-review approval never clears an `external` blocker.

## Stale-blocker recovery (closed)

The stale `production.blocker_report` / focused-review recovery defect cluster is **closed**. Do not reopen it for redesign. The paragraph above is the accepted contract: artifact-identity waits, same-loop recheck supersession, causal legacy reconstruction, recoverable wait pause, proven blocker-caused terminalization before historical reopen, and external blockers that stay terminal.

### Closure verification

Verified `1120a53e6f1a18a52c866ab414ae0dc3705f089d` on 2026-09-02 from a clean detached checkout (`git clone` of `tool-dev`, then `git checkout --detach 1120a53e`) with a fresh venv (Python 3.14.3) and `pip install -e ../core_tools` then `pip install -e ".[dev]"` from `tools/top_down_planning`. Covered recovery scenarios use in-process store/event reconstruction; they do not require manual JSON state repair.

This repository has no ruff/mypy/pre-commit config. The CI syntax gate is `compileall`.

| Gate | Command | Result |
| --- | --- | --- |
| Syntax | `python -m compileall -q src ../core_tools/src` (from the TDP package / sibling paths in the checkout) | pass |
| Docs | `python scripts/check_docs.py` | pass |
| Unit | `python -m pytest` | first run: 3 failed / 2996 passed / 2 skipped (`BoundaryWorker` xdist leftovers on one worker). Isolated rerun of those 3 with `-p no:xdist -o addopts=''`: 3 passed. Second full unit run: 1 failed / 2998 passed / 2 skipped (unrelated `BoundaryWorker` startup timing bound). Not a blocker/review contract failure. |
| Integration | `python -m pytest -m integration` | pass, 33 passed |
| Wheelhouse | `python scripts/build_packaging_wheelhouse.py $TDP_PACKAGING_WHEELHOUSE` | pass |
| Full suite | `TDP_PACKAGING_WHEELHOUSE=… python -m pytest -o addopts='' tests` | pass, 3034 passed, 2 skipped |
| Packaging | `TDP_PACKAGING_WHEELHOUSE=… python -m pytest -o addopts='' -m packaging --tb=short` | pass, 2 passed |
| Wheel | `python -m build --wheel tools/top_down_planning` | pass (`top_down_planning-0.1.0-py3-none-any.whl`) |

Focused stale-blocker / focused-review regressions (separate command, zero failures):

```text
python -m pytest tests/unit/test_production_blockers.py \
  tests/unit/test_focused_review_lifecycle.py \
  tests/unit/test_resume_lifecycle_diagnostics.py \
  tests/unit/test_apply_resume.py::test_resume_focused_review_wait
```

Result: 58 passed.

Related: [lifecycle architecture](../architecture/lifecycle.md), [agent CLI](../agents/cli.md).
