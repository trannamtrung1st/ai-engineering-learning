"""Load and verify execution packages (proposal §7–8)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from top_down_planning.domain.models import Plan
from top_down_planning.domain.unit_dependencies import (
    UnitDependencyCycleError,
    detect_unit_dependency_cycles,
)
from top_down_planning.package.digests import (
    assigned_subtree_digest,
    compute_package_digest,
    digest_plan_file,
)


class ExecutionPackageError(ValueError):
    """Package validation failure before execution may start."""

    def __init__(self, message: str, *, code: str = "package_invalid") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class LoadedUnit:
    unit_id: str
    ordinal: int
    title: str
    plan_file: Path
    plan_digest: str
    assigned_root_item_id: str
    assigned_item_ids: list[str]
    assigned_subtree_digest: str
    depends_on: list[str]
    plan: Plan
    external_prerequisites: list[dict[str, Any]] = field(default_factory=list)
    required_upstream_outputs: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class LoadedExecutionPackage:
    manifest_path: Path
    manifest: dict[str, Any]
    parent_plan: Plan
    units: dict[str, LoadedUnit]
    workspace_path: Path
    resolved_config: dict[str, Any]


def _contained_package_path(package_dir: Path, relative: str, *, label: str) -> Path:
    if not relative or relative.startswith("/") or Path(relative).is_absolute():
        raise ExecutionPackageError(
            f"{label} path must be package-relative, got {relative!r}",
            code="package_path_invalid",
        )
    candidate = (package_dir / relative).resolve()
    try:
        candidate.relative_to(package_dir)
    except ValueError as exc:
        raise ExecutionPackageError(
            f"{label} path escapes package directory: {relative!r}",
            code="package_path_escape",
        ) from exc
    return candidate


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ExecutionPackageError(
            f"invalid JSON in {path.name}: {exc}",
            code="package_json_invalid",
        ) from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise ExecutionPackageError(
            f"unreadable package file {path.name}: {exc}",
            code="package_json_invalid",
        ) from exc


def _require_mapping(value: Any, *, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ExecutionPackageError(
            f"{field} must be an object",
            code="package_field_invalid",
        )
    return value


def _require_list(value: Any, *, field: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ExecutionPackageError(
            f"{field} must be a list",
            code="package_field_invalid",
        )
    return value


def _require_package_int(value: Any, *, field: str) -> int:
    if type(value) is not int:
        raise ExecutionPackageError(
            f"{field} must be an integer",
            code="package_field_invalid",
        )
    return value


def load_package_context_snapshot_binding(
    package_dir: Path, context: dict[str, Any]
) -> dict[str, Any]:
    """Load and schema-validate the package snapshot binding file."""

    from core_tools.persistence import PersistenceError
    from top_down_planning.config.binding_validation import (
        validate_context_snapshot_binding,
    )
    from top_down_planning.config.context import (
        compute_context_snapshot_digest_from_payload,
    )

    binding_rel = str(context.get("context_snapshot_binding_file") or "").strip()
    if not binding_rel:
        raise ExecutionPackageError(
            "prepared package missing context_snapshot_binding_file",
            code="package_context_incomplete",
        )
    binding_path = _contained_package_path(
        package_dir, binding_rel, label="context snapshot binding"
    )
    if not binding_path.is_file():
        raise ExecutionPackageError(
            f"context_snapshot_binding file missing: {binding_rel}",
            code="package_context_incomplete",
        )
    stored_binding = _load_json(binding_path)
    try:
        validate_context_snapshot_binding(stored_binding)
    except PersistenceError as exc:
        raise ExecutionPackageError(
            str(exc),
            code="package_snapshot_binding_invalid",
        ) from exc
    if not isinstance(stored_binding, dict):
        raise ExecutionPackageError(
            "context_snapshot_binding must be an object",
            code="package_snapshot_binding_invalid",
        )
    expected_snapshot = str(context.get("context_snapshot_digest") or "")
    stored_digest = compute_context_snapshot_digest_from_payload(stored_binding)
    if not expected_snapshot:
        raise ExecutionPackageError(
            "prepared package missing context_snapshot_digest",
            code="package_context_incomplete",
        )
    if stored_digest != expected_snapshot:
        raise ExecutionPackageError(
            f"context_snapshot_binding digest mismatch: expected {expected_snapshot}, "
            f"got {stored_digest}",
            code="package_context_drift",
        )
    return stored_binding


class ExecutionPackageLoader:
    """Load manifest.json and verify digests before provider sessions."""

    def load_from_manifest(
        self,
        manifest_path: Path,
        *,
        verify_workspace: bool = True,
    ) -> LoadedExecutionPackage:
        """Load a package from an explicit ``manifest.json`` path."""

        resolved = manifest_path.resolve()
        if resolved.name != "manifest.json":
            raise ExecutionPackageError(
                f"manifest path must be manifest.json (got {resolved.name!r})",
                code="package_invalid",
            )
        if not resolved.is_file():
            raise ExecutionPackageError(
                f"manifest.json missing: {resolved}",
                code="package_invalid",
            )
        return self.load(resolved.parent, verify_workspace=verify_workspace)

    def load(
        self,
        package_dir: Path,
        *,
        verify_workspace: bool = True,
    ) -> LoadedExecutionPackage:
        package_dir = package_dir.resolve()
        manifest_path = package_dir / "manifest.json"
        if not manifest_path.is_file():
            raise ExecutionPackageError(f"manifest.json missing: {manifest_path}")

        manifest = _load_json(manifest_path)
        if not isinstance(manifest, dict):
            raise ExecutionPackageError("manifest.json must be an object")
        if _require_package_int(
            manifest.get("schema_version"), field="schema_version"
        ) != 1:
            raise ExecutionPackageError(
                "unsupported package schema_version",
                code="package_schema_unsupported",
            )
        from core_tools.persistence import PersistenceError
        from top_down_planning.persistence.path_ids import validate_store_id

        try:
            validate_store_id(
                str(manifest.get("package_id") or ""),
                label="package_id",
            )
        except PersistenceError as exc:
            raise ExecutionPackageError(
                str(exc),
                code="package_id_invalid",
            ) from exc

        workspace_info = _require_mapping(manifest.get("workspace"), field="workspace")
        workspace_path = Path(str(workspace_info.get("path") or "")).resolve()
        if verify_workspace and not workspace_path.is_dir():
            raise ExecutionPackageError(f"workspace path missing: {workspace_path}")

        parent_info = _require_mapping(manifest.get("parent"), field="parent")
        parent_plan_rel = str(parent_info.get("plan_file") or "")
        parent_plan_path = _contained_package_path(
            package_dir, parent_plan_rel, label="parent plan"
        )
        if not parent_plan_path.is_file():
            raise ExecutionPackageError(f"parent plan snapshot missing: {parent_plan_path}")
        parent_digest = digest_plan_file(parent_plan_path)
        expected_parent_digest = str(parent_info.get("plan_digest") or "")
        if parent_digest != expected_parent_digest:
            raise ExecutionPackageError(
                f"parent plan digest mismatch: expected {expected_parent_digest}, got {parent_digest}"
            )
        try:
            parent_plan = Plan.from_dict(_load_json(parent_plan_path))
        except (TypeError, ValueError, KeyError) as exc:
            raise ExecutionPackageError(
                f"parent plan deserialization failed: {exc}",
                code="package_plan_invalid",
            ) from exc

        units: dict[str, LoadedUnit] = {}
        unit_plan_digests: list[str] = []
        seen_ordinals: set[int] = set()
        seen_plan_files: set[str] = set()
        unit_deps: dict[str, list[str]] = {}

        for raw_unit in _require_list(manifest.get("units"), field="units"):
            if not isinstance(raw_unit, dict):
                raise ExecutionPackageError("each manifest unit must be an object")
            unit_id = str(raw_unit.get("unit_id") or "").strip()
            if not unit_id:
                raise ExecutionPackageError("unit_id must be non-empty")
            if unit_id in units:
                raise ExecutionPackageError(f"duplicate unit_id: {unit_id!r}")
            ordinal = _require_package_int(
                raw_unit.get("ordinal"), field=f"unit {unit_id} ordinal"
            )
            if ordinal in seen_ordinals:
                raise ExecutionPackageError(f"duplicate unit ordinal: {ordinal}")
            seen_ordinals.add(ordinal)

            plan_rel = str(raw_unit.get("plan_file") or "")
            if plan_rel in seen_plan_files:
                raise ExecutionPackageError(f"duplicate unit plan_file: {plan_rel!r}")
            seen_plan_files.add(plan_rel)
            unit_plan_path = _contained_package_path(
                package_dir, plan_rel, label=f"unit {unit_id} plan"
            )
            if not unit_plan_path.is_file():
                raise ExecutionPackageError(f"unit plan snapshot missing: {unit_plan_path}")
            unit_digest = digest_plan_file(unit_plan_path)
            expected_unit_digest = str(raw_unit.get("plan_digest") or "")
            if unit_digest != expected_unit_digest:
                raise ExecutionPackageError(f"unit {unit_id} plan digest mismatch")
            unit_plan_digests.append(unit_digest)
            assigned_ids = [
                str(item)
                for item in _require_list(
                    raw_unit.get("assigned_item_ids"),
                    field=f"unit {unit_id} assigned_item_ids",
                )
            ]
            try:
                unit_plan = Plan.from_dict(_load_json(unit_plan_path))
            except (TypeError, ValueError, KeyError) as exc:
                raise ExecutionPackageError(
                    f"unit {unit_id} plan deserialization failed: {exc}",
                    code="package_plan_invalid",
                ) from exc
            active_unit_ids = {
                item_id for item_id in unit_plan.items if item_id != "item-root"
            }
            assigned_set = set(assigned_ids)
            if assigned_set != active_unit_ids:
                raise ExecutionPackageError(
                    f"unit {unit_id} assigned_item_ids do not equal snapshot inventory"
                )
            assigned_root = str(raw_unit.get("assigned_root_item_id") or unit_id)
            if assigned_root != unit_id:
                raise ExecutionPackageError(
                    f"unit {unit_id} assigned_root_item_id mismatch"
                )
            expected_subtree = str(raw_unit.get("assigned_subtree_digest") or "").strip()
            actual_subtree = assigned_subtree_digest(parent_plan, unit_id)
            if not expected_subtree:
                raise ExecutionPackageError(
                    f"unit {unit_id} assigned_subtree_digest is required",
                    code="package_subtree_digest_missing",
                )
            if expected_subtree != actual_subtree:
                raise ExecutionPackageError(
                    f"unit {unit_id} assigned_subtree_digest mismatch"
                )

            depends_on = [
                str(dep)
                for dep in _require_list(
                    raw_unit.get("depends_on"),
                    field=f"unit {unit_id} depends_on",
                )
            ]
            if unit_id in depends_on:
                raise ExecutionPackageError(f"unit {unit_id} has self-dependency")
            unit_deps[unit_id] = depends_on
            units[unit_id] = LoadedUnit(
                unit_id=unit_id,
                ordinal=ordinal,
                title=str(raw_unit.get("title") or ""),
                plan_file=unit_plan_path,
                plan_digest=unit_digest,
                assigned_root_item_id=assigned_root,
                assigned_item_ids=assigned_ids,
                assigned_subtree_digest=expected_subtree,
                depends_on=depends_on,
                plan=unit_plan,
                external_prerequisites=_require_list(
                    raw_unit.get("external_prerequisites"),
                    field=f"unit {unit_id} external_prerequisites",
                ),
                required_upstream_outputs=_require_list(
                    raw_unit.get("required_upstream_outputs"),
                    field=f"unit {unit_id} required_upstream_outputs",
                ),
            )

        for unit_id, deps in unit_deps.items():
            for dep_id in deps:
                if dep_id not in units:
                    raise ExecutionPackageError(
                        f"unit {unit_id} depends on unknown unit {dep_id!r}"
                    )
        try:
            detect_unit_dependency_cycles(unit_deps)
        except UnitDependencyCycleError as exc:
            raise ExecutionPackageError(str(exc), code="package_unit_cycle") from exc

        resolved_config: dict[str, Any] | None = None
        execution_config = manifest.get("execution_config")
        if not isinstance(execution_config, dict):
            raise ExecutionPackageError(
                "manifest.execution_config is required",
                code="package_config_missing",
            )
        config_rel = str(execution_config.get("resolved_config_file") or "").strip()
        if not config_rel:
            raise ExecutionPackageError(
                "manifest.execution_config.resolved_config_file is required",
                code="package_config_missing",
            )
        config_path = _contained_package_path(
            package_dir, config_rel, label="execution config"
        )
        if not config_path.is_file():
            raise ExecutionPackageError(
                f"execution resolved_config missing: {config_path}",
                code="package_config_missing",
            )
        loaded_config = _load_json(config_path)
        if not isinstance(loaded_config, dict):
            raise ExecutionPackageError("execution resolved_config must be an object")
        from top_down_planning.config import ConfigError, validate_persisted_resolved_config

        try:
            validate_persisted_resolved_config(loaded_config)
        except ConfigError as exc:
            raise ExecutionPackageError(
                str(exc),
                code="package_config_invalid",
            ) from exc
        resolved_config = loaded_config

        planning_run = manifest.get("planning_run")
        if not isinstance(planning_run, dict):
            raise ExecutionPackageError("manifest.planning_run is required")
        if not isinstance(planning_run.get("inherited_plan_approval"), dict):
            raise ExecutionPackageError(
                "manifest.planning_run.inherited_plan_approval is required",
                code="package_approval_missing",
            )
        attestation = planning_run["inherited_plan_approval"]
        if not attestation.get("inherited_plan_approval"):
            raise ExecutionPackageError(
                "inherited_plan_approval attestation missing inherited marker",
                code="package_approval_invalid",
            )
        attestation_plan_digest = str(
            attestation.get("approved_plan_digest") or ""
        ).strip()
        if (
            attestation_plan_digest
            and attestation_plan_digest
            != str(planning_run.get("approved_plan_digest") or "").strip()
        ):
            raise ExecutionPackageError(
                "inherited_plan_approval.approved_plan_digest mismatch",
                code="package_approval_digest_mismatch",
            )
        approval_file = str(
            planning_run.get("inherited_plan_approval_file") or ""
        ).strip()
        if not approval_file:
            raise ExecutionPackageError(
                "planning_run.inherited_plan_approval_file is required",
                code="package_approval_missing",
            )
        approval_path = _contained_package_path(
            package_dir, approval_file, label="inherited plan approval"
        )
        if not approval_path.is_file():
            raise ExecutionPackageError(
                f"inherited plan approval file missing: {approval_path}",
                code="package_approval_missing",
            )
        file_attestation = _load_json(approval_path)
        if file_attestation != attestation:
            raise ExecutionPackageError(
                "inherited_plan_approval file does not match embedded attestation",
                code="package_approval_file_mismatch",
            )
        from top_down_planning.package.builder import digest_review_record

        whole_plan_review_digest = str(
            planning_run.get("whole_plan_review_digest") or ""
        ).strip()
        if not whole_plan_review_digest:
            raise ExecutionPackageError(
                "planning_run.whole_plan_review_digest is required",
                code="package_approval_digest_missing",
            )
        if digest_review_record(attestation) != whole_plan_review_digest:
            raise ExecutionPackageError(
                "inherited_plan_approval digest does not match whole_plan_review_digest",
                code="package_approval_digest_mismatch",
            )
        whole_plan_review_id = str(
            planning_run.get("whole_plan_review_id") or ""
        ).strip()
        source_review_id = str(attestation.get("source_review_id") or "").strip()
        if whole_plan_review_id and source_review_id != whole_plan_review_id:
            raise ExecutionPackageError(
                "inherited_plan_approval source_review_id mismatch",
                code="package_approval_id_mismatch",
            )
        approved_plan_revision = planning_run.get("approved_plan_revision")
        target_revision = attestation.get("target_revision")
        if (
            approved_plan_revision is not None
            and target_revision is not None
            and _require_package_int(
                target_revision, field="inherited_plan_approval.target_revision"
            )
            != _require_package_int(
                approved_plan_revision, field="planning_run.approved_plan_revision"
            )
        ):
            raise ExecutionPackageError(
                "inherited_plan_approval target_revision mismatch",
                code="package_approval_revision_mismatch",
            )

        context = manifest.get("context")
        if not isinstance(context, dict):
            raise ExecutionPackageError("manifest.context is required")
        load_package_context_snapshot_binding(package_dir, context)
        input_refs = context.get("input_refs")
        if not isinstance(input_refs, dict) or not isinstance(
            input_refs.get("refs"), list
        ):
            raise ExecutionPackageError(
                "manifest.context.input_refs must be "
                "{aggregate_digest, refs:[...]}",
                code="package_input_refs_invalid",
            )

        approved_digests = attestation.get("approved_digests")
        if not isinstance(approved_digests, dict):
            raise ExecutionPackageError(
                "inherited_plan_approval.approved_digests is required",
                code="package_approval_digest_missing",
            )
        from top_down_planning.domain.approval_digests import PLAN_APPROVAL_DIGEST_KEYS

        manifest_digest_map = {
            "plan": str(planning_run.get("approved_plan_digest") or "").strip(),
            "input": str(input_refs.get("aggregate_digest") or "").strip(),
            "output_goal": str(context.get("output_goal_digest") or "").strip(),
            "config_contract": str(
                context.get("config_contract_digest") or ""
            ).strip(),
            "context_spec": str(context.get("context_spec_digest") or "").strip(),
        }
        for key in PLAN_APPROVAL_DIGEST_KEYS:
            expected = manifest_digest_map.get(key) or ""
            if not expected:
                continue
            actual = str(approved_digests.get(key) or "").strip()
            if not actual:
                raise ExecutionPackageError(
                    f"inherited_plan_approval approved_digests.{key} is required",
                    code="package_approval_digest_missing",
                )
            if actual != expected:
                raise ExecutionPackageError(
                    f"inherited_plan_approval approved_digests.{key} does not "
                    f"match manifest context ({actual} != {expected})",
                    code="package_approval_digest_mismatch",
                )

        approved_plan_digest = str(planning_run.get("approved_plan_digest") or "").strip()
        if not approved_plan_digest:
            raise ExecutionPackageError(
                "planning_run.approved_plan_digest is required",
                code="package_approved_plan_digest_missing",
            )
        from top_down_planning.domain.plan_tree import is_active_item
        from top_down_planning.domain.sub_tdp_units import derive_sub_tdp_units
        from top_down_planning.domain.unit_dependencies import derive_unit_dependencies
        from top_down_planning.domain.unit_plan import (
            build_unit_plan_snapshot,
            collect_assigned_item_ids,
        )
        from top_down_planning.persistence.digests import compute_plan_digest

        semantic_parent_digest = compute_plan_digest(parent_plan)
        if approved_plan_digest != semantic_parent_digest:
            raise ExecutionPackageError(
                "planning_run.approved_plan_digest does not match parent plan digest",
                code="package_approved_plan_mismatch",
            )
        # Re-derive units from the approved parent plan and compare inventory.
        derived_units = derive_sub_tdp_units(parent_plan)
        derived_ids = {unit.plan_item_id for unit in derived_units}
        manifest_ids = set(units)
        if derived_ids != manifest_ids:
            raise ExecutionPackageError(
                "manifest units do not match units derived from approved parent plan",
                code="package_unit_inventory_mismatch",
            )
        derived_deps = derive_unit_dependencies(parent_plan, derived_units)
        package_id = str(manifest.get("package_id") or "")
        for derived in derived_units:
            loaded = units[derived.plan_item_id]
            if loaded.ordinal != derived.ordinal:
                raise ExecutionPackageError(
                    f"unit {derived.plan_item_id} ordinal mismatch with derived plan",
                    code="package_unit_ordinal_mismatch",
                )
            expected_deps = list(derived_deps.get(derived.plan_item_id) or [])
            if list(loaded.depends_on) != expected_deps:
                raise ExecutionPackageError(
                    f"unit {derived.plan_item_id} depends_on mismatch with derived plan",
                    code="package_unit_deps_mismatch",
                )
            expected_assigned = collect_assigned_item_ids(
                parent_plan, derived.plan_item_id
            )
            if list(loaded.assigned_item_ids) != expected_assigned:
                raise ExecutionPackageError(
                    f"unit {derived.plan_item_id} assigned_item_ids mismatch "
                    "with derived plan",
                    code="package_unit_assignment_mismatch",
                )
            rebuilt = build_unit_plan_snapshot(
                parent_plan,
                derived,
                package_id=package_id,
                all_units=derived_units,
            )
            rebuilt_digest = compute_plan_digest(rebuilt)
            loaded_semantic = compute_plan_digest(loaded.plan)
            if rebuilt_digest != loaded_semantic:
                raise ExecutionPackageError(
                    f"unit {derived.plan_item_id} plan does not match "
                    "rebuilt unit snapshot from approved parent plan",
                    code="package_unit_plan_mismatch",
                )
        from top_down_planning.domain.unit_dependencies import (
            external_prerequisites_for_unit,
        )

        contract_digests = {
            unit_id: unit.assigned_subtree_digest for unit_id, unit in units.items()
        }
        for derived in derived_units:
            loaded = units[derived.plan_item_id]
            expected_external = external_prerequisites_for_unit(
                parent_plan,
                derived,
                derived_units,
                owning_unit_contract_digests=contract_digests,
            )
            if list(loaded.external_prerequisites) != expected_external:
                raise ExecutionPackageError(
                    f"unit {derived.plan_item_id} external_prerequisites mismatch "
                    "with derived plan",
                    code="package_external_prereq_mismatch",
                )
        assigned: set[str] = set()
        for derived in derived_units:
            for item_id in collect_assigned_item_ids(parent_plan, derived.plan_item_id):
                if item_id in assigned:
                    raise ExecutionPackageError(
                        f"overlapping unit assignment for item {item_id!r}",
                        code="package_unit_overlap",
                    )
                assigned.add(item_id)
        for item_id, item in parent_plan.items.items():
            if item_id == "item-root" or not is_active_item(item):
                continue
            if item.kind == "work" and item_id not in assigned:
                raise ExecutionPackageError(
                    f"active work item {item_id!r} is not covered by any unit",
                    code="package_unit_coverage",
                )

        context_digests = {
            key: str(value)
            for key, value in context.items()
            if key.endswith("_digest") and value
        }
        expected_package_digest = compute_package_digest(
            manifest,
            parent_plan_digest=parent_digest,
            unit_plan_digests=unit_plan_digests,
            approved_plan_digest=approved_plan_digest,
            context_digests=context_digests,
        )
        actual_package_digest = str(manifest.get("package_digest") or "")
        if actual_package_digest != expected_package_digest:
            raise ExecutionPackageError("package_digest mismatch")

        return LoadedExecutionPackage(
            manifest_path=manifest_path,
            manifest=manifest,
            parent_plan=parent_plan,
            units=units,
            workspace_path=workspace_path,
            resolved_config=resolved_config,
        )


__all__ = [
    "ExecutionPackageError",
    "ExecutionPackageLoader",
    "LoadedExecutionPackage",
    "LoadedUnit",
    "load_package_context_snapshot_binding",
]
