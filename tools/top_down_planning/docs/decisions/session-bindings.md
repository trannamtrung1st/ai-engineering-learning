# Decision: replaceable session bindings and recovery manifests

**Status:** verified current behavior.

**Evidence:** `domain/session_bindings.py` (`with_next_generation`); `orchestrator/recovery_manifest.py`; `tests/unit/test_design_decisions.py` (`test_decision_10`, `test_decision_11`); `tests/unit/test_session_recovery_enforcement.py` (one replacement per `phase_action_id`); package README provider section; `tdp agent readme`.

Architecture: [sessions](../architecture/sessions.md).

## Binding choice

Provider sessions are **replaceable bindings**, not a single immortal remote id. Each binding has `session_instance_id`, `generation`, `provider_session_id`, and `state`. `with_next_generation()` increments `generation` and allocates a new `session_instance_id`.

Recovery prompts are built from **durable run state** (`build_planner_recovery_manifest` and siblings), not from in-memory Cursor handles alone. Transient `cursor-pending-*` ids are never passed to Cursor `--resume`.

`prepare_resume()` is a pure plan; apply is `apply_resume_plan_atomically()`. CLI resume uses those two steps (`test_cli_resume_uses_prepare_and_apply_not_legacy`). Legacy `validate_resume_preconditions` / `ResumeError` symbols are absent from production source.

## Verified consequences

- Missing remote session (`provider_session_not_found`) and idle stall (`provider_turn_stalled`) each allow **one** replacement attempt per `phase_action_id`.
- A second not-found for the same action is refused; exhausted replacement marks the run `failed` with `session_recovery_exhausted` (invariant stop — not a pause).
- Durable `session_id` is persisted during the turn (`state: bound`). Capability records include `session_instance_id` and `generation`; a generation change revokes prior tokens ([agent authorization](agent-authorization.md)).
- Session resume requires the same role, activity, and context digest; activity changes start a fresh provider session.

## Not claimed

This record does not reconstruct earlier session-id storage shapes or invent why replacement is capped at one attempt beyond the tests that enforce that cap.

Related: [lifecycle stop states](lifecycle-stop-states.md), [security](../internals/security.md).
