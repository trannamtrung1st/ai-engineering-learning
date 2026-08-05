"""Atomic resume plan apply (proposal §9.3)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core_tools.persistence import StoreRevisionConflictError

from top_down_planning.config import compute_input_digest, compute_output_goal_digest
from top_down_planning.config.context import compute_context_spec_digest_from_config
from top_down_planning.domain.resume_limits import consumed_limits_from_run
from top_down_planning.domain.resume_plan import ResumePlan
from top_down_planning.domain.reviews import (
    ReviewLoop,
    prepare_limit_reached_retry,
    prepare_review_incomplete_retry,
)
from top_down_planning.domain.run_ownership import (
    RunOwnershipError,
    assert_expected_run_revision,
    assert_no_live_process_owns_run,
    resolve_run_dir,
)
from top_down_planning.orchestrator.errors import OrchestratorError
from top_down_planning.orchestrator.resume_stop_validators import (
    ResumeStopValidationError,
    validate_stop_for_resume_apply,
)
from top_down_planning.persistence.commit import CommitSpec
from top_down_planning.persistence.config_commit import (
    ResumeConfigCommitError,
    validate_and_prepare_resume_config_update,
)
from top_down_planning.persistence.digests import compute_config_execution_digest
from top_down_planning.persistence.file_store import FileRunStore
from top_down_planning.workspace import run_workspace


class ApplyResumeError(OrchestratorError):
    """Resume apply refused or persistence failed."""


def _review_updates_for_resume_apply(
    *,
    review_loop: ReviewLoop | None,
) -> list[dict[str, Any]]:
    if review_loop is None:
        return []
    if review_loop.lifecycle_status == "limit_reached":
        normalized = prepare_limit_reached_retry(review_loop)
    else:
        normalized = prepare_review_incomplete_retry(review_loop)
    if normalized.to_dict() == review_loop.to_dict():
        return []
    return [normalized.to_dict()]


def _limit_extended_paths(config_changes: dict[str, dict[str, Any]]) -> list[str]:
    return sorted(
        path
        for path in config_changes
        if path.startswith("limits.")
    )


def apply_resume_plan_atomically(
    store: FileRunStore,
    resume_plan: ResumePlan,
    *,
    resolved_config: dict[str, Any],
    invocation: dict[str, Any] | None = None,
    consumed_limits: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Apply a prepared resume plan in one journaled commit."""

    if resume_plan.already_completed:
        return {
            "ok": True,
            "already_completed": True,
            "run_id": resume_plan.run_id,
            "message": resume_plan.message,
        }

    run_id = resume_plan.run_id
    run = store.load_run(run_id)
    expected_revision = resume_plan.expected_run_revision

    try:
        assert_expected_run_revision(run, expected_revision)
        run_dir = resolve_run_dir(store, run_id)
        if run_dir is not None:
            assert_no_live_process_owns_run(run_id, run_dir=run_dir)
    except RunOwnershipError as exc:
        raise ApplyResumeError(str(exc), code=exc.code) from exc

    prior_status = str(run.get("status") or "running")
    prior_stop = run.get("stop")
    prior_phase = str(run.get("phase") or "")
    digests = dict(run.get("digests") or {})
    old_execution_digest = str(digests.get("config_execution") or "")

    review_loop: ReviewLoop | None = None
    if prior_status == "paused" and isinstance(prior_stop, dict):
        try:
            review_loop = validate_stop_for_resume_apply(store, run_id, run, prior_stop)
        except ResumeStopValidationError as exc:
            raise ApplyResumeError(str(exc), code="resume_apply_blocked") from exc

    stored_config = store.load_resolved_config(run_id)
    stored_invocation = store.load_invocation(run_id)
    effective_config = resume_plan.effective_config or resolved_config
    plan_config_changes = dict(resume_plan.config_changes)
    try:
        config_update = validate_and_prepare_resume_config_update(
            stored_config=stored_config,
            candidate_config=effective_config,
            stored_invocation=stored_invocation,
            candidate_invocation=invocation or {},
            consumed_limits=consumed_limits or consumed_limits_from_run(run),
            contract_digest_may_change=resume_plan.contract_digest_may_change,
            context_spec_may_change=resume_plan.context_spec_may_change,
        )
    except ResumeConfigCommitError as exc:
        raise ApplyResumeError(str(exc), code="resume_apply_blocked") from exc

    run_payload = dict(run)
    run_payload["status"] = "running"
    run_payload["stop"] = None
    next_digests = dict(digests)
    next_digests["config_execution"] = config_update.config_execution_digest
    if resume_plan.contract_digest_may_change or resume_plan.context_spec_may_change:
        workspace = Path(run_workspace(run))
        next_digests["config_contract"] = config_update.config_contract_digest
        if resume_plan.contract_digest_may_change:
            next_digests["input"] = compute_input_digest(
                effective_config,
                base_dir=workspace,
            )
            next_digests["output_goal"] = compute_output_goal_digest(
                effective_config,
                base_dir=workspace,
            )
        next_digests["context_spec"] = compute_context_spec_digest_from_config(
            effective_config,
            workspace=workspace,
        )
    run_payload["digests"] = next_digests
    next_revision = expected_revision + 1
    run_payload["revision"] = next_revision

    events: list[dict[str, Any]] = [
        {
            "type": "resume_applied",
            "run_id": run_id,
            "expected_revision": expected_revision,
            "resulting_revision": next_revision,
            "phase": prior_phase,
            "prior_status": prior_status,
            "prior_stop": prior_stop,
            "config_changes": plan_config_changes,
            "ignored_config_changes": dict(resume_plan.ignored_config_changes),
            "warnings": list(resume_plan.warnings),
            "allow_config_drift": resume_plan.allow_config_drift,
            "contract_digest_may_change": resume_plan.contract_digest_may_change,
            "context_spec_may_change": resume_plan.context_spec_may_change,
            "old_config_execution_digest": old_execution_digest,
            "new_config_execution_digest": config_update.config_execution_digest,
            "session_policy": dict(resume_plan.session_policy),
            "invocation": dict(config_update.invocation),
        }
    ]
    extended_paths = _limit_extended_paths(plan_config_changes)
    if extended_paths:
        events.append(
            {
                "type": "resume_limit_extended",
                "run_id": run_id,
                "paths": extended_paths,
                "config_changes": {
                    path: plan_config_changes[path] for path in extended_paths
                },
            }
        )
    if resume_plan.allow_config_drift and (
        plan_config_changes or resume_plan.ignored_config_changes
    ):
        events.append(
            {
                "type": "resume_config_drift",
                "run_id": run_id,
                "applied_changes": plan_config_changes,
                "ignored_changes": dict(resume_plan.ignored_config_changes),
                "warnings": list(resume_plan.warnings),
                "contract_digest_may_change": resume_plan.contract_digest_may_change,
                "context_spec_may_change": resume_plan.context_spec_may_change,
            }
        )

    spec = CommitSpec(
        run=run_payload,
        run_expected_revision=expected_revision,
        resolved_config=config_update.resolved_config,
        invocation=config_update.invocation,
        reviews=_review_updates_for_resume_apply(review_loop=review_loop),
        events=events,
    )

    try:
        result = store.commit(run_id, spec)
    except StoreRevisionConflictError as exc:
        raise ApplyResumeError(
            f"resume apply revision conflict: expected {exc.expected}, found {exc.actual}",
            code="stale_resume_plan",
        ) from exc

    return {
        "ok": True,
        "run_id": run_id,
        "run_revision": int(result["run_revision"]),
        "prior_status": prior_status,
        "prior_stop": prior_stop,
        "config_changes": plan_config_changes,
        "old_config_execution_digest": old_execution_digest,
        "new_config_execution_digest": config_update.config_execution_digest,
        "limit_extended": bool(extended_paths),
        "contract_digest_may_change": resume_plan.contract_digest_may_change,
        "context_spec_may_change": resume_plan.context_spec_may_change,
    }


__all__ = ["ApplyResumeError", "apply_resume_plan_atomically"]
