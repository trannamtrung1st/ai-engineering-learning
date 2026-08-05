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
)
from top_down_planning.package.loader import ExecutionPackageError, LoadedExecutionPackage
from top_down_planning.persistence import FileRunStore

ProviderFactory = Callable[[dict[str, Any], Path], Any]
RuntimeFactory = Callable[[str], Any]


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
            self._check_external_dependencies(
                package,
                unit_id,
                child_store,
                explicit_upstream=explicit_upstream,
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
            return existing_child_run_id

        creation_key = self._child_creation_key(
            package=package,
            unit_id=unit_id,
            parent_run_id=parent_run_id,
        )
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
                return str(existing.get("id") or "")

        child_run_id = self._run_factory.create_child_run(
            child_store,
            package,
            unit,
            resolved_config=resolved_config,
            invocation=self._child_invocation(invocation, parent_run_id, unit_id),
        )
        upstream = self._collect_upstream_accepted_results(
            child_store,
            package=package,
            unit_id=unit_id,
            orchestration_state=orchestration_state,
            explicit_upstream=explicit_upstream,
        )
        self._bind_upstream_accepted_results(child_store, child_run_id, upstream)
        self._bind_external_prerequisites(
            child_store,
            child_run_id,
            package=package,
            unit_id=unit_id,
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
        parent = str(parent_run_id or "").strip() or "direct"
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
                continue
            # Adopt children created before creation_key was persisted.
            sub_tdp = (run.get("invocation") or {}).get("sub_tdp") or {}
            if not isinstance(sub_tdp, dict):
                continue
            package_digest = str(binding.get("package_digest") or "").strip()
            parent = str(sub_tdp.get("parent_run_id") or "").strip()
            unit = str(sub_tdp.get("unit_id") or "").strip()
            if (
                package_digest
                and parent
                and unit
                and f"{package_digest}:{parent}:{unit}" == creation_key
            ):
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
    ) -> None:
        unit = package.units[unit_id]
        for dep_id in unit.depends_on:
            if dep_id not in package.units:
                raise ExecutionPackageError(
                    f"unit {unit_id} depends on unknown unit {dep_id!r}"
                )
            dep_unit = package.units[dep_id]
            dep_accepted = self._find_accepted_dependency_run(
                child_store,
                package=package,
                dep_unit_id=dep_id,
                dep_unit=dep_unit,
                explicit_upstream=explicit_upstream,
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
    ) -> list[dict[str, Any]]:
        from top_down_planning.package.lineage import verify_accepted_result_attestation

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
                    entry = dict(accepted)
                    entry["upstream_contract_digest"] = dep_unit.assigned_subtree_digest
                    results.append(entry)
                    continue
                child_run_id = str(dep_record.get("child_run_id") or "").strip()
                if child_run_id:
                    child_run = child_store.load_run(child_run_id)
                    child_production = child_store.load_production(child_run_id)
                    entry = accepted_result_record(
                        child_run=child_run,
                        child_production=child_production,
                        unit_id=dep_id,
                        unit_plan_digest=dep_unit.plan_digest,
                        package_id=package_id,
                        package_digest=package_digest,
                        assigned_subtree_digest=dep_unit.assigned_subtree_digest,
                    )
                    entry["upstream_contract_digest"] = dep_unit.assigned_subtree_digest
                    results.append(entry)
                    continue
                raise self.DependencyUnmetError(unit_id, dep_id)
            matched = self._find_accepted_dependency_run(
                child_store,
                package=package,
                dep_unit_id=dep_id,
                dep_unit=dep_unit,
                explicit_upstream=explicit_upstream,
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
            entry["upstream_contract_digest"] = dep_unit.assigned_subtree_digest
            results.append(entry)
        return results

    @staticmethod
    def _bind_upstream_accepted_results(
        child_store: FileRunStore,
        child_run_id: str,
        upstream: list[dict[str, Any]],
    ) -> None:
        run = child_store.load_run(child_run_id)
        expected = int(run["revision"])
        binding = dict(run.get("package_binding") or {})
        binding["upstream_accepted_results"] = list(upstream)
        run["package_binding"] = binding
        run["revision"] = expected + 1
        child_store.save_run(child_run_id, run, expected)

    @staticmethod
    def _bind_external_prerequisites(
        child_store: FileRunStore,
        child_run_id: str,
        *,
        package: LoadedExecutionPackage,
        unit_id: str,
    ) -> None:
        unit = package.units[unit_id]
        external = list(unit.external_prerequisites)
        run = child_store.load_run(child_run_id)
        expected = int(run["revision"])
        binding = dict(run.get("package_binding") or {})
        binding["external_prerequisites"] = external
        for item in binding.get("upstream_accepted_results") or []:
            if not isinstance(item, dict):
                raise ExecutionPackageError(
                    "upstream_accepted_results entries must be objects",
                    code="sub_tdp_upstream_invalid",
                )
            if not str(item.get("upstream_contract_digest") or "").strip():
                dep_id = str(item.get("unit_id") or "")
                dep_unit = package.units.get(dep_id)
                if dep_unit is None:
                    raise ExecutionPackageError(
                        f"upstream accepted result missing contract for {dep_id!r}",
                        code="sub_tdp_upstream_invalid",
                    )
                item["upstream_contract_digest"] = dep_unit.assigned_subtree_digest
            if not str(item.get("output_digest") or "").strip():
                raise ExecutionPackageError(
                    "upstream accepted result missing output_digest",
                    code="sub_tdp_upstream_invalid",
                )
        run["package_binding"] = binding
        run["revision"] = expected + 1
        child_store.save_run(child_run_id, run, expected)

    @staticmethod
    def _find_accepted_dependency_run(
        child_store: FileRunStore,
        *,
        package: LoadedExecutionPackage,
        dep_unit_id: str,
        dep_unit,
        explicit_upstream: dict[str, str] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        if explicit_upstream is not None and dep_unit_id in explicit_upstream:
            run_id = str(explicit_upstream[dep_unit_id] or "").strip()
            if not run_id:
                return None
            run = child_store.load_run(run_id)
            production = child_store.load_production(run_id)
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
    def _dependency_accepted(
        child_store: FileRunStore,
        *,
        package: LoadedExecutionPackage,
        dep_unit_id: str,
        dep_unit,
    ) -> bool:
        return (
            PreparedUnitExecutor._find_accepted_dependency_run(
                child_store,
                package=package,
                dep_unit_id=dep_unit_id,
                dep_unit=dep_unit,
            )
            is not None
        )

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
