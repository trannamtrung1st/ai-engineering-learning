"""Parent execution orchestration for prepared Sub-TDP packages."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from core_tools.provider import Provider

from top_down_planning.config.context_digests import (
    recompute_context_snapshot_binding_with_diagnostics,
    short_path_for_observability,
    validate_production_snapshot_rebase,
)
from top_down_planning.domain.models import Plan
from top_down_planning.domain.reviews import find_whole_plan_approval
from top_down_planning.domain.run_kind import RUN_KIND_PARENT_EXECUTION, resolve_run_kind
from top_down_planning.domain.run_lifecycle import StopRecord
from top_down_planning.domain.production import completion_claim_asserts_goal_met
from top_down_planning.domain.sub_tdp_synthesis import (
    child_run_summary,
    synthesize_parent_production,
)
from top_down_planning.domain.sub_tdp_units import SubTdpUnit
from top_down_planning.orchestrator.errors import ProviderRunError
from top_down_planning.orchestrator.evidence_promotion import (
    promote_child_evidence_to_parent,
)
from top_down_planning.orchestrator.execution_runtime import build_execution_runtime
from top_down_planning.orchestrator.prepared_unit_executor import (
    PreparedUnitExecutor,
)
from top_down_planning.orchestrator.resume import short_digest_for_observability
from top_down_planning.orchestrator.phases import (
    PLAN_VALIDATED,
    PRODUCTION,
    SUB_TDPS,
    WHOLE_OUTPUT_REVIEW,
)
from top_down_planning.orchestrator.run_transitions import pause_run
from top_down_planning.orchestrator.sub_tdp_child_driver import (
    PreparedChildResult,
    ProviderFactory,
)
from top_down_planning.package.lineage import (
    accepted_result_digest,
    accepted_result_record,
)
from top_down_planning.package.loader import ExecutionPackageLoader
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.digests import compute_output_digest
from top_down_planning.persistence.interface import RunStore
from top_down_planning.persistence.sub_tdp_state import (
    ORCHESTRATION_STATUS_COMPLETED,
    ORCHESTRATION_STATUS_FAILED,
    ORCHESTRATION_STATUS_PREPARING,
    ORCHESTRATION_STATUS_RUNNING,
    UNIT_STATUS_COMPLETED,
    UNIT_STATUS_FAILED,
    UNIT_STATUS_PAUSED,
    UNIT_STATUS_PENDING,
    UNIT_STATUS_RUNNING,
    all_units_completed,
    ensure_sub_tdp_state_matches_units,
    initial_sub_tdp_state_from_package,
    load_sub_tdp_state,
    merge_sub_tdp_state_into_production,
    next_ready_unit_id,
    unit_status_from_child_run,
    find_unit,
)
from top_down_planning.workspace import run_workspace


@dataclass(frozen=True)
class SubTdpsPhaseResult:
    ok: bool
    phase: str
    status: str
    outcome: str | None
    units_completed: int
    reason: str | None = None


class SubTdpsPhaseOrchestrator:
    """Drive sequential prepared unit runs and synthesize parent production."""

    def __init__(
        self,
        store: RunStore,
        run_id: str,
        provider: Provider,
        *,
        create_provider: ProviderFactory | None = None,
        observability: Any | None = None,
    ) -> None:
        self._store = store
        self._run_id = run_id
        self._provider = provider
        self._create_provider = create_provider
        self._observability = observability

    def run(self) -> SubTdpsPhaseResult:
        run = self._store.load_run(self._run_id)
        if resolve_run_kind(run) != RUN_KIND_PARENT_EXECUTION:
            raise ProviderRunError(
                "sub_tdps phase requires a parent_execution run created from tdp execute"
            )

        phase = str(run.get("phase") or "")
        if phase == WHOLE_OUTPUT_REVIEW:
            return self._result_from_run(run, ok=True, units_completed=0)
        if phase == PLAN_VALIDATED:
            self._require_plan_approval()
            run = self._enter_sub_tdps_phase()
            phase = SUB_TDPS
        elif phase != SUB_TDPS:
            raise ProviderRunError(f"run is not ready for sub_tdps phase: {phase}")

        config = self._store.load_resolved_config(self._run_id)
        package = self._load_execution_package()
        if package is None:
            raise ProviderRunError(
                "parent execution requires a prepared execution package binding"
            )

        self._require_plan_approval()
        plan = self._store.load_plan_model(self._run_id)
        workspace = run_workspace(run)
        # Manifest units are authoritative for execution; plan re-derivation is only
        # used to build SubTdpUnit display records for state helpers.
        units = [
            SubTdpUnit(
                plan_item_id=loaded.unit_id,
                title=loaded.title,
                outcome="",
                directory=loaded.plan_file.parent.name,
                ordinal=loaded.ordinal,
            )
            for loaded in sorted(package.units.values(), key=lambda item: item.ordinal)
        ]
        production = self._store.load_production(self._run_id)
        state = load_sub_tdp_state(production)
        if state is None:
            state = self._initialize_orchestration_state(package, units, production)
            production = self._store.load_production(self._run_id)
        else:
            try:
                ensure_sub_tdp_state_matches_units(state, units)
                self._ensure_state_matches_package(state, package)
            except ValueError as exc:
                raise ProviderRunError(str(exc)) from exc

        units_completed = sum(
            1
            for unit in state.get("units") or []
            if isinstance(unit, dict) and unit.get("status") == UNIT_STATUS_COMPLETED
        )

        if state.get("status") == ORCHESTRATION_STATUS_COMPLETED and production.get(
            "completion_claim"
        ):
            claim = production.get("completion_claim")
            if completion_claim_asserts_goal_met(
                claim if isinstance(claim, dict) else None
            ):
                return self._transition_to_whole_output_review()
            return self._transition_to_integration_production()

        state["status"] = ORCHESTRATION_STATUS_RUNNING
        self._commit_production_state(production, state)

        create_provider = self._resolve_create_provider(config, workspace)
        units_by_id = {unit.plan_item_id: unit for unit in units}
        child_store = FileRunStore(self._store.root)

        while not all_units_completed(state, units):
            for unit_record in state.get("units") or []:
                if not isinstance(unit_record, dict):
                    continue
                if str(unit_record.get("status") or "") == UNIT_STATUS_FAILED:
                    plan_item_id = str(unit_record.get("plan_item_id") or "")
                    return self._result_from_run(
                        self._store.load_run(self._run_id),
                        ok=False,
                        units_completed=units_completed,
                        reason=f"sub-tdp unit {plan_item_id} previously failed",
                    )

            plan_item_id = next_ready_unit_id(state, package.units)
            if plan_item_id is None:
                paused_unit = str(state.get("active_unit_id") or "").strip()
                if paused_unit:
                    return self._result_from_run(
                        self._store.load_run(self._run_id),
                        ok=False,
                        units_completed=units_completed,
                        reason=f"child Sub-TDP paused for unit {paused_unit}",
                    )
                raise ProviderRunError(
                    "sub_tdps orchestration blocked: no dependency-ready units remain"
                )

            unit = units_by_id.get(plan_item_id)
            unit_record = find_unit(state, plan_item_id)
            if unit is None or unit_record is None:
                raise ProviderRunError(f"unknown sub-tdp unit: {plan_item_id!r}")

            state["active_unit_id"] = plan_item_id
            # Create or resume the child before marking the unit running so a
            # crash cannot leave status=running with a null child_run_id.
            try:
                child_run_id = PreparedUnitExecutor().create_or_load_child_run(
                    child_store,
                    package,
                    plan_item_id,
                    resolved_config=config,
                    invocation=dict(self._store.load_run(self._run_id).get("invocation") or {})
                    or {"command": "execute", "observability": {}},
                    existing_child_run_id=str(unit_record.get("child_run_id") or "").strip()
                    or None,
                    parent_run_id=self._run_id,
                    orchestration_state=state,
                )
            except PreparedUnitExecutor.DependencyUnmetError as exc:
                unit_record["status"] = UNIT_STATUS_PENDING
                state["active_unit_id"] = None
                production = self._store.load_production(self._run_id)
                self._commit_production_state(production, state)
                stop = StopRecord(
                    code=exc.stop_code,
                    category="operational",
                    phase=SUB_TDPS,
                    message=str(exc),
                )
                pause_run(
                    self._store,
                    self._run_id,
                    stop=stop,
                    revoke_phase=SUB_TDPS,
                    event_type="sub_tdp_child_blocked",
                    plan_item_id=plan_item_id,
                    unit_id=plan_item_id,
                    dependency_id=exc.dependency_id,
                )
                return self._result_from_run(
                    self._store.load_run(self._run_id),
                    ok=False,
                    units_completed=units_completed,
                    reason=str(exc),
                )

            unit_record["status"] = UNIT_STATUS_RUNNING
            was_existing = bool(str(unit_record.get("child_run_id") or "").strip())
            unit_record["child_run_id"] = child_run_id
            production = self._store.load_production(self._run_id)
            self._commit_production_state(production, state)

            try:
                child_result = self._drive_prepared_unit(
                    unit,
                    unit_record,
                    create_provider,
                    workspace,
                    config,
                    package,
                    child_store,
                    orchestration_state=state,
                    child_run_id=child_run_id,
                    was_existing=was_existing,
                )
            except PreparedUnitExecutor.DependencyUnmetError as exc:
                unit_record["status"] = UNIT_STATUS_PENDING
                state["active_unit_id"] = None
                production = self._store.load_production(self._run_id)
                self._commit_production_state(production, state)
                stop = StopRecord(
                    code=exc.stop_code,
                    category="operational",
                    phase=SUB_TDPS,
                    message=str(exc),
                )
                pause_run(
                    self._store,
                    self._run_id,
                    stop=stop,
                    revoke_phase=SUB_TDPS,
                    event_type="sub_tdp_child_blocked",
                    plan_item_id=plan_item_id,
                    unit_id=plan_item_id,
                    dependency_id=exc.dependency_id,
                )
                return self._result_from_run(
                    self._store.load_run(self._run_id),
                    ok=False,
                    units_completed=units_completed,
                    reason=str(exc),
                )

            child_run = child_result.run
            if child_result.cancelled:
                unit_record["status"] = UNIT_STATUS_PAUSED
                unit_record["child_run_id"] = child_run.get("id")
                state["active_unit_id"] = plan_item_id
                production = self._store.load_production(self._run_id)
                self._commit_production_state(production, state)
                stop = StopRecord(
                    code="user_cancelled",
                    category="operational",
                    phase=SUB_TDPS,
                    message=(
                        child_result.reason
                        or f"child Sub-TDP cancelled for unit {plan_item_id}"
                    ),
                    details={"child_run_id": child_run.get("id"), "unit_id": plan_item_id},
                )
                pause_run(
                    self._store,
                    self._run_id,
                    stop=stop,
                    revoke_phase=SUB_TDPS,
                    event_type="run_paused",
                    plan_item_id=plan_item_id,
                    child_run_id=child_run.get("id"),
                    unit_id=plan_item_id,
                )
                return self._result_from_run(
                    self._store.load_run(self._run_id),
                    ok=False,
                    units_completed=units_completed,
                    reason=stop.message,
                )

            mapped_status = unit_status_from_child_run(child_run)
            if (
                mapped_status == UNIT_STATUS_FAILED
                or (
                    str(child_run.get("phase") or "") == "output_validated"
                    and str(child_run.get("outcome") or "") != "accepted"
                )
            ):
                mapped_status = UNIT_STATUS_FAILED
            unit_record["status"] = mapped_status
            unit_record["child_run_id"] = child_run.get("id")
            child_production = child_store.load_production(str(child_run.get("id")))
            unit_record["summary"] = child_run_summary(child_production, child_run)
            if mapped_status == UNIT_STATUS_COMPLETED:
                loaded_unit = package.units[plan_item_id]
                accepted = accepted_result_record(
                    child_run=child_run,
                    child_production=child_production,
                    unit_id=plan_item_id,
                    unit_plan_digest=loaded_unit.plan_digest,
                    package_id=str(package.manifest.get("package_id") or ""),
                    package_digest=str(package.manifest.get("package_digest") or ""),
                    assigned_subtree_digest=loaded_unit.assigned_subtree_digest,
                )
                unit_record["accepted_result"] = accepted
                unit_record["accepted_result_digest"] = accepted_result_digest(accepted)
                from top_down_planning.package.lineage import (
                    verify_accepted_result_attestation,
                )

                verify_accepted_result_attestation(unit_record)

            if mapped_status == UNIT_STATUS_PAUSED:
                state["active_unit_id"] = plan_item_id
                production = self._store.load_production(self._run_id)
                self._commit_production_state(production, state)
                return self._result_from_run(
                    self._store.load_run(self._run_id),
                    ok=False,
                    units_completed=units_completed,
                    reason=f"child Sub-TDP paused for unit {plan_item_id}",
                )

            if mapped_status == UNIT_STATUS_FAILED:
                state["status"] = ORCHESTRATION_STATUS_FAILED
                state["active_unit_id"] = plan_item_id
                production = self._store.load_production(self._run_id)
                self._commit_production_state(production, state)
                stop = StopRecord(
                    code="sub_tdp_child_failed",
                    category="operational",
                    phase=SUB_TDPS,
                    message=(
                        child_result.reason
                        or f"child Sub-TDP failed for unit {plan_item_id}"
                    ),
                )
                pause_run(
                    self._store,
                    self._run_id,
                    stop=stop,
                    revoke_phase=SUB_TDPS,
                    event_type="run_paused",
                    plan_item_id=plan_item_id,
                    child_run_id=child_run.get("id"),
                )
                return self._result_from_run(
                    self._store.load_run(self._run_id),
                    ok=False,
                    units_completed=units_completed,
                    reason=stop.message,
                )

            if mapped_status != UNIT_STATUS_COMPLETED:
                raise ProviderRunError(
                    f"child Sub-TDP for unit {plan_item_id} ended in non-terminal "
                    f"state: {mapped_status!r}"
                )

            units_completed += 1
            state["active_unit_id"] = None
            production = self._store.load_production(self._run_id)
            self._commit_production_state(production, state)

        production = self._store.load_production(self._run_id)
        state = load_sub_tdp_state(production) or state
        return self._synthesize_and_transition(plan, production, state, units, child_store)

    def _ensure_state_matches_package(self, state: dict[str, Any], package) -> None:
        expected_package_id = str(package.manifest.get("package_id") or "")
        expected_digest = str(package.manifest.get("package_digest") or "")
        actual_package_id = str(state.get("package_id") or "").strip()
        actual_digest = str(state.get("package_digest") or "").strip()
        if not expected_package_id:
            raise ValueError("execution package missing package_id")
        if not expected_digest:
            raise ValueError("execution package missing package_digest")
        if not actual_package_id:
            raise ValueError("sub_tdps state missing required package_id")
        if actual_package_id != expected_package_id:
            raise ValueError(
                f"sub_tdps state package_id mismatch: {actual_package_id} != {expected_package_id}"
            )
        if not actual_digest:
            raise ValueError("sub_tdps state missing required package_digest")
        if actual_digest != expected_digest:
            raise ValueError(
                "sub_tdps state package_digest mismatch with loaded execution package"
            )
        for loaded in package.units.values():
            record = find_unit(state, loaded.unit_id)
            if record is None:
                raise ValueError(f"sub_tdps state missing unit {loaded.unit_id!r}")
            record_ordinal = record.get("ordinal")
            if record_ordinal is not None and int(record_ordinal) != int(loaded.ordinal):
                raise ValueError(
                    f"sub_tdps state ordinal mismatch for unit {loaded.unit_id!r}"
                )
            unit_plan_digest = str(record.get("unit_plan_digest") or "").strip()
            if not unit_plan_digest:
                raise ValueError(
                    f"sub_tdps state missing unit_plan_digest for unit {loaded.unit_id!r}"
                )
            if unit_plan_digest != loaded.plan_digest:
                raise ValueError(
                    f"sub_tdps state unit_plan_digest mismatch for unit {loaded.unit_id!r}"
                )
            subtree_digest = str(record.get("assigned_subtree_digest") or "").strip()
            if not subtree_digest:
                raise ValueError(
                    f"sub_tdps state missing assigned_subtree_digest for unit "
                    f"{loaded.unit_id!r}"
                )
            if subtree_digest != loaded.assigned_subtree_digest:
                raise ValueError(
                    f"sub_tdps state assigned_subtree_digest mismatch for unit "
                    f"{loaded.unit_id!r}"
                )
            deps = record.get("depends_on")
            if not isinstance(deps, list):
                raise ValueError(
                    f"sub_tdps state missing depends_on for unit {loaded.unit_id!r}"
                )
            if list(deps) != list(loaded.depends_on):
                raise ValueError(
                    f"sub_tdps state depends_on mismatch for unit {loaded.unit_id!r}"
                )

    def _resolve_create_provider(
        self,
        config: dict[str, Any],
        workspace: Path,
    ) -> ProviderFactory:
        if self._create_provider is not None:
            return self._create_provider
        provider = self._provider

        def _factory(child_config: dict[str, Any], child_workspace: Path) -> Provider:
            return provider

        return _factory

    def _initialize_orchestration_state(
        self,
        package,
        units: list[SubTdpUnit],
        production: dict[str, Any],
    ) -> dict[str, Any]:
        state = initial_sub_tdp_state_from_package(
            package.manifest,
            manifest_path=str(
                (self._store.load_run(self._run_id).get("package_binding") or {}).get(
                    "manifest_path"
                )
                or package.manifest_path
            ),
            units=units,
            package_units=package.units,
        )
        state["status"] = ORCHESTRATION_STATUS_PREPARING
        self._commit_production_state(production, state)
        self._append_event(
            "sub_tdps_prepared",
            unit_count=len(units),
            package_id=package.manifest.get("package_id"),
        )
        return state

    def _load_execution_package(self):
        run = self._store.load_run(self._run_id)
        binding = run.get("package_binding") or {}
        manifest_path = ""
        if isinstance(binding, dict):
            manifest_path = str(binding.get("manifest_path") or "").strip()
        if not manifest_path:
            production = self._store.load_production(self._run_id)
            state = load_sub_tdp_state(production) or {}
            manifest_path = str(state.get("manifest_path") or "").strip()
        if not manifest_path:
            return None
        package_dir = Path(manifest_path).resolve().parent
        return ExecutionPackageLoader().load(package_dir)

    def _drive_prepared_unit(
        self,
        unit: SubTdpUnit,
        unit_record: dict[str, Any],
        create_provider: ProviderFactory,
        workspace: Path,
        config: dict[str, Any],
        package,
        child_store: FileRunStore,
        *,
        orchestration_state: dict[str, Any] | None = None,
        child_run_id: str | None = None,
        was_existing: bool = False,
    ) -> PreparedChildResult:
        child_run_id = child_run_id or str(unit_record.get("child_run_id") or "").strip() or None
        parent_run = self._store.load_run(self._run_id)
        invocation = dict(parent_run.get("invocation") or {})
        if not invocation:
            invocation = {"command": "execute", "observability": {}}

        if was_existing:
            self._append_event(
                "sub_tdp_child_resumed",
                unit_id=unit.plan_item_id,
                plan_item_id=unit.plan_item_id,
                child_run_id=child_run_id,
                package_id=package.manifest.get("package_id"),
                parent_run_id=self._run_id,
            )
        else:
            self._append_event(
                "sub_tdp_child_started",
                unit_id=unit.plan_item_id,
                plan_item_id=unit.plan_item_id,
                child_run_id=child_run_id,
                package_id=package.manifest.get("package_id"),
                parent_run_id=self._run_id,
            )

        from top_down_planning.cli.common import ResolvedRunsDir
        from top_down_planning.observability import build_observability_context

        resolved_runs = ResolvedRunsDir(path=child_store.root, source="cli")
        child_run_id = child_run_id or ""
        child_obs = self._observability
        if self._observability is not None and child_run_id:
            child_obs = build_observability_context(
                options=self._observability.options,
                run_id=child_run_id,
                run_dir=child_store.root / child_run_id,
            )

        def run_provider_factory(run_id: str):
            return build_execution_runtime(
                store=child_store,
                run_id=run_id,
                resolved_runs=resolved_runs,
                observability=child_obs,
                workspace=workspace,
            ).create_provider

        child_result = PreparedUnitExecutor().execute_unit(
            child_store,
            package,
            unit.plan_item_id,
            resolved_config=config,
            invocation=invocation,
            create_provider=create_provider,
            workspace=workspace,
            existing_child_run_id=child_run_id,
            parent_run_id=self._run_id,
            orchestration_state=orchestration_state,
            observability=child_obs,
            provider_factory_for_run=run_provider_factory,
        )
        unit_record["child_run_id"] = child_result.run.get("id")
        self._append_child_completion_event(
            unit=unit,
            package=package,
            child_result=child_result,
        )
        return child_result

    def _append_child_completion_event(
        self,
        *,
        unit: SubTdpUnit,
        package,
        child_result: PreparedChildResult,
    ) -> None:
        child_run = child_result.run
        if child_result.cancelled:
            event_type = "sub_tdp_child_cancelled"
        elif child_result.ok and str(child_run.get("outcome") or "") == "accepted":
            event_type = "sub_tdp_child_completed"
        elif str(child_run.get("status") or "") == "paused":
            event_type = "sub_tdp_child_paused"
        else:
            event_type = "sub_tdp_child_failed"
        self._append_event(
            event_type,
            unit_id=unit.plan_item_id,
            plan_item_id=unit.plan_item_id,
            child_run_id=child_run.get("id"),
            status=child_result.status,
            outcome=child_result.outcome,
            package_id=package.manifest.get("package_id"),
            parent_run_id=self._run_id,
            reason=child_result.reason,
        )

    def _synthesize_and_transition(
        self,
        plan: Plan,
        production: dict[str, Any],
        state: dict[str, Any],
        units: list[SubTdpUnit],
        child_store: FileRunStore,
    ) -> SubTdpsPhaseResult:
        if not all_units_completed(state, units):
            raise ProviderRunError(
                "sub_tdps synthesis requires every unit to reach completed status"
            )
        child_runs_data: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
        units_by_id = {unit.plan_item_id: unit for unit in units}
        for unit_record in state.get("units") or []:
            if not isinstance(unit_record, dict):
                continue
            plan_item_id = str(unit_record.get("plan_item_id") or "")
            unit = units_by_id.get(plan_item_id)
            child_run_id = str(unit_record.get("child_run_id") or "").strip()
            if unit is None or not child_run_id:
                continue
            child_run = child_store.load_run(child_run_id)
            child_production = child_store.load_production(child_run_id)
            child_runs_data.append((unit_record, child_run, child_production))

        production = self._store.load_production(self._run_id)
        parent_output_goal = str(plan.output_goal or "")

        def _promote_evidence(evidence: dict[str, Any], child_run_id: str) -> dict[str, Any]:
            return promote_child_evidence_to_parent(
                evidence,
                child_store=child_store,
                child_run_id=child_run_id,
                parent_store=self._store,
                parent_run_id=self._run_id,
            )

        synthesized = synthesize_parent_production(
            plan,
            production,
            child_runs=child_runs_data,
            parent_output_goal=parent_output_goal,
            promote_evidence=_promote_evidence,
        )
        expected_production_revision = int(production["revision"])
        synthesized["revision"] = expected_production_revision + 1
        self._store.save_production(
            self._run_id,
            synthesized,
            expected_production_revision,
        )
        self._append_event("sub_tdps_synthesis_completed")
        return self._transition_to_integration_production()

    def _transition_to_integration_production(self) -> SubTdpsPhaseResult:
        """Move parent into production so the integration producer can claim goal_met."""

        run = self._store.load_run(self._run_id)
        production = self._store.load_production(self._run_id)
        claim = production.get("completion_claim")
        if completion_claim_asserts_goal_met(claim if isinstance(claim, dict) else None):
            return self._transition_to_whole_output_review()

        expected_revision = int(run["revision"])
        run = dict(run)
        run["revision"] = expected_revision + 1
        run["phase"] = PRODUCTION
        digests = dict(run.get("digests") or {})
        digests["output"] = compute_output_digest(production)
        run["digests"] = digests
        self._store.save_run(self._run_id, run, expected_revision)
        self._append_event(
            "sub_tdps_integration_production_entered",
            package_id=(run.get("package_binding") or {}).get("package_id"),
        )
        units_completed = sum(
            1
            for unit in (load_sub_tdp_state(production) or {}).get("units") or []
            if isinstance(unit, dict) and unit.get("status") == UNIT_STATUS_COMPLETED
        )
        return self._result_from_run(
            self._store.load_run(self._run_id),
            ok=True,
            units_completed=units_completed,
        )

    def _transition_to_whole_output_review(self) -> SubTdpsPhaseResult:
        run = self._store.load_run(self._run_id)
        production = self._store.load_production(self._run_id)
        config = self._store.load_resolved_config(self._run_id)
        workspace = run_workspace(run)
        expected_revision = int(run["revision"])
        digests = dict(run.get("digests") or {})
        old_binding = dict(run.get("context_snapshot_binding") or {})
        old_snapshot_digest = str(digests.get("context_snapshot") or "")

        new_binding, new_snapshot_digest, diagnostics = (
            recompute_context_snapshot_binding_with_diagnostics(
                config,
                workspace=workspace,
            )
        )
        changed_paths: list[str] = []
        if new_snapshot_digest != old_snapshot_digest:
            changed_paths = validate_production_snapshot_rebase(
                old_binding,
                new_binding,
                production,
                workspace=workspace,
            )

        snapshot_rebased = new_snapshot_digest != old_snapshot_digest
        run = dict(run)
        run["revision"] = expected_revision + 1
        run["phase"] = WHOLE_OUTPUT_REVIEW
        digests["output"] = compute_output_digest(production)
        if snapshot_rebased:
            digests["context_snapshot"] = new_snapshot_digest
            run["context_snapshot_binding"] = new_binding
        run["digests"] = digests
        self._store.save_run(self._run_id, run, expected_revision)
        self._append_event(
            "context_snapshot_collected",
            **diagnostics.to_event_fields(),
        )
        if snapshot_rebased:
            self._append_event(
                "context_snapshot_rebased",
                phase_transition=f"{SUB_TDPS}->{WHOLE_OUTPUT_REVIEW}",
                prior_snapshot_digest=short_digest_for_observability(old_snapshot_digest),
                new_snapshot_digest=short_digest_for_observability(new_snapshot_digest),
                changed_path_count=len(changed_paths),
                changed_paths=[
                    short_path_for_observability(path) for path in changed_paths[:10]
                ],
                **diagnostics.to_event_fields(),
            )
        self._append_event("sub_tdps_completed")
        units_completed = sum(
            1
            for unit in (load_sub_tdp_state(production) or {}).get("units") or []
            if isinstance(unit, dict) and unit.get("status") == UNIT_STATUS_COMPLETED
        )
        return self._result_from_run(
            self._store.load_run(self._run_id),
            ok=True,
            units_completed=units_completed,
        )

    def _enter_sub_tdps_phase(self) -> dict[str, Any]:
        run = self._store.load_run(self._run_id)
        expected_revision = int(run["revision"])
        run = dict(run)
        run["revision"] = expected_revision + 1
        run["phase"] = SUB_TDPS
        self._store.save_run(self._run_id, run, expected_revision)
        self._append_event("sub_tdps_phase_entered")
        return self._store.load_run(self._run_id)

    def _commit_production_state(
        self,
        production: dict[str, Any],
        state: dict[str, Any],
    ) -> None:
        merged = merge_sub_tdp_state_into_production(production, state)
        expected_revision = int(production["revision"])
        merged["revision"] = expected_revision + 1
        self._store.save_production(self._run_id, merged, expected_revision)

    def _result_from_run(
        self,
        run: dict[str, Any],
        *,
        ok: bool,
        units_completed: int,
        reason: str | None = None,
    ) -> SubTdpsPhaseResult:
        return SubTdpsPhaseResult(
            ok=ok,
            phase=str(run.get("phase") or SUB_TDPS),
            status=str(run.get("status") or "running"),
            outcome=run.get("outcome"),
            units_completed=units_completed,
            reason=reason,
        )

    def _append_event(self, event_type: str, **fields: Any) -> None:
        self._store.append_event(
            self._run_id,
            {"type": event_type, "run_id": self._run_id, **fields},
        )

    def _require_plan_approval(self) -> None:
        plan = self._store.load_plan_model(self._run_id)
        approval = find_whole_plan_approval(
            self._store.list_reviews(self._run_id),
            plan.revision,
        )
        if approval is None:
            raise ProviderRunError(
                "sub_tdps requires an approved whole-plan review "
                "for the current plan revision"
            )


__all__ = ["SubTdpsPhaseOrchestrator", "SubTdpsPhaseResult"]
