"""Shared direct and parent-driven prepared unit execution (proposal §12–13)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from top_down_planning.orchestrator.phases import OUTPUT_VALIDATED
from top_down_planning.orchestrator.prepared_run_factory import PreparedRunFactory
from top_down_planning.orchestrator.sub_tdp_child_driver import (
    PreparedChildResult,
    continue_child_sub_tdp,
)
from top_down_planning.package.lineage import (
    ExecutionLineageValidator,
    accepted_result_record,
    upstream_accepted_result_binding,
)
from top_down_planning.package.loader import ExecutionPackageError, LoadedExecutionPackage
from top_down_planning.persistence import FileRunStore

ProviderFactory = Callable[[dict[str, Any], Path], Any]
RuntimeFactory = Callable[[str], Any]


def validate_explicit_upstream_bindings(
    package: LoadedExecutionPackage,
    unit_id: str,
    bindings: dict[str, str],
) -> None:
    """Require a complete explicit map for all unit dependencies."""

    unit = package.units.get(unit_id)
    if unit is None:
        known = ", ".join(sorted(package.units))
        raise ExecutionPackageError(
            f"unknown unit: {unit_id!r}; valid units: {known}",
            code="unknown_unit",
        )
    required = set(unit.depends_on)
    provided = set(bindings)
    unknown = sorted(provided - required)
    if unknown:
        raise ExecutionPackageError(
            f"--upstream unit(s) are not dependencies of {unit_id!r}: "
            + ", ".join(unknown),
            code="sub_tdp_upstream_invalid",
        )
    missing = sorted(required - provided)
    if missing:
        raise ExecutionPackageError(
            f"--upstream missing required dependencies for {unit_id!r}: "
            + ", ".join(missing),
            code="sub_tdp_upstream_invalid",
        )


class PreparedUnitExecutor:
    """Execute one prepared unit through production and output review."""

    class DependencyUnmetError(ExecutionPackageError):
        def __init__(self, unit_id: str, dependency_id: str) -> None:
            super().__init__(
                f"unit {unit_id!r} blocked: unmet dependency {dependency_id!r}",
                code="sub_tdp_dependency_unmet",
            )
            self.unit_id = unit_id
            self.dependency_id = dependency_id
            self.stop_code = "sub_tdp_dependency_unmet"

    def __init__(self, *, run_factory: PreparedRunFactory | None = None) -> None:
        self._run_factory = run_factory or PreparedRunFactory()

    def create_or_load_child_run(
        self,
        child_store: FileRunStore,
        package: LoadedExecutionPackage,
        unit_id: str,
        *,
        resolved_config: dict[str, Any],
        invocation: dict[str, Any],
        existing_child_run_id: str | None = None,
        parent_run_id: str | None = None,
        orchestration_state: dict[str, Any] | None = None,
        explicit_upstream: dict[str, str] | None = None,
        explicit_upstream_only: bool = False,
        explicit_baseline_run_ids: list[str] | None = None,
    ) -> str:
        unit = package.units.get(unit_id)
        if unit is None:
            known = ", ".join(sorted(package.units))
            raise ExecutionPackageError(
                f"unknown unit: {unit_id!r}; valid units: {known}",
                code="unknown_unit",
            )

        if orchestration_state is not None:
            from top_down_planning.persistence.sub_tdp_state import (
                UNIT_STATUS_COMPLETED,
                find_unit,
            )

            for dep_id in unit.depends_on:
                dep_record = find_unit(orchestration_state, dep_id)
                if (
                    dep_record is None
                    or str(dep_record.get("status") or "") != UNIT_STATUS_COMPLETED
                    or not str(dep_record.get("accepted_result_digest") or "").strip()
                ):
                    raise self.DependencyUnmetError(unit_id, dep_id)
        else:
            if explicit_upstream_only:
                validate_explicit_upstream_bindings(
                    package,
                    unit_id,
                    explicit_upstream or {},
                )
            self._check_external_dependencies(
                package,
                unit_id,
                child_store,
                explicit_upstream=explicit_upstream,
                explicit_upstream_only=explicit_upstream_only,
            )

        upstream = self._collect_upstream_accepted_results(
            child_store,
            package=package,
            unit_id=unit_id,
            orchestration_state=orchestration_state,
            explicit_upstream=explicit_upstream,
            explicit_upstream_only=explicit_upstream_only,
        )
        baseline = self._collect_workspace_baseline_results(
            child_store,
            package=package,
            unit_id=unit_id,
            direct_upstream=upstream,
            orchestration_state=orchestration_state,
            explicit_upstream=explicit_upstream,
            explicit_upstream_only=explicit_upstream_only,
            explicit_baseline_run_ids=explicit_baseline_run_ids,
        )

        if existing_child_run_id:
            child_run = child_store.load_run(existing_child_run_id)
            mismatches = ExecutionLineageValidator().validate_resume(
                parent_package=package,
                child_run=child_run,
                expected_unit_id=unit_id,
            )
            if mismatches:
                detail = mismatches[0]
                raise ExecutionPackageError(
                    f"existing child lineage mismatch on {detail.field}: "
                    f"expected {detail.expected}, got {detail.actual}",
                    code="sub_tdp_lineage_mismatch",
                )
            child_run_id = existing_child_run_id
        else:
            creation_key = self._child_creation_key(
                package=package,
                unit_id=unit_id,
                parent_run_id=parent_run_id,
            )
            child_run_id = None
            if creation_key:
                existing = self._find_child_by_creation_key(child_store, creation_key)
                if existing is not None:
                    mismatches = ExecutionLineageValidator().validate_resume(
                        parent_package=package,
                        child_run=existing,
                        expected_unit_id=unit_id,
                    )
                    if mismatches:
                        detail = mismatches[0]
                        raise ExecutionPackageError(
                            f"existing child lineage mismatch on {detail.field}: "
                            f"expected {detail.expected}, got {detail.actual}",
                            code="sub_tdp_lineage_mismatch",
                        )
                    child_run_id = str(existing.get("id") or "")

            if child_run_id is None:
                child_run_id = self._run_factory.create_child_run(
                    child_store,
                    package,
                    unit,
                    resolved_config=resolved_config,
                    invocation=self._child_invocation(invocation, parent_run_id, unit_id),
                    upstream_accepted_results=upstream,
                    workspace_baseline_results=baseline,
                )

        self._ensure_child_package_bindings(
            child_store,
            child_run_id,
            package=package,
            unit_id=unit_id,
            upstream=upstream,
            baseline=baseline,
        )
        return child_run_id

    def drive_child_run(
        self,
        child_store: FileRunStore,
        child_run_id: str,
        *,
        create_provider: ProviderFactory,
        workspace: Path,
        observability: Any | None = None,
    ) -> PreparedChildResult:
        child_run = child_store.load_run(child_run_id)
        if self._is_terminal(child_run):
            self._revalidate_terminal_child_delivery(child_store, child_run_id, child_run)
            return PreparedChildResult.from_run(child_run, ok=True)
        return continue_child_sub_tdp(
            child_store,
            child_run_id,
            create_provider=create_provider,
            workspace=workspace,
            observability=observability,
        )

    def execute_unit(
        self,
        child_store: FileRunStore,
        package: LoadedExecutionPackage,
        unit_id: str,
        *,
        resolved_config: dict[str, Any],
        invocation: dict[str, Any],
        create_provider: ProviderFactory,
        workspace: Path,
        existing_child_run_id: str | None = None,
        parent_run_id: str | None = None,
        orchestration_state: dict[str, Any] | None = None,
        observability: Any | None = None,
        provider_factory_for_run: Callable[[str], ProviderFactory] | None = None,
        explicit_upstream: dict[str, str] | None = None,
    ) -> PreparedChildResult:
        child_run_id = self.create_or_load_child_run(
            child_store,
            package,
            unit_id,
            resolved_config=resolved_config,
            invocation=invocation,
            existing_child_run_id=existing_child_run_id,
            parent_run_id=parent_run_id,
            orchestration_state=orchestration_state,
            explicit_upstream=explicit_upstream,
        )
        child_run = child_store.load_run(child_run_id)
        if self._is_terminal(child_run):
            self._revalidate_terminal_child_delivery(child_store, child_run_id, child_run)
            return PreparedChildResult.from_run(child_run, ok=True)

        if provider_factory_for_run is not None:
            create_provider = provider_factory_for_run(child_run_id)

        return self.drive_child_run(
            child_store,
            child_run_id,
            create_provider=create_provider,
            workspace=workspace,
            observability=observability,
        )

    def _child_invocation(
        self,
        parent_invocation: dict[str, Any],
        parent_run_id: str | None,
        unit_id: str,
    ) -> dict[str, Any]:
        invocation = dict(parent_invocation)
        invocation["command"] = "sub_tdp_child"
        observability = dict(invocation.get("observability") or {})
        invocation["observability"] = observability
        invocation["sub_tdp"] = {
            "parent_run_id": parent_run_id,
            "unit_id": unit_id,
        }
        return invocation

    @staticmethod
    def _child_creation_key(
        *,
        package: LoadedExecutionPackage,
        unit_id: str,
        parent_run_id: str | None,
    ) -> str | None:
        parent = str(parent_run_id or "").strip()
        if not parent:
            return None
        unit = str(unit_id or "").strip()
        package_digest = str(package.manifest.get("package_digest") or "").strip()
        if not unit or not package_digest:
            return None
        return f"{package_digest}:{parent}:{unit}"

    @staticmethod
    def _find_child_by_creation_key(
        child_store: FileRunStore,
        creation_key: str,
    ) -> dict[str, Any] | None:
        matches: list[dict[str, Any]] = []
        for run_dir in sorted(child_store.root.iterdir(), key=lambda p: p.name):
            if not run_dir.is_dir() or run_dir.name.startswith("."):
                continue
            try:
                run = child_store.load_run(run_dir.name)
            except (OSError, ValueError, KeyError):
                continue
            binding = run.get("package_binding") or {}
            if not isinstance(binding, dict):
                continue
            if str(binding.get("creation_key") or "") == creation_key:
                matches.append(run)
        if len(matches) > 1:
            ids = ", ".join(str(m.get("id") or "") for m in matches)
            raise ExecutionPackageError(
                f"multiple child runs for creation key {creation_key!r}: {ids}",
                code="sub_tdp_duplicate_children",
            )
        return matches[0] if matches else None

    def _check_external_dependencies(
        self,
        package: LoadedExecutionPackage,
        unit_id: str,
        child_store: FileRunStore,
        *,
        explicit_upstream: dict[str, str] | None = None,
        explicit_upstream_only: bool = False,
    ) -> None:
        unit = package.units[unit_id]
        for dep_id in unit.depends_on:
            if dep_id not in package.units:
                raise ExecutionPackageError(
                    f"unit {unit_id} depends on unknown unit {dep_id!r}",
                    code="sub_tdp_dependency_unmet",
                )
            dep_unit = package.units[dep_id]
            dep_accepted = self._find_accepted_dependency_run(
                child_store,
                package=package,
                dep_unit_id=dep_id,
                dep_unit=dep_unit,
                explicit_upstream=explicit_upstream,
                explicit_upstream_only=explicit_upstream_only,
            )
            if dep_accepted is None:
                raise self.DependencyUnmetError(unit_id, dep_id)

    def _collect_upstream_accepted_results(
        self,
        child_store: FileRunStore,
        *,
        package: LoadedExecutionPackage,
        unit_id: str,
        orchestration_state: dict[str, Any] | None,
        explicit_upstream: dict[str, str] | None = None,
        explicit_upstream_only: bool = False,
    ) -> list[dict[str, Any]]:
        from top_down_planning.package.lineage import (
            accepted_result_record,
            upstream_accepted_result_binding,
            verify_accepted_result_attestation,
        )

        package_id = str(package.manifest.get("package_id") or "")
        package_digest = str(package.manifest.get("package_digest") or "")
        unit = package.units[unit_id]
        results: list[dict[str, Any]] = []
        for dep_id in unit.depends_on:
            dep_unit = package.units[dep_id]
            if orchestration_state is not None:
                from top_down_planning.persistence.sub_tdp_state import find_unit

                dep_record = find_unit(orchestration_state, dep_id) or {}
                accepted = dep_record.get("accepted_result")
                if isinstance(accepted, dict):
                    verify_accepted_result_attestation(dep_record)
                    child_run_id = str(accepted.get("child_run_id") or "").strip()
                    if not child_run_id:
                        raise ExecutionPackageError(
                            f"orchestration upstream {dep_id!r} missing child_run_id",
                            code="sub_tdp_upstream_invalid",
                        )
                    entry = self._validated_accepted_result_entry(
                        child_store,
                        child_run_id=child_run_id,
                        unit_id=dep_id,
                        unit_plan_digest=dep_unit.plan_digest,
                        package_id=package_id,
                        package_digest=package_digest,
                        assigned_subtree_digest=dep_unit.assigned_subtree_digest,
                        error_label=f"orchestration upstream {dep_id!r}",
                    )
                    results.append(
                        upstream_accepted_result_binding(
                            entry,
                            upstream_contract_digest=dep_unit.assigned_subtree_digest,
                        )
                    )
                    continue
                child_run_id = str(dep_record.get("child_run_id") or "").strip()
                if not child_run_id:
                    raise self.DependencyUnmetError(unit_id, dep_id)
                entry = self._validated_accepted_result_entry(
                    child_store,
                    child_run_id=child_run_id,
                    unit_id=dep_id,
                    unit_plan_digest=dep_unit.plan_digest,
                    package_id=package_id,
                    package_digest=package_digest,
                    assigned_subtree_digest=dep_unit.assigned_subtree_digest,
                    error_label=f"orchestration upstream {dep_id!r}",
                )
                results.append(
                    upstream_accepted_result_binding(
                        entry,
                        upstream_contract_digest=dep_unit.assigned_subtree_digest,
                    )
                )
                continue
            matched = self._find_accepted_dependency_run(
                child_store,
                package=package,
                dep_unit_id=dep_id,
                dep_unit=dep_unit,
                explicit_upstream=explicit_upstream,
                explicit_upstream_only=explicit_upstream_only,
            )
            if matched is None:
                raise self.DependencyUnmetError(unit_id, dep_id)
            child_run, child_production = matched
            entry = accepted_result_record(
                child_run=child_run,
                child_production=child_production,
                unit_id=dep_id,
                unit_plan_digest=dep_unit.plan_digest,
                package_id=package_id,
                package_digest=package_digest,
                assigned_subtree_digest=dep_unit.assigned_subtree_digest,
            )
            results.append(
                upstream_accepted_result_binding(
                    entry,
                    upstream_contract_digest=dep_unit.assigned_subtree_digest,
                )
            )
        return results

    def _collect_workspace_baseline_results(
        self,
        child_store: FileRunStore,
        *,
        package: LoadedExecutionPackage,
        unit_id: str,
        direct_upstream: list[dict[str, Any]],
        orchestration_state: dict[str, Any] | None,
        explicit_upstream: dict[str, str] | None = None,
        explicit_upstream_only: bool = False,
        explicit_baseline_run_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Cumulative accepted results authorizing shared-workspace resource drift."""

        from top_down_planning.package.lineage import (
            accepted_result_record,
            upstream_accepted_result_binding,
            verify_accepted_result_attestation,
            verify_baseline_wrapper_matches_current_package,
            verify_upstream_accepted_result_binding,
        )
        from top_down_planning.persistence.sub_tdp_state import UNIT_STATUS_COMPLETED

        package_id = str(package.manifest.get("package_id") or "")
        package_digest = str(package.manifest.get("package_digest") or "")
        seen: set[str] = set()
        results: list[dict[str, Any]] = []

        def add_wrapper(wrapper: dict[str, Any], *, require_live: bool = False) -> None:
            try:
                verify_upstream_accepted_result_binding(wrapper)
                verify_baseline_wrapper_matches_current_package(
                    wrapper,
                    package_id=package_id,
                    package_digest=package_digest,
                    package_units=package.units,
                )
            except ValueError as exc:
                raise ExecutionPackageError(
                    str(exc),
                    code="sub_tdp_upstream_invalid",
                ) from exc
            if require_live:
                from top_down_planning.package.lineage import (
                    verify_upstream_wrapper_matches_live_delivery,
                )

                try:
                    verify_upstream_wrapper_matches_live_delivery(child_store, wrapper)
                except (OSError, ValueError, KeyError) as exc:
                    raise ExecutionPackageError(
                        f"baseline closure wrapper delivery invalid: {exc}",
                        code="sub_tdp_upstream_invalid",
                    ) from exc
            digest = str(wrapper.get("accepted_result_digest") or "")
            if not digest or digest in seen:
                return
            seen.add(digest)
            results.append(wrapper)

        for wrapper in direct_upstream:
            add_wrapper(wrapper)

        def add_closure_from_child(child_run_id: str) -> None:
            if not child_run_id:
                return
            try:
                child_run = child_store.load_run(child_run_id)
            except (OSError, ValueError, KeyError) as exc:
                raise ExecutionPackageError(
                    f"baseline closure child {child_run_id!r} is missing or unreadable",
                    code="sub_tdp_upstream_invalid",
                ) from exc
            binding = child_run.get("package_binding")
            if not isinstance(binding, dict):
                raise ExecutionPackageError(
                    f"baseline closure child {child_run_id!r} missing package_binding",
                    code="sub_tdp_upstream_invalid",
                )
            for key in (
                "upstream_accepted_results",
                "workspace_baseline_accepted_results",
            ):
                for nested in binding.get(key) or []:
                    if isinstance(nested, dict):
                        add_wrapper(nested, require_live=True)

        for wrapper in list(results):
            accepted = wrapper.get("accepted_result") or {}
            add_closure_from_child(str(accepted.get("child_run_id") or "").strip())

        for baseline_run_id in explicit_baseline_run_ids or []:
            wrapper = self._wrapper_from_accepted_child_run(
                child_store,
                package=package,
                child_run_id=str(baseline_run_id).strip(),
                error_label=f"explicit baseline {baseline_run_id!r}",
            )
            add_wrapper(wrapper)
            add_closure_from_child(str(baseline_run_id).strip())

        if orchestration_state is not None:
            for unit_record in orchestration_state.get("units") or []:
                if not isinstance(unit_record, dict):
                    continue
                peer_id = str(unit_record.get("plan_item_id") or "").strip()
                if not peer_id or peer_id == unit_id:
                    continue
                if str(unit_record.get("status") or "") != UNIT_STATUS_COMPLETED:
                    continue
                peer_unit = package.units.get(peer_id)
                if peer_unit is None:
                    continue
                accepted = unit_record.get("accepted_result")
                if isinstance(accepted, dict):
                    try:
                        verify_accepted_result_attestation(unit_record)
                    except ValueError as exc:
                        raise ExecutionPackageError(
                            f"orchestration baseline {peer_id!r} attestation invalid: {exc}",
                            code="sub_tdp_upstream_invalid",
                        ) from exc
                    child_run_id = str(accepted.get("child_run_id") or "").strip()
                    if not child_run_id:
                        raise ExecutionPackageError(
                            f"orchestration baseline {peer_id!r} missing child_run_id",
                            code="sub_tdp_upstream_invalid",
                        )
                    entry = self._validated_accepted_result_entry(
                        child_store,
                        child_run_id=child_run_id,
                        unit_id=peer_id,
                        unit_plan_digest=peer_unit.plan_digest,
                        package_id=package_id,
                        package_digest=package_digest,
                        assigned_subtree_digest=peer_unit.assigned_subtree_digest,
                        error_label=f"orchestration baseline {peer_id!r}",
                    )
                    add_wrapper(
                        upstream_accepted_result_binding(
                            entry,
                            upstream_contract_digest=peer_unit.assigned_subtree_digest,
                        )
                    )
                    add_closure_from_child(child_run_id)
                    continue
                child_run_id = str(unit_record.get("child_run_id") or "").strip()
                if not child_run_id:
                    continue
                entry = self._validated_accepted_result_entry(
                    child_store,
                    child_run_id=child_run_id,
                    unit_id=peer_id,
                    unit_plan_digest=peer_unit.plan_digest,
                    package_id=package_id,
                    package_digest=package_digest,
                    assigned_subtree_digest=peer_unit.assigned_subtree_digest,
                    error_label=f"orchestration baseline {peer_id!r}",
                )
                add_wrapper(
                    upstream_accepted_result_binding(
                        entry,
                        upstream_contract_digest=peer_unit.assigned_subtree_digest,
                    )
                )
                add_closure_from_child(child_run_id)
            return results

        # Non-orchestration independent units: discover accepted siblings as baseline.
        unit = package.units[unit_id]
        if unit.depends_on or explicit_upstream_only:
            return results
        for peer_id, peer_unit in package.units.items():
            if peer_id == unit_id:
                continue
            matched = self._find_accepted_dependency_run(
                child_store,
                package=package,
                dep_unit_id=peer_id,
                dep_unit=peer_unit,
                explicit_upstream=explicit_upstream,
                explicit_upstream_only=False,
            )
            if matched is None:
                continue
            child_run, child_production = matched
            entry = accepted_result_record(
                child_run=child_run,
                child_production=child_production,
                unit_id=peer_id,
                unit_plan_digest=peer_unit.plan_digest,
                package_id=package_id,
                package_digest=package_digest,
                assigned_subtree_digest=peer_unit.assigned_subtree_digest,
            )
            add_wrapper(
                upstream_accepted_result_binding(
                    entry,
                    upstream_contract_digest=peer_unit.assigned_subtree_digest,
                )
            )
            add_closure_from_child(str(child_run.get("id") or ""))
        return results

    def _wrapper_from_accepted_child_run(
        self,
        child_store: FileRunStore,
        *,
        package: LoadedExecutionPackage,
        child_run_id: str,
        error_label: str,
    ) -> dict[str, Any]:
        """Resolve an accepted child run into a digest-verified baseline wrapper."""

        from top_down_planning.package.lineage import upstream_accepted_result_binding

        if not child_run_id:
            raise ExecutionPackageError(
                f"{error_label} missing run id",
                code="sub_tdp_baseline_invalid",
            )
        try:
            child_run = child_store.load_run(child_run_id)
        except (OSError, ValueError, KeyError) as exc:
            raise ExecutionPackageError(
                f"{error_label} is missing or unreadable",
                code="sub_tdp_baseline_invalid",
            ) from exc
        binding = child_run.get("package_binding") or {}
        if not isinstance(binding, dict):
            raise ExecutionPackageError(
                f"{error_label} missing package_binding",
                code="sub_tdp_baseline_invalid",
            )
        bound_unit_id = str(binding.get("unit_id") or "").strip()
        if not bound_unit_id or bound_unit_id not in package.units:
            raise ExecutionPackageError(
                f"{error_label} is not bound to a unit in this package",
                code="sub_tdp_baseline_invalid",
            )
        peer_unit = package.units[bound_unit_id]
        package_id = str(package.manifest.get("package_id") or "")
        package_digest = str(package.manifest.get("package_digest") or "")
        if str(binding.get("package_digest") or "") != package_digest:
            raise ExecutionPackageError(
                f"{error_label} package_digest does not match current package",
                code="sub_tdp_baseline_invalid",
            )
        entry = self._validated_accepted_result_entry(
            child_store,
            child_run_id=child_run_id,
            unit_id=bound_unit_id,
            unit_plan_digest=peer_unit.plan_digest,
            package_id=package_id,
            package_digest=package_digest,
            assigned_subtree_digest=peer_unit.assigned_subtree_digest,
            error_label=error_label,
        )
        return upstream_accepted_result_binding(
            entry,
            upstream_contract_digest=peer_unit.assigned_subtree_digest,
        )

    @staticmethod
    def _validated_accepted_result_entry(
        child_store: FileRunStore,
        *,
        child_run_id: str,
        unit_id: str,
        unit_plan_digest: str,
        package_id: str,
        package_digest: str,
        assigned_subtree_digest: str,
        error_label: str,
    ) -> dict[str, Any]:
        from top_down_planning.package.lineage import (
            accepted_result_record,
            validate_accepted_child_delivery,
        )

        try:
            child_run = child_store.load_run(child_run_id)
            child_production = child_store.load_production(child_run_id)
            validate_accepted_child_delivery(
                store=child_store,
                child_run_id=child_run_id,
                child_run=child_run,
                child_production=child_production,
                verify_evidence=True,
            )
        except (OSError, ValueError, KeyError) as exc:
            raise ExecutionPackageError(
                f"{error_label} delivery invalid: {exc}",
                code="sub_tdp_upstream_invalid",
            ) from exc
        return accepted_result_record(
            child_run=child_run,
            child_production=child_production,
            unit_id=unit_id,
            unit_plan_digest=unit_plan_digest,
            package_id=package_id,
            package_digest=package_digest,
            assigned_subtree_digest=assigned_subtree_digest,
        )

    @staticmethod
    def _child_execution_started(
        run: dict[str, Any],
        production: dict[str, Any],
    ) -> bool:
        from top_down_planning.orchestrator.phases import PLAN_VALIDATED

        if str(run.get("phase") or "") != PLAN_VALIDATED:
            return True
        if production.get("batches"):
            return True
        sessions = run.get("provider_sessions") or {}
        if isinstance(sessions, dict) and sessions:
            return True
        if isinstance(sessions, list) and sessions:
            return True
        return False

    @staticmethod
    def _ensure_child_package_bindings(
        child_store: FileRunStore,
        child_run_id: str,
        *,
        package: LoadedExecutionPackage,
        unit_id: str,
        upstream: list[dict[str, Any]],
        baseline: list[dict[str, Any]],
    ) -> None:
        """Idempotently persist upstream wrappers, baseline, and external prerequisites."""

        from top_down_planning.package.lineage import verify_upstream_accepted_result_binding
        from top_down_planning.config.context import (
            compute_context_snapshot_digest_from_payload,
        )
        from top_down_planning.domain.reviews import find_whole_plan_approval
        from top_down_planning.orchestrator.phases import PLAN_VALIDATED
        from top_down_planning.package.execution_validation import (
            verify_package_context_snapshot_with_baseline,
        )

        unit = package.units[unit_id]
        external = list(unit.external_prerequisites)
        desired_upstream = list(upstream)
        desired_baseline = list(baseline)
        for wrapper in desired_upstream + desired_baseline:
            try:
                verify_upstream_accepted_result_binding(wrapper)
            except ValueError as exc:
                raise ExecutionPackageError(
                    str(exc),
                    code="sub_tdp_upstream_invalid",
                ) from exc

        run = child_store.load_run(child_run_id)
        production = child_store.load_production(child_run_id)
        binding = dict(run.get("package_binding") or {})

        if PreparedUnitExecutor._child_execution_started(run, production):
            stored_upstream = binding.get("upstream_accepted_results")
            stored_baseline = binding.get("workspace_baseline_accepted_results")
            stored_external = binding.get("external_prerequisites")
            stored_baseline_digest = str(
                binding.get("baseline_context_snapshot_digest") or ""
            ).strip()
            stored_lineage = binding.get("baseline_accepted_result_digests")
            expected_initial = str(
                (package.manifest.get("context") or {}).get("context_snapshot_digest") or ""
            )
            from top_down_planning.package.lineage import (
                baseline_accepted_result_digests_from_wrappers,
            )

            desired_lineage_for_check = baseline_accepted_result_digests_from_wrappers(
                desired_baseline
            )
            if (
                not desired_lineage_for_check
                and stored_baseline_digest != expected_initial
            ):
                raise ExecutionPackageError(
                    "child with empty baseline_accepted_result_digests must be at "
                    "package initial snapshot",
                    code="sub_tdp_upstream_invalid",
                )
            if (
                stored_upstream != desired_upstream
                or stored_baseline != desired_baseline
                or stored_external != external
                or stored_lineage != desired_lineage_for_check
            ):
                raise ExecutionPackageError(
                    "child package bindings are immutable after execution starts",
                    code="sub_tdp_binding_immutable",
                )
            if not stored_baseline_digest:
                raise ExecutionPackageError(
                    "child missing baseline_context_snapshot_digest after execution started",
                    code="sub_tdp_binding_immutable",
                )
            # Do not rebase context from package+baseline; prepare_resume owns
            # validation of the child's own production evidence.
            return

        snapshot_binding = verify_package_context_snapshot_with_baseline(
            package,
            store=child_store,
            baseline_wrappers=desired_baseline,
        )
        context_snapshot_digest = compute_context_snapshot_digest_from_payload(
            snapshot_binding
        )

        from top_down_planning.package.lineage import (
            baseline_accepted_result_digests_from_wrappers,
        )

        expected_initial = str(
            (package.manifest.get("context") or {}).get("context_snapshot_digest") or ""
        )
        desired_baseline_digests = baseline_accepted_result_digests_from_wrappers(
            desired_baseline
        )
        if not desired_baseline_digests and context_snapshot_digest != expected_initial:
            raise ExecutionPackageError(
                "child with empty baseline_accepted_result_digests must be at "
                "package initial snapshot",
                code="sub_tdp_upstream_invalid",
            )

        binding_unchanged = (
            binding.get("upstream_accepted_results") == desired_upstream
            and binding.get("workspace_baseline_accepted_results") == desired_baseline
            and binding.get("baseline_accepted_result_digests") == desired_baseline_digests
            and binding.get("external_prerequisites") == external
            and "upstream_accepted_results" in binding
            and "workspace_baseline_accepted_results" in binding
            and "baseline_accepted_result_digests" in binding
            and "external_prerequisites" in binding
            and str(binding.get("baseline_context_snapshot_digest") or "")
            == context_snapshot_digest
        )
        snapshot_unchanged = (
            run.get("context_snapshot_binding") == snapshot_binding
            and str((run.get("digests") or {}).get("context_snapshot") or "")
            == context_snapshot_digest
        )
        if binding_unchanged and snapshot_unchanged:
            return

        # Retrofit only while the child is still at the initial inherited approval.
        bindings_present = (
            "upstream_accepted_results" in binding
            or "workspace_baseline_accepted_results" in binding
        )
        bindings_changing = (
            binding.get("upstream_accepted_results") != desired_upstream
            or binding.get("workspace_baseline_accepted_results") != desired_baseline
            or binding.get("baseline_accepted_result_digests") != desired_baseline_digests
        )
        if (
            bindings_present
            and bindings_changing
            and str(run.get("phase") or "") != PLAN_VALIDATED
        ):
            raise ExecutionPackageError(
                "child package bindings can only be retrofitted before execution starts",
                code="sub_tdp_binding_immutable",
            )

        binding["upstream_accepted_results"] = desired_upstream
        binding["workspace_baseline_accepted_results"] = desired_baseline
        binding["baseline_accepted_result_digests"] = desired_baseline_digests
        binding["external_prerequisites"] = external
        binding["baseline_context_snapshot_digest"] = context_snapshot_digest
        run["package_binding"] = binding
        run["context_snapshot_binding"] = snapshot_binding
        digests = dict(run.get("digests") or {})
        digests["context_snapshot"] = context_snapshot_digest
        run["digests"] = digests
        expected = int(run["revision"])
        run["revision"] = expected + 1
        child_store.save_run(child_run_id, run, expected)

        # Keep the derived execution approval binding aligned with the rebased snapshot.
        plan = child_store.load_plan(child_run_id)
        reviews = child_store.list_reviews(child_run_id)
        approval = find_whole_plan_approval(reviews, int(plan.get("revision") or 0))
        if approval is not None and approval.get("inherited_plan_approval"):
            updated = dict(approval)
            approved = dict(updated.get("approved_digests") or {})
            approved["context_snapshot"] = context_snapshot_digest
            updated["approved_digests"] = approved
            child_store.save_review(child_run_id, updated)

    @staticmethod
    def _find_accepted_dependency_run(
        child_store: FileRunStore,
        *,
        package: LoadedExecutionPackage,
        dep_unit_id: str,
        dep_unit,
        explicit_upstream: dict[str, str] | None = None,
        explicit_upstream_only: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        if explicit_upstream is not None and dep_unit_id in explicit_upstream:
            run_id = str(explicit_upstream[dep_unit_id] or "").strip()
            if not run_id:
                return None
            from core_tools.persistence.revision import RunNotFoundError

            try:
                run = child_store.load_run(run_id)
                production = child_store.load_production(run_id)
            except (OSError, ValueError, KeyError, RunNotFoundError) as exc:
                raise ExecutionPackageError(
                    f"explicit upstream run {run_id!r} is missing or unreadable",
                    code="sub_tdp_upstream_invalid",
                ) from exc
            resume_mismatches = ExecutionLineageValidator().validate_resume(
                parent_package=package,
                child_run=run,
                expected_unit_id=dep_unit_id,
            )
            if resume_mismatches:
                detail = resume_mismatches[0]
                raise ExecutionPackageError(
                    f"explicit upstream {dep_unit_id!r} unit mismatch on "
                    f"{detail.field}: expected {detail.expected}, got {detail.actual}",
                    code="sub_tdp_upstream_invalid",
                )
            mismatches = ExecutionLineageValidator().validate_attach(
                parent_package=package,
                parent_manifest_digest=str(package.manifest.get("package_digest") or ""),
                child_run=run,
                child_production=production,
                child_plan=child_store.load_plan_model(run_id),
            )
            if mismatches:
                detail = mismatches[0]
                raise ExecutionPackageError(
                    f"explicit upstream {dep_unit_id!r} lineage mismatch on "
                    f"{detail.field}: expected {detail.expected}, got {detail.actual}",
                    code="sub_tdp_upstream_invalid",
                )
            from top_down_planning.package.lineage import validate_accepted_child_delivery

            try:
                validate_accepted_child_delivery(
                    store=child_store,
                    child_run_id=run_id,
                    child_run=run,
                    child_production=production,
                )
            except ValueError as exc:
                raise ExecutionPackageError(
                    f"explicit upstream {dep_unit_id!r} delivery invalid: {exc}",
                    code="sub_tdp_upstream_invalid",
                ) from exc
            return run, production

        if explicit_upstream_only:
            return None

        package_id = str(package.manifest.get("package_id") or "")
        package_digest = str(package.manifest.get("package_digest") or "")
        planning_run_id = str(
            (package.manifest.get("planning_run") or {}).get("run_id") or ""
        )
        parent_plan_digest = str(
            (package.manifest.get("parent") or {}).get("plan_digest") or ""
        )
        matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for run_dir in sorted(child_store.root.iterdir(), key=lambda p: p.name):
            if not run_dir.is_dir() or run_dir.name.startswith("."):
                continue
            try:
                run = child_store.load_run(run_dir.name)
            except (OSError, ValueError, KeyError):
                continue
            binding = run.get("package_binding") or {}
            if not isinstance(binding, dict):
                continue
            bound_unit = str(
                binding.get("selected_unit_id") or binding.get("unit_id") or ""
            )
            if bound_unit != dep_unit_id:
                continue
            if str(binding.get("package_id") or "") != package_id:
                continue
            if str(binding.get("package_digest") or "") != package_digest:
                continue
            if str(binding.get("planning_run_id") or "") != planning_run_id:
                continue
            if str(binding.get("parent_plan_digest") or "") != parent_plan_digest:
                continue
            if str(binding.get("unit_plan_digest") or "") != dep_unit.plan_digest:
                continue
            if (
                str(binding.get("assigned_subtree_digest") or "")
                != dep_unit.assigned_subtree_digest
            ):
                continue
            output_digest = str((run.get("digests") or {}).get("output") or "").strip()
            if not output_digest:
                continue
            if (
                str(run.get("status") or "") == "completed"
                and str(run.get("phase") or "") == OUTPUT_VALIDATED
                and str(run.get("outcome") or "") == "accepted"
            ):
                production = child_store.load_production(run_dir.name)
                # Recompute digest from production for integrity.
                from top_down_planning.persistence.digests import compute_output_digest

                recomputed = compute_output_digest(production)
                if recomputed != output_digest:
                    continue
                claim = production.get("completion_claim")
                if not isinstance(claim, dict) or claim.get("goal_met") is not True:
                    continue
                if not str(binding.get("whole_output_review_id") or "").strip():
                    continue
                if not str(binding.get("whole_output_review_digest") or "").strip():
                    continue
                from top_down_planning.package.lineage import (
                    validate_accepted_child_delivery,
                )

                try:
                    validate_accepted_child_delivery(
                        store=child_store,
                        child_run_id=run_dir.name,
                        child_run=run,
                        child_production=production,
                        verify_evidence=True,
                    )
                except ValueError:
                    continue
                matches.append((run, production))
        if len(matches) > 1:
            ids = ", ".join(str(m[0].get("id") or "") for m in matches)
            raise ExecutionPackageError(
                f"multiple accepted results for dependency {dep_unit_id!r}: {ids}; "
                "pass an explicit upstream run binding",
                code="sub_tdp_ambiguous_upstream",
            )
        return matches[0] if matches else None

    @staticmethod
    def _revalidate_terminal_child_delivery(
        child_store: FileRunStore,
        child_run_id: str,
        child_run: dict[str, Any],
    ) -> None:
        from top_down_planning.package.lineage import revalidate_terminal_child_delivery

        try:
            revalidate_terminal_child_delivery(
                store=child_store,
                child_run_id=child_run_id,
                child_run=child_run,
                verify_evidence=True,
            )
        except ValueError as exc:
            raise ExecutionPackageError(
                f"terminal child delivery invalid: {exc}",
                code="sub_tdp_lineage_mismatch",
            ) from exc

    @staticmethod
    def _is_terminal(child_run: dict[str, Any]) -> bool:
        return (
            str(child_run.get("status") or "") == "completed"
            and str(child_run.get("phase") or "") == OUTPUT_VALIDATED
            and str(child_run.get("outcome") or "") == "accepted"
        )


def continue_prepared_child(
    child_store: FileRunStore,
    child_run_id: str,
    *,
    create_provider: ProviderFactory,
    workspace: Path,
    observability: Any | None = None,
) -> PreparedChildResult:
    """Resume a prepared child run without creating a replacement."""

    return continue_child_sub_tdp(
        child_store,
        child_run_id,
        create_provider=create_provider,
        workspace=workspace,
        observability=observability,
    )


__all__ = ["PreparedChildResult", "PreparedUnitExecutor", "continue_prepared_child"]
