"""Pure resume planning (proposal §9.2)."""

from __future__ import annotations

from typing import Any

from core_tools.config import resolve_workspace

from top_down_planning.agent_tool.artifacts import verify_evidence_snapshot
from top_down_planning.config import (
    compute_input_digest,
    compute_output_goal_digest,
)
from top_down_planning.config.context_digests import validate_resume_context_bindings
from top_down_planning.config.resume_policy import (
    compare_resume_configs,
    validate_resume_config_comparison,
)
from top_down_planning.domain.approval_digests import (
    OUTPUT_APPROVAL_DIGEST_KEYS,
    PLAN_APPROVAL_DIGEST_KEYS,
    reject_legacy_approved_config_digest,
)
from top_down_planning.domain.resume_limits import consumed_limits_from_run
from top_down_planning.domain.resume_plan import (
    ResumePlan,
    ResumePlanValidation,
    ResumeStateTransition,
)
from top_down_planning.orchestrator.session_policy_execution import derive_session_policy
from top_down_planning.domain.reviews import (
    find_conflicting_active_review_loops,
    find_whole_plan_approval,
)
from top_down_planning.domain.run_lifecycle import validate_run_lifecycle_invariants
from top_down_planning.domain.session_recovery_state import (
    replacement_attempted_for_phase_action,
)
from top_down_planning.domain.run_ownership import (
    RunOwnershipError,
    assert_no_live_process_owns_run,
    resolve_run_dir,
)
from top_down_planning.orchestrator.errors import OrchestratorError
from top_down_planning.orchestrator.phases import (
    OUTPUT_VALIDATED,
    PLAN_AMENDMENT,
    PLAN_VALIDATED,
    PRODUCTION,
    WHOLE_OUTPUT_REVIEW,
)
from top_down_planning.orchestrator.resume_stop_validators import (
    ResumeStopValidationError,
    validate_stop_for_resume_apply,
)
from top_down_planning.persistence.digests import (
    compute_config_contract_digest,
    compute_output_digest,
    compute_plan_digest,
)
from top_down_planning.persistence.interface import RunStore
from top_down_planning.persistence.run_schema import (
    validate_run_digests,
    validate_run_schema_version,
)
from top_down_planning.workspace import run_workspace


