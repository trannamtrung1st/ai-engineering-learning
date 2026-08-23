# Decision: split configuration digests and drift policy

**Status:** verified current behavior.

**Evidence:** `persistence/digests.py` (`contract_config_projection`, `execution_config_projection`); `config/resume_policy.py` (`RESUME_EXECUTION_POLICY_ALLOWLIST`, `resolve_resume_candidate_config`); `domain/approval_digests.py` (`PLAN_APPROVAL_DIGEST_KEYS`, `OUTPUT_APPROVAL_DIGEST_KEYS`); `orchestrator/prepare_resume.py` (`_approval_binding_valid`); `tests/unit/test_design_decisions.py` (`test_decision_7`–`9`); `tests/unit/test_no_monolithic_config_digest.py`; `tdp agent readme` (Resume).

Mechanics: [config and snapshots](../internals/config-and-snapshots.md). Operator hatch: [configuration](../manual/configuration.md#resume-and-drift).

## Binding choice

Approval identity and operational limits are **different digest axes**. A single `digests.config` field is not accepted on schema v3.

| Digest | Projection |
| --- | --- |
| `config_contract` | Semantic config excluding `limits`, `observability`, `notifications`, `runtime.runs_dir` |
| `config_execution` | `limits` only |

`prepare_resume` is read-only (`test_decision_12_prepare_resume_is_pure`: no `store.save_run` / `store.append_event`). Candidate config is resolved during resume (`resolve_resume_candidate_config`). Production source must not read or write `digests.config` except to reject it.

## Verified consequences

- Whole-plan approval binds `plan`, `config_contract`, `input`, `output_goal`, and `context_spec` only. When a current whole-output approval exists, resume also matches `output` and `context_snapshot`. A pending `whole_output` loop does **not** require those output snapshot keys on the plan approval (`prepare_resume._approval_binding_valid` returns after the plan-key match when `find_whole_output_approval` is `None`).
- Limit-only `--set` updates `config_execution` and does **not** invalidate whole-plan/output approvals bound to `config_contract`.
- Changing `observability.*`, `notifications.*`, or `runtime.runs_dir` does not change either digest (presentation tier).
- Default resume **rejects** contract drift and non-model `context_spec` drift. `--allow-config-drift` applies contract/model changes only **before** whole-plan approval; after approval those changes are ignored with warnings.
- When `limit_exhausted` tracks `consumed`, the candidate limit must be strictly greater than consumed (`RESUME_EXECUTION_POLICY_ALLOWLIST` includes paths such as `limits.planning.max_agent_turns`).
- `context_spec` vs `context_snapshot` is a further split (declarations vs materialized bytes); production may authorize **resource** snapshot drift via outputs, not skills/guidance.

## Not claimed

This record does not invent a timeline for splitting digests or assert unpublished motivations. It only states the projections and resume rules the code and tests enforce today.

Related: [lifecycle stop states](lifecycle-stop-states.md).
