"""Atomic resume plan apply (proposal §9.3)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core_tools.persistence import StoreRevisionConflictError

from top_down_planning.config import (
    compute_input_digest,
    compute_output_goal_digest,
    compute_unit_output_goal_digest,
)
from top_down_planning.config.context_digests import validate_resume_context_bindings
from top_down_planning.domain.run_kind import (
    RUN_KIND_PARENT_EXECUTION,
    RUN_KIND_SUB_TDP_EXECUTION,
    resolve_run_kind,
)
from top_down_planning.config.context import compute_context_spec_digest_from_config
from top_down_planning.domain.resume_limits import consumed_limits_from_run
from top_down_planning.domain.resume_plan import ResumePlan
from top_down_planning.domain.run_lifecycle import continuation_ok_from_run
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
from top_down_planning.orchestrator.phases import PRODUCTION
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
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if review_loop is None:
        return [], {}
    if review_loop.lifecycle_status == "limit_reached":
        normalized = prepare_limit_reached_retry(review_loop)
    else:
        normalized = prepare_review_incomplete_retry(review_loop)
    if normalized.to_dict() == review_loop.to_dict():
        return [], {}
    from top_down_planning.persistence.review_commit import review_record_revision

    loop_id = str(normalized.id)
    return [normalized.to_dict()], {loop_id: review_record_revision(review_loop.to_dict())}


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
        run = store.load_run(resume_plan.run_id)
        actual_status = str(run.get("status") or "")
        if actual_status != "completed":
            raise ApplyResumeError(
                f"already_completed resume plan does not match actual status "
                f"{actual_status!r}",
                code="resume_apply_blocked",
            )
        return {
            "ok": continuation_ok_from_run(run),
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

    actual_status = str(run.get("status") or "")
    if actual_status in {"completed", "failed"}:
        raise ApplyResumeError(
            f"cannot resume run in terminal status {actual_status!r}",
            code="resume_apply_blocked",
        )
    transition = resume_plan.state_transition
    if transition is None:
        if actual_status == "paused":
            raise ApplyResumeError(
                "paused resume requires state_transition on resume plan",
                code="resume_apply_blocked",
            )
    else:
        if actual_status != transition.from_status:
            raise ApplyResumeError(
                f"resume plan from_status {transition.from_status!r} does not match "
                f"actual status {actual_status!r}",
                code="resume_apply_blocked",
            )
        if transition.to_status != "running":
            raise ApplyResumeError(
                f"unsupported resume destination status {transition.to_status!r}",
                code="resume_apply_blocked",
            )
        if transition.from_status == "paused":
            if transition.prior_stop_code is None:
                raise ApplyResumeError(
                    "paused resume requires prior_stop_code on state_transition",
                    code="resume_apply_blocked",
                )
            prior_stop_record = run.get("stop")
            if not isinstance(prior_stop_record, dict):
                raise ApplyResumeError(
                    "resume plan requires prior stop on paused run",
                    code="resume_apply_blocked",
                )
            if str(prior_stop_record.get("code") or "") != transition.prior_stop_code:
                raise ApplyResumeError(
                    "resume plan prior_stop_code does not match actual stop",
                    code="resume_apply_blocked",
                )
        elif transition.prior_stop_code is not None:
            prior_stop_record = run.get("stop")
            if not isinstance(prior_stop_record, dict):
                raise ApplyResumeError(
                    "resume plan requires prior stop on paused run",
                    code="resume_apply_blocked",
                )
            if str(prior_stop_record.get("code") or "") != transition.prior_stop_code:
                raise ApplyResumeError(
                    "resume plan prior_stop_code does not match actual stop",
                    code="resume_apply_blocked",
                )

    prior_status = str(run.get("status") or "running")
    prior_stop = run.get("stop")
    prior_phase = str(run.get("phase") or "")
    digests = dict(run.get("digests") or {})
    old_execution_digest = str(digests.get("config_execution") or "")

    # Re-verify content-bound Sub-TDP auth at apply time (prepare/apply gap).
    try:
        from top_down_planning.orchestrator.prepare_resume import (
            verify_parent_sub_tdp_workspace_matches_accepted,
        )
        from top_down_planning.package.lineage import (
            verify_upstream_wrapper_matches_live_delivery,
        )

        from top_down_planning.package.loader import ExecutionPackageError

        kind = resolve_run_kind(run)
        if kind == RUN_KIND_PARENT_EXECUTION:
            production = store.load_production(run_id)
            verify_parent_sub_tdp_workspace_matches_accepted(
                store,
                production=production,
                workspace=run_workspace(run),
            )
        elif kind == RUN_KIND_SUB_TDP_EXECUTION:
            binding = run.get("package_binding") or {}
            if not isinstance(binding, dict):
                raise ValueError("child package_binding is missing at resume apply")
            from top_down_planning.package.execution_validation import (
                baseline_auth_params_from_binding,
                verify_merged_baseline_workspace_bytes,
            )
            from top_down_planning.package.lineage import (
                verify_baseline_wrapper_matches_current_package,
                verify_upstream_wrapper_matches_live_delivery,
            )

            package_id = str(binding.get("package_id") or "").strip()
            package_digest = str(binding.get("package_digest") or "").strip()
            if not package_id or not package_digest:
                raise ValueError(
                    "child package_binding missing package identity at resume apply"
                )
            initial_snapshot, unit_depends_on, resolved_config, package_units = (
                baseline_auth_params_from_binding(binding)
            )
            seen_digests: set[str] = set()
            for key in ("upstream_accepted_results",):
                for wrapper in binding.get(key) or []:
                    if not isinstance(wrapper, dict):
                        raise ValueError(
                            f"child {key} entry is invalid at resume apply"
                        )
                    digest = str(wrapper.get("accepted_result_digest") or "").strip()
                    if digest and digest in seen_digests:
                        continue
                    if digest:
                        seen_digests.add(digest)
                    verify_upstream_wrapper_matches_live_delivery(store, wrapper)
                    verify_baseline_wrapper_matches_current_package(
                        wrapper,
                        package_id=package_id,
                        package_digest=package_digest,
                        package_units=package_units,
                    )
            baseline_wrappers = binding.get("workspace_baseline_accepted_results") or []
            for wrapper in baseline_wrappers:
                if not isinstance(wrapper, dict):
                    raise ValueError(
                        "child workspace_baseline_accepted_results entry is invalid "
                        "at resume apply"
                    )
                digest = str(wrapper.get("accepted_result_digest") or "").strip()
                if digest and digest in seen_digests:
                    continue
                if digest:
                    seen_digests.add(digest)
                verify_upstream_wrapper_matches_live_delivery(store, wrapper)
                verify_baseline_wrapper_matches_current_package(
                    wrapper,
                    package_id=package_id,
                    package_digest=package_digest,
                    package_units=package_units,
                )
            if baseline_wrappers:
                verify_merged_baseline_workspace_bytes(
                    list(baseline_wrappers),
                    workspace=run_workspace(run),
                    initial_snapshot_digest=initial_snapshot,
                    resolved_config=resolved_config,
                    unit_depends_on=unit_depends_on,
                    production_overlay=store.load_production(run_id),
                )
    except (ValueError, ExecutionPackageError) as exc:
        raise ApplyResumeError(str(exc), code="resume_apply_blocked") from exc

    effective_config = resume_plan.effective_config or resolved_config
    production = store.load_production(run_id)
    workspace_path = Path(run_workspace(run))
    try:
        from top_down_planning.orchestrator.prepare_resume import (
            _extra_authorized_paths_for_resume,
        )

        extra_authorized = _extra_authorized_paths_for_resume(
            store,
            run=run,
            production=production,
            workspace=workspace_path,
        )
    except ValueError as exc:
        raise ApplyResumeError(str(exc), code="resume_apply_blocked") from exc
    context_error = validate_resume_context_bindings(
        run,
        production,
        effective_config,
        workspace=workspace_path,
        context_spec_may_change=resume_plan.context_spec_may_change,
        extra_authorized_paths=extra_authorized,
    )
    if context_error is not None:
        raise ApplyResumeError(context_error, code="resume_apply_blocked")

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
    run_payload.pop("pending_capability_revoke_phase", None)
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
            try:
                if resolve_run_kind(run) == RUN_KIND_SUB_TDP_EXECUTION:
                    plan = store.load_plan_model(run_id)
                    next_digests["output_goal"] = compute_unit_output_goal_digest(
                        plan.output_goal
                    )
            except ValueError:
                pass
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

    review_updates, review_expected = _review_updates_for_resume_apply(
        review_loop=review_loop,
    )
    spec = CommitSpec(
        run=run_payload,
        run_expected_revision=expected_revision,
        resolved_config=config_update.resolved_config,
        invocation=config_update.invocation,
        reviews=review_updates,
        review_expected_revisions=review_expected,
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