class PrepareResumeBlockedError(OrchestratorError):
    """Resume preparation refused without mutating the run store."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "resume_preparation_blocked",
        blockers: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message, code=code)
        self.blockers = blockers


def _raise_blocked(message: str, *, code: str = "resume_preparation_blocked") -> None:
    raise PrepareResumeBlockedError(message, code=code, blockers=(message,))


def _verify_production_evidence(
    store: RunStore,
    run_id: str,
    production: dict[str, Any],
) -> str | None:
    for entry in production.get("output_evidence") or []:
        if not isinstance(entry, dict):
            return "production output_evidence entry is invalid"
        try:
            verify_evidence_snapshot(store, run_id, entry)
        except Exception as exc:
            return f"evidence integrity failure: {exc}"
    for batch in production.get("batches") or []:
        if not isinstance(batch, dict):
            continue
        if batch.get("evidence_status") == "invalidated_by_reconciliation":
            continue
        result = batch.get("result")
        if not isinstance(result, dict):
            continue
        for output in result.get("outputs") or []:
            if not isinstance(output, dict):
                continue
            if not output.get("snapshot_ref"):
                continue
            try:
                verify_evidence_snapshot(store, run_id, output)
            except Exception as exc:
                return f"evidence integrity failure: {exc}"
    return None


_APPROVAL_REQUIRED_PHASES = frozenset(
    {
        PLAN_VALIDATED,
        PRODUCTION,
        WHOLE_OUTPUT_REVIEW,
        PLAN_AMENDMENT,
    }
)


def _approval_binding_valid(
    reviews: list[dict[str, Any]],
    plan: dict[str, Any],
    run_digests: dict[str, str],
    *,
    phase: str,
) -> bool:
    plan_revision = int(plan.get("revision") or 0)
    approval = find_whole_plan_approval(reviews, plan_revision)
    if approval is None:
        return False
    approved = approval.get("approved_digests")
    if not isinstance(approved, dict):
        return False
    try:
        reject_legacy_approved_config_digest(approved)
    except ValueError:
        return False
    required_keys = PLAN_APPROVAL_DIGEST_KEYS
    if phase in {OUTPUT_VALIDATED} or any(
        payload.get("type") == "whole_output" for payload in reviews
    ):
        required_keys = OUTPUT_APPROVAL_DIGEST_KEYS
    for key in required_keys:
        if str(approved.get(key) or "") != str(run_digests.get(key) or ""):
            return False
    return True


def prepare_resume(
    store: RunStore,
    run_id: str,
    candidate_config: dict[str, Any],
    consumed_limits: dict[str, int] | None = None,
) -> ResumePlan:
    """Build a read-only resume plan or raise when canonical invariants block resume."""

    run = store.load_run(run_id)
    validate_run_schema_version(run)
    validate_run_digests(run)
    validate_run_lifecycle_invariants(run)

    status = str(run.get("status") or "running")
    outcome = run.get("outcome")
    phase = str(run.get("phase") or "")
    expected_revision = int(run.get("revision") or 0)
    run_digests = {
        str(key): str(value)
        for key, value in dict(run.get("digests") or {}).items()
    }

    if status == "failed":
        _raise_blocked("failed runs cannot be resumed", code="failed_run_not_resumable")

    if status == "completed" or outcome is not None:
        return ResumePlan(
            run_id=run_id,
            expected_run_revision=expected_revision,
            state_transition=None,
            config_changes={},
            session_policy=derive_session_policy(run, store.list_reviews(run_id)),
            validation=ResumePlanValidation(
                contract_digest_valid=True,
                plan_binding_valid=True,
                approval_binding_valid=True,
                evidence_binding_valid=True,
                context_binding_valid=True,
            ),
            already_completed=True,
            message="run already completed",
        )

    run_dir = resolve_run_dir(store, run_id)
    if run_dir is not None:
        try:
            assert_no_live_process_owns_run(run_id, run_dir=run_dir)
        except RunOwnershipError as exc:
            _raise_blocked(str(exc), code=exc.code)

    stored_config = store.load_resolved_config(run_id)
    workspace = run_workspace(run)
    plan = store.load_plan(run_id)
    production = store.load_production(run_id)
    reviews = store.list_reviews(run_id)

    blockers: list[str] = []

    stored_ws = resolve_workspace(stored_config, cwd=workspace)
    candidate_ws = resolve_workspace(candidate_config, cwd=workspace)
    if stored_ws.resolve() != candidate_ws.resolve():
        blockers.append("workspace change blocked during resume")

    input_digest = compute_input_digest(candidate_config, base_dir=workspace)
    if input_digest != run_digests.get("input"):
        blockers.append("input digest mismatch blocks resume")

    output_goal_digest = compute_output_goal_digest(candidate_config, base_dir=workspace)
    if output_goal_digest != run_digests.get("output_goal"):
        blockers.append("output-goal digest mismatch blocks resume")

    contract_digest = compute_config_contract_digest(candidate_config)
    contract_digest_valid = contract_digest == run_digests.get("config_contract")
    if not contract_digest_valid:
        blockers.append("config_contract digest mismatch blocks resume")

    plan_digest = compute_plan_digest(plan)
    plan_binding_valid = plan_digest == run_digests.get("plan")
    if not plan_binding_valid:
        blockers.append("plan digest mismatch blocks resume")

    output_digest = compute_output_digest(production)
    output_digest_expected = run_digests.get("output")
    evidence_binding_valid = (
        output_digest_expected is None or output_digest == output_digest_expected
    )
    if not evidence_binding_valid:
        blockers.append("output/production digest mismatch blocks resume")

    context_error = validate_resume_context_bindings(
        run,
        production,
        candidate_config,
        workspace=workspace,
    )
    context_binding_valid = context_error is None
    if context_error is not None:
        blockers.append(context_error)

    approval_binding_valid = _approval_binding_valid(
        reviews,
        plan,
        run_digests,
        phase=phase,
    )
    if not approval_binding_valid and phase in _APPROVAL_REQUIRED_PHASES:
        blockers.append("approval binding is invalid for current artifacts")

    conflicting_loops = find_conflicting_active_review_loops(reviews)
    if conflicting_loops:
        joined = ", ".join(conflicting_loops)
        blockers.append(f"conflicting active review loops: {joined}")

    evidence_error = _verify_production_evidence(store, run_id, production)
    if evidence_error is not None:
        blockers.append(evidence_error)

    comparison = validate_resume_config_comparison(
        compare_resume_configs(stored_config, candidate_config),
        consumed_limits=consumed_limits or consumed_limits_from_run(run),
    )
    if not comparison.ok:
        blockers.extend(comparison.errors)

    if status == "paused":
        stop = run.get("stop")
        if isinstance(stop, dict):
            try:
                validate_stop_for_resume_apply(store, run_id, run, stop)
            except ResumeStopValidationError as exc:
                blockers.append(str(exc))
        phase_action_id = run.get("phase_action_id")
        if phase_action_id and replacement_attempted_for_phase_action(
            run,
            str(phase_action_id),
        ):
            blockers.append(
                "replacement already exhausted for the current logical action"
            )

    if blockers:
        raise PrepareResumeBlockedError(
            blockers[0],
            code="resume_preparation_blocked",
            blockers=tuple(blockers),
        )

    config_changes = {
        change.path: {"from": change.stored_value, "to": change.candidate_value}
        for change in comparison.changes
    }

    if status == "running":
        transition = ResumeStateTransition(from_status="running", to_status="running")
    else:
        stop = run.get("stop") if isinstance(run.get("stop"), dict) else {}
        transition = ResumeStateTransition(
            from_status="paused",
            to_status="running",
            prior_stop_code=str(stop.get("code")) if stop else None,
        )

    return ResumePlan(
        run_id=run_id,
        expected_run_revision=expected_revision,
        state_transition=transition,
        config_changes=config_changes,
        session_policy=derive_session_policy(run, reviews),
        validation=ResumePlanValidation(
            contract_digest_valid=contract_digest_valid,
            plan_binding_valid=plan_binding_valid,
            approval_binding_valid=approval_binding_valid,
            evidence_binding_valid=evidence_binding_valid,
            context_binding_valid=context_binding_valid,
        ),
    )
