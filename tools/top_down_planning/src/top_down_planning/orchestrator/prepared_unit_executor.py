"""Shared direct and parent-driven prepared unit execution (proposal §12–13)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from top_down_planning.orchestrator.phases import OUTPUT_VALIDATED
from top_down_planning.orchestrator.prepared_run_factory import PreparedRunFactory
from top_down_planning.orchestrator.sub_tdp_child_driver import continue_child_sub_tdp
from top_down_planning.package.loader import ExecutionPackageError, LoadedExecutionPackage
from top_down_planning.persistence import FileRunStore

ProviderFactory = Callable[[dict[str, Any], Path], Any]


class PreparedUnitExecutor:
    """Execute one prepared unit through production and output review."""

    class DependencyUnmetError(ExecutionPackageError):
        def __init__(self, unit_id: str, dependency_id: str) -> None:
            super().__init__(
                f"unit {unit_id!r} blocked: unmet dependency {dependency_id!r}"
            )
            self.unit_id = unit_id
            self.dependency_id = dependency_id
            self.stop_code = "sub_tdp_dependency_unmet"

    def __init__(self, *, run_factory: PreparedRunFactory | None = None) -> None:
        self._run_factory = run_factory or PreparedRunFactory()

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
    ) -> dict[str, Any]:
        unit = package.units.get(unit_id)
        if unit is None:
            raise ExecutionPackageError(f"unknown unit: {unit_id!r}")

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
                ):
                    raise self.DependencyUnmetError(unit_id, dep_id)
        else:
            self._check_external_dependencies(package, unit_id, child_store)

        child_run_id = existing_child_run_id
        if child_run_id:
            child_run = child_store.load_run(child_run_id)
            if self._is_terminal(child_run):
                return child_run
        else:
            child_run_id = self._run_factory.create_child_run(
                child_store,
                package,
                unit,
                resolved_config=resolved_config,
                invocation=self._child_invocation(invocation, parent_run_id, unit_id),
            )

        return continue_child_sub_tdp(
            child_store,
            child_run_id,
            create_provider=create_provider,
            workspace=workspace,
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

    def _check_external_dependencies(
        self,
        package: LoadedExecutionPackage,
        unit_id: str,
        child_store: FileRunStore,
    ) -> None:
        unit = package.units[unit_id]
        for dep_id in unit.depends_on:
            if dep_id not in package.units:
                raise ExecutionPackageError(
                    f"unit {unit_id} depends on unknown unit {dep_id!r}"
                )
            dep_accepted = self._dependency_accepted(child_store, dep_id)
            if not dep_accepted:
                raise self.DependencyUnmetError(unit_id, dep_id)

    @staticmethod
    def _dependency_accepted(child_store: FileRunStore, dep_unit_id: str) -> bool:
        for run_dir in child_store.root.iterdir():
            if not run_dir.is_dir() or run_dir.name.startswith("."):
                continue
            try:
                run = child_store.load_run(run_dir.name)
            except Exception:
                continue
            binding = run.get("package_binding") or {}
            if not isinstance(binding, dict):
                continue
            bound_unit = str(
                binding.get("selected_unit_id") or binding.get("unit_id") or ""
            )
            if bound_unit != dep_unit_id:
                continue
            if (
                str(run.get("status") or "") == "completed"
                and str(run.get("phase") or "") == OUTPUT_VALIDATED
            ):
                return True
        return False

    @staticmethod
    def _is_terminal(child_run: dict[str, Any]) -> bool:
        return (
            str(child_run.get("status") or "") == "completed"
            and str(child_run.get("phase") or "") == OUTPUT_VALIDATED
        )


def continue_prepared_child(
    child_store: FileRunStore,
    child_run_id: str,
    *,
    create_provider: ProviderFactory,
    workspace: Path,
) -> dict[str, Any]:
    """Resume a prepared child run without creating a replacement."""

    return continue_child_sub_tdp(
        child_store,
        child_run_id,
        create_provider=create_provider,
        workspace=workspace,
    )


__all__ = ["PreparedUnitExecutor", "continue_prepared_child"]
