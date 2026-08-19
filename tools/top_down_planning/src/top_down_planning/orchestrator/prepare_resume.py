"""Pure resume planning (proposal §9.2)."""

from __future__ import annotations

import copy
from typing import Any

from core_tools.config import resolve_workspace
from core_tools.persistence import PersistenceError

from top_down_planning.agent_tool.artifacts import verify_evidence_snapshot
from top_down_planning.config import (
    compute_input_digest,
    compute_output_goal_digest,
    compute_unit_output_goal_digest,
)
from top_down_planning.config.context_digests import (
    resolve_context_spec_may_change,
    validate_resume_context_bindings,
)
from top_down_planning.config.resume_policy import (
    apply_resume_config_drift_policy,
    has_mandatory_whole_plan_approval,
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
    SUB_TDPS,
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
from top_down_planning.persistence.snapshot import CanonicalRunSnapshot
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


def _blocker_from_verify_exc(exc: BaseException, message: str) -> str:
    """Translate semantic verify failures; let access errors propagate."""

    if isinstance(exc, (OSError, PersistenceError)):
        raise
    return message


def _raise_blocked(message: str, *, code: str = "resume_preparation_blocked") -> None:
    raise PrepareResumeBlockedError(message, code=code, blockers=(message,))


def _verify_production_evidence(
    store: RunStore,
    run_id: str,
    production: dict[str, Any],
) -> str | None:
    from top_down_planning.domain.production import (
        is_live_completed_batch,
        live_output_evidence_entries,
    )

    for entry in live_output_evidence_entries(production):
        try:
            verify_evidence_snapshot(store, run_id, entry)
        except Exception as exc:
            return _blocker_from_verify_exc(exc, f"evidence integrity failure: {exc}")
    for batch in production.get("batches") or []:
        if not isinstance(batch, dict):
            continue
        if not is_live_completed_batch(batch):
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
                return _blocker_from_verify_exc(exc, f"evidence integrity failure: {exc}")
    return None


def _verify_prepared_package_binding(
    store: RunStore,
    run: dict[str, Any],
) -> str | None:
    """Reload prepared package and verify binding digests for resume."""

    from pathlib import Path

    from top_down_planning.domain.run_kind import (
        RUN_KIND_PARENT_EXECUTION,
        RUN_KIND_SUB_TDP_EXECUTION,
        resolve_run_kind,
    )
    from top_down_planning.package.lineage import (
        validate_accepted_child_delivery,
        verify_accepted_result_attestation,
        verify_accepted_result_matches_live_delivery,
    )
    from top_down_planning.package.loader import ExecutionPackageError, ExecutionPackageLoader

    try:
        kind = resolve_run_kind(run)
    except ValueError:
        return None
    if kind not in {RUN_KIND_PARENT_EXECUTION, RUN_KIND_SUB_TDP_EXECUTION}:
        return None
    binding = run.get("package_binding") or {}
    if not isinstance(binding, dict):
        return "prepared run package_binding is missing"
    manifest_path = str(binding.get("manifest_path") or "").strip()
    if not manifest_path:
        return "prepared run missing package_binding.manifest_path"
    try:
        from top_down_planning.package.store_persist import assert_manifest_path_in_store

        assert_manifest_path_in_store(
            store.root,
            Path(manifest_path),
            package_id=str(binding.get("package_id") or "").strip() or None,
        )
    except Exception as exc:
        return _blocker_from_verify_exc(
            exc, f"prepared package manifest_path invalid: {exc}"
        )
    try:
        package = ExecutionPackageLoader().load_from_manifest(
            Path(manifest_path),
            verify_workspace=False,
        )
    except ExecutionPackageError as exc:
        return f"prepared package reload failed: {exc}"
    expected_digest = str(package.manifest.get("package_digest") or "")
    actual_digest = str(binding.get("package_digest") or "")
    if expected_digest != actual_digest:
        return (
            "prepared package_digest mismatch blocks resume: "
            f"expected {expected_digest}, got {actual_digest}"
        )
    run_id = str(run.get("id") or "").strip()
    try:
        actual_plan = store.load_plan_model(run_id)
    except (OSError, PersistenceError):
        raise
    except Exception as exc:
        return _blocker_from_verify_exc(exc, f"prepared plan reload failed: {exc}")
    if kind == RUN_KIND_SUB_TDP_EXECUTION:
        unit_id = str(
            binding.get("selected_unit_id") or binding.get("unit_id") or ""
        ).strip()
        unit = package.units.get(unit_id)
        if unit is None:
            return f"prepared unit {unit_id!r} missing from package"
        expected_plan_digest = compute_plan_digest(unit.plan)
        if compute_plan_digest(actual_plan) != expected_plan_digest:
            return "prepared persisted plan does not match package unit plan"
        if str(binding.get("unit_plan_digest") or "") != unit.plan_digest:
            return "prepared unit_plan_digest mismatch blocks resume"
        if str(binding.get("assigned_subtree_digest") or "") != unit.assigned_subtree_digest:
            return "prepared assigned_subtree_digest mismatch blocks resume"
        upstream_error = _verify_child_upstream_bindings(
            store,
            run_id=run_id,
            binding=binding,
            unit=unit,
            package=package,
        )
        if upstream_error:
            return upstream_error
    elif kind == RUN_KIND_PARENT_EXECUTION:
        expected_plan_digest = compute_plan_digest(package.parent_plan)
        if compute_plan_digest(actual_plan) != expected_plan_digest:
            return "prepared persisted plan does not match package parent plan"
        production = store.load_production(run_id)
        state = production.get("sub_tdps")
        if isinstance(state, dict):
            for unit_record in state.get("units") or []:
                if not isinstance(unit_record, dict):
                    continue
                status = str(unit_record.get("status") or "")
                if status == "completed" and not unit_record.get("accepted_result"):
                    return (
                        f"parent sub_tdps unit {unit_record.get('plan_item_id')!r} "
                        "completed without accepted_result"
                    )
                if not unit_record.get("accepted_result"):
                    continue
                try:
                    verify_accepted_result_attestation(unit_record)
                except ValueError as exc:
                    return f"parent sub_tdps attestation invalid: {exc}"
                accepted = unit_record.get("accepted_result")
                if not isinstance(accepted, dict):
                    return (
                        f"parent sub_tdps unit {unit_record.get('plan_item_id')!r} "
                        "accepted_result missing"
                    )
                child_run_id = str(accepted.get("child_run_id") or "").strip()
                if not child_run_id:
                    return (
                        f"parent sub_tdps unit {unit_record.get('plan_item_id')!r} "
                        "accepted_result missing child_run_id"
                    )
                try:
                    child_run = store.load_run(child_run_id)
                    child_production = store.load_production(child_run_id)
                    validate_accepted_child_delivery(
                        store=store,
                        child_run_id=child_run_id,
                        child_run=child_run,
                        child_production=child_production,
                        verify_evidence=True,
                    )
                    verify_accepted_result_matches_live_delivery(
                        unit_record,
                        child_run=child_run,
                        child_production=child_production,
                    )
                except (ValueError, KeyError) as exc:
                    return (
                        f"parent sub_tdps child delivery invalid for "
                        f"{unit_record.get('plan_item_id')!r}: {exc}"
                    )
            try:
                from top_down_planning.persistence.sub_tdp_state import (
                    ensure_sub_tdp_state_matches_units,
                    validate_sub_tdp_state_matches_package,
                )
                from top_down_planning.domain.sub_tdp_units import SubTdpUnit

                units = [
                    SubTdpUnit(
                        plan_item_id=u.unit_id,
                        title=u.title,
                        outcome="",
                        directory=u.plan_file.parent.name,
                        ordinal=u.ordinal,
                    )
                    for u in sorted(package.units.values(), key=lambda item: item.ordinal)
                ]
                ensure_sub_tdp_state_matches_units(
                    state,
                    units,
                )
                validate_sub_tdp_state_matches_package(state, package)
            except (ValueError, TypeError, KeyError) as exc:
                return f"parent sub_tdps orchestration mismatch: {exc}"
    return None


def _verify_child_upstream_bindings(
    store: RunStore,
    *,
    run_id: str,
    binding: dict[str, Any],
    unit,
    package,
) -> str | None:
    from top_down_planning.package.lineage import (
        validate_accepted_child_delivery,
        validate_child_package_bindings,
        verify_accepted_result_matches_live_delivery,
        verify_baseline_wrapper_matches_current_package,
        verify_upstream_accepted_result_binding,
        verify_upstream_wrapper_matches_live_delivery,
    )
    from top_down_planning.package.loader import ExecutionPackageError

    binding_error = validate_child_package_bindings(binding)
    if binding_error:
        return binding_error

    expected_deps = list(unit.depends_on)
    wrappers = binding["upstream_accepted_results"]
    if len(wrappers) != len(expected_deps):
        return (
            "prepared upstream_accepted_results count does not match unit dependencies"
        )

    package_id = str(package.manifest.get("package_id") or "").strip()
    package_digest = str(package.manifest.get("package_digest") or "").strip()

    seen: set[str] = set()
    upstream_digests: set[str] = set()
    for wrapper in wrappers:
        if not isinstance(wrapper, dict):
            return "prepared upstream_accepted_results entry is invalid"
        try:
            verify_upstream_accepted_result_binding(wrapper)
            verify_baseline_wrapper_matches_current_package(
                wrapper,
                package_id=package_id,
                package_digest=package_digest,
                package_units=package.units,
            )
        except ValueError as exc:
            return f"prepared upstream attestation invalid: {exc}"
        accepted = wrapper.get("accepted_result") or {}
        dep_id = str(accepted.get("unit_id") or "").strip()
        if dep_id not in expected_deps:
            return f"prepared upstream wrapper references unexpected unit {dep_id!r}"
        if dep_id in seen:
            return f"duplicate prepared upstream wrapper for {dep_id!r}"
        seen.add(dep_id)
        upstream_digests.add(str(wrapper.get("accepted_result_digest") or "").strip())
        dep_unit = package.units.get(dep_id)
        if dep_unit is None:
            return f"prepared upstream dependency unit {dep_id!r} missing from package"
        contract = str(wrapper.get("upstream_contract_digest") or "").strip()
        if contract != dep_unit.assigned_subtree_digest:
            return (
                f"prepared upstream_contract_digest mismatch for dependency {dep_id!r}"
            )
        child_run_id = str(accepted.get("child_run_id") or "").strip()
        if not child_run_id:
            return (
                f"prepared upstream wrapper for {dep_id!r} missing child_run_id"
            )
        try:
            child_run = store.load_run(child_run_id)
            child_production = store.load_production(child_run_id)
            validate_accepted_child_delivery(
                store=store,
                child_run_id=child_run_id,
                child_run=child_run,
                child_production=child_production,
                verify_evidence=True,
            )
            verify_accepted_result_matches_live_delivery(
                {
                    "plan_item_id": dep_id,
                    "child_run_id": child_run_id,
                    "unit_plan_digest": str(accepted.get("unit_plan_digest") or ""),
                    "accepted_result": accepted,
                    "accepted_result_digest": str(
                        wrapper.get("accepted_result_digest") or ""
                    ),
                },
                child_run=child_run,
                child_production=child_production,
            )
        except (ValueError, KeyError) as exc:
            return f"prepared upstream child delivery invalid for {dep_id!r}: {exc}"
    if seen != set(expected_deps):
        missing = sorted(set(expected_deps) - seen)
        return f"prepared upstream_accepted_results missing dependencies: {', '.join(missing)}"

    expected_external = list(unit.external_prerequisites)
    actual_external = binding.get("external_prerequisites")
    if actual_external != expected_external:
        return (
            "prepared external_prerequisites do not match package unit contract"
        )

    baseline_wrappers = binding["workspace_baseline_accepted_results"]
    baseline_digests: set[str] = set()
    for wrapper in baseline_wrappers:
        if not isinstance(wrapper, dict):
            return "prepared workspace_baseline_accepted_results entry is invalid"
        try:
            verify_upstream_wrapper_matches_live_delivery(store, wrapper)
            verify_baseline_wrapper_matches_current_package(
                wrapper,
                package_id=package_id,
                package_digest=package_digest,
                package_units=package.units,
            )
        except (ValueError, KeyError) as exc:
            return f"prepared workspace baseline attestation invalid: {exc}"
        digest = str(wrapper.get("accepted_result_digest") or "").strip()
        if not digest:
            return "prepared workspace baseline wrapper missing accepted_result_digest"
        baseline_digests.add(digest)
    if baseline_wrappers:
        from top_down_planning.package.execution_validation import (
            verify_merged_baseline_workspace_bytes,
        )

        expected_snapshot = str(
            (package.manifest.get("context") or {}).get("context_snapshot_digest") or ""
        )
        production_overlay = store.load_production(run_id)
        try:
            verify_merged_baseline_workspace_bytes(
                baseline_wrappers,
                workspace=package.workspace_path,
                initial_snapshot_digest=expected_snapshot,
                resolved_config=package.resolved_config,
                unit_depends_on={
                    unit_id: list(unit.depends_on)
                    for unit_id, unit in package.units.items()
                },
                production_overlay=production_overlay,
            )
        except ExecutionPackageError as exc:
            return f"prepared workspace baseline bytes invalid: {exc}"
    missing_in_baseline = sorted(
        d for d in upstream_digests if d and d not in baseline_digests
    )
    if missing_in_baseline:
        return (
            "prepared workspace_baseline_accepted_results missing upstream digests: "
            + ", ".join(missing_in_baseline)
        )
    return None


def _parent_package_auth_from_production(
    production: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Load package initial snapshot digest and resolved config from sub_tdps state."""

    from top_down_planning.package.execution_validation import baseline_auth_params_from_binding
    from top_down_planning.package.loader import ExecutionPackageError

    state = production.get("sub_tdps")
    if not isinstance(state, dict):
        raise ValueError("parent sub_tdps state is missing")
    manifest_path = str(state.get("manifest_path") or "").strip()
    if not manifest_path:
        raise ValueError(
            "parent sub_tdps missing manifest_path required for workspace succession"
        )
    try:
        initial_snapshot, _, resolved_config, _ = baseline_auth_params_from_binding(
            {"manifest_path": manifest_path}
        )
    except ExecutionPackageError as exc:
        raise ValueError(str(exc)) from exc
    return initial_snapshot, resolved_config


def _topo_sort_sub_tdp_unit_records(
    unit_records: list[dict[str, Any]],
    *,
    initial_snapshot_digest: str,
) -> list[dict[str, Any]]:
    """Return unit records in workspace-succession order."""

    from top_down_planning.package.execution_validation import order_workspace_succession_items

    indexed_records = [
        record
        for record in unit_records
        if isinstance(record, dict)
        and str(record.get("plan_item_id") or "").strip()
        and isinstance(record.get("accepted_result"), dict)
    ]
    if not str(initial_snapshot_digest or "").strip():
        raise ValueError(
            "package initial context_snapshot_digest is required for sub_tdp ordering"
        )
    return order_workspace_succession_items(
        indexed_records,
        item_id=lambda record: str(record.get("plan_item_id") or "").strip(),
        depends_on_ids=lambda record: [
            str(dep).strip()
            for dep in (record.get("depends_on") or [])
            if isinstance(record.get("depends_on"), list)
        ],
        accepted_result=lambda record: record["accepted_result"],
        initial_snapshot_digest=initial_snapshot_digest,
        item_digest=lambda record: str(record.get("accepted_result_digest") or "").strip(),
    )


def collect_parent_sub_tdp_authorized_workspace_changes(
    store: RunStore,
    *,
    production: dict[str, Any],
    workspace: Any,
) -> dict[str, dict[str, Any]]:
    """Merge content-bound workspace_changes from attached accepted Sub-TDP units.

    Validates attestation and live child delivery for every completed unit with an
    accepted_result, then merges workspace_changes in dependency order. Ordering
    roots at the prepared package initial context snapshot and supports composite
    multi-result baseline joins via merged workspace lineage.
    """

    from top_down_planning.package.execution_validation import (
        merge_accepted_result_workspace_changes,
        merge_parent_integration_workspace_evidence,
    )
    from top_down_planning.package.lineage import (
        validate_accepted_child_delivery,
        verify_accepted_result_matches_live_delivery,
    )
    from top_down_planning.package.loader import ExecutionPackageError

    state = production.get("sub_tdps")
    if not isinstance(state, dict):
        return {}
    unit_records = [
        record
        for record in (state.get("units") or [])
        if isinstance(record, dict) and isinstance(record.get("accepted_result"), dict)
    ]
    if not unit_records:
        return {}
    authorized_changes: dict[str, dict[str, Any]] = {}
    package_initial_snapshot, _ = _parent_package_auth_from_production(production)
    cumulative_snapshot = package_initial_snapshot
    path_writers: dict[str, str] = {}
    for unit_record in _topo_sort_sub_tdp_unit_records(
        unit_records,
        initial_snapshot_digest=package_initial_snapshot,
    ):
        accepted = unit_record["accepted_result"]
        plan_item_id = str(unit_record.get("plan_item_id") or "").strip() or "<unknown>"
        child_run_id = str(accepted.get("child_run_id") or "").strip()
        if not child_run_id:
            raise ValueError(
                f"parent sub_tdps unit {plan_item_id!r} accepted_result missing child_run_id"
            )
        try:
            child_run = store.load_run(child_run_id)
            child_production = store.load_production(child_run_id)
            validate_accepted_child_delivery(
                store=store,
                child_run_id=child_run_id,
                child_run=child_run,
                child_production=child_production,
                verify_evidence=True,
            )
            live_accepted = verify_accepted_result_matches_live_delivery(
                unit_record,
                child_run=child_run,
                child_production=child_production,
            )
        except (ValueError, KeyError) as exc:
            raise ValueError(
                f"parent sub_tdps child delivery invalid for {plan_item_id!r}: {exc}"
            ) from exc
        try:
            digest = str(unit_record.get("accepted_result_digest") or "").strip()
            authorized_changes, cumulative_snapshot = merge_accepted_result_workspace_changes(
                authorized_changes,
                live_accepted,
                cumulative_snapshot_digest=cumulative_snapshot,
                workspace=workspace,
                path_writers=path_writers,
                accepted_result_digest=digest,
            )
        except (ExecutionPackageError, ValueError, TypeError) as exc:
            raise ValueError(
                f"parent sub_tdps workspace_changes invalid for {plan_item_id!r}: {exc}"
            ) from exc
    authorized_changes = merge_parent_integration_workspace_evidence(
        authorized_changes,
        production,
        workspace=workspace,
    )
    return authorized_changes


def verify_parent_sub_tdp_workspace_matches_accepted(
    store: RunStore,
    *,
    production: dict[str, Any],
    workspace: Any,
) -> set[str]:
    """Fail closed unless live workspace bytes match attached accepted changes."""

    from top_down_planning.package.execution_validation import (
        verify_workspace_matches_authorized_changes,
    )

    authorized_changes = collect_parent_sub_tdp_authorized_workspace_changes(
        store,
        production=production,
        workspace=workspace,
    )
    if authorized_changes:
        verify_workspace_matches_authorized_changes(
            sorted(authorized_changes),
            authorized_changes=authorized_changes,
            workspace=workspace,
        )
    return set(authorized_changes)


def _extra_authorized_paths_for_resume(
    store: RunStore,
    *,
    run: dict[str, Any],
    production: dict[str, Any],
    workspace: Any,
) -> set[str] | None:
    """Authorize parent resume drift from attached accepted-result workspace_changes.

    Paths are authorized only when current workspace bytes match the accepted
    sha256 (content-bound), not merely because the pathname was previously emitted.
    """

    from top_down_planning.domain.run_kind import (
        RUN_KIND_PARENT_EXECUTION,
        resolve_run_kind,
    )

    try:
        kind = resolve_run_kind(run)
    except ValueError:
        return None
    if kind != RUN_KIND_PARENT_EXECUTION:
        return None
    authorized = verify_parent_sub_tdp_workspace_matches_accepted(
        store,
        production=production,
        workspace=workspace,
    )
    return authorized or None


_APPROVAL_REQUIRED_PHASES = frozenset(
    {
        PLAN_VALIDATED,
        PRODUCTION,
        SUB_TDPS,
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
    *,
    allow_config_drift: bool = False,
    run: dict[str, Any] | None = None,
    snapshot: CanonicalRunSnapshot | None = None,
) -> ResumePlan:
    """Build a read-only resume plan or raise when canonical invariants block resume."""

    if snapshot is not None:
        run = snapshot.run
        stored_config = snapshot.resolved_config
        plan = snapshot.plan
        production = snapshot.production
        reviews = snapshot.reviews
    else:
        if run is None:
            run = store.load_run(run_id)
        stored_config = store.load_resolved_config(run_id)
        plan = store.load_plan(run_id)
        production = store.load_production(run_id)
        reviews = store.list_reviews(run_id)
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
            session_policy=derive_session_policy(run, reviews),
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

    workspace = run_workspace(run)
    plan_revision = int(plan.get("revision") or 0)
    has_whole_plan_approval = has_mandatory_whole_plan_approval(reviews, plan_revision)
    resolved_consumed_limits = consumed_limits or consumed_limits_from_run(run)

    drift = apply_resume_config_drift_policy(
        stored_config,
        candidate_config,
        allow_config_drift=allow_config_drift,
        has_whole_plan_approval=has_whole_plan_approval,
        consumed_limits=resolved_consumed_limits,
    )
    effective_config = drift.effective_config

    blockers: list[str] = []

    stored_ws = resolve_workspace(stored_config, cwd=workspace)
    candidate_ws = resolve_workspace(candidate_config, cwd=workspace)
    if stored_ws.resolve() != candidate_ws.resolve():
        blockers.append("workspace change blocked during resume")

    digest_config = effective_config if allow_config_drift else candidate_config
    drift_hint = (
        " (pass --allow-config-drift to opt in)"
        if not allow_config_drift
        else ""
    )
    if not allow_config_drift or has_whole_plan_approval:
        input_digest = compute_input_digest(digest_config, base_dir=workspace)
        if input_digest != run_digests.get("input"):
            blockers.append(f"input digest mismatch blocks resume{drift_hint}")

        output_goal_digest = compute_output_goal_digest(digest_config, base_dir=workspace)
        try:
            from top_down_planning.domain.run_kind import (
                RUN_KIND_SUB_TDP_EXECUTION,
                resolve_run_kind,
            )

            kind = resolve_run_kind(run)
            if kind == RUN_KIND_SUB_TDP_EXECUTION:
                from top_down_planning.domain.models import Plan

                unit_plan = Plan.from_dict(plan)
                output_goal_digest = compute_unit_output_goal_digest(
                    unit_plan.output_goal
                )
        except ValueError as exc:
            blockers.append(f"run_kind invalid blocks resume: {exc}")
        if output_goal_digest != run_digests.get("output_goal"):
            blockers.append(f"output-goal digest mismatch blocks resume{drift_hint}")

        contract_digest = compute_config_contract_digest(digest_config)
        contract_digest_valid = contract_digest == run_digests.get("config_contract")
        if not contract_digest_valid:
            blockers.append(f"config_contract digest mismatch blocks resume{drift_hint}")
    else:
        contract_digest = compute_config_contract_digest(effective_config)
        contract_digest_valid = (
            contract_digest == run_digests.get("config_contract")
            or (allow_config_drift and drift.contract_digest_changed)
        )

    blockers.extend(drift.errors)

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

    context_spec_may_change = resolve_context_spec_may_change(
        run_digests=run_digests,
        stored_config=stored_config,
        candidate_config=effective_config,
        workspace=workspace,
        allow_config_drift=allow_config_drift,
        has_whole_plan_approval=has_whole_plan_approval,
    )

    try:
        extra_authorized_paths = _extra_authorized_paths_for_resume(
            store,
            run=run,
            production=production,
            workspace=workspace,
        )
    except ValueError as exc:
        blockers.append(str(exc))
        extra_authorized_paths = None

    context_error = validate_resume_context_bindings(
        run,
        production,
        effective_config,
        workspace=workspace,
        context_spec_may_change=context_spec_may_change,
        extra_authorized_paths=extra_authorized_paths,
    )
    context_binding_valid = context_error is None
    if context_error is not None:
        if context_error == "context_spec digest mismatch blocks resume":
            if not allow_config_drift:
                context_error += " (pass --allow-config-drift to opt in for model-only changes)"
            elif not context_spec_may_change:
                context_error += (
                    " (non-model context_spec fields cannot drift on resume)"
                )
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

    package_error = _verify_prepared_package_binding(store, run)
    if package_error is not None:
        blockers.append(package_error)

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

    config_changes = dict(drift.applied_changes)

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
        effective_config=copy.deepcopy(effective_config),
        ignored_config_changes=dict(drift.ignored_changes),
        warnings=drift.warnings,
        allow_config_drift=allow_config_drift,
        contract_digest_may_change=allow_config_drift and drift.contract_digest_changed,
        context_spec_may_change=context_spec_may_change,
    )
