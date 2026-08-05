"""Build immutable execution packages from approved planning runs (proposal §7–11)."""

from __future__ import annotations

import copy
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core_tools.persistence import atomic_write_json, digest_file
from core_tools.persistence.digests import digest_json

from top_down_planning.domain.models import Plan
from top_down_planning.domain.plan_tree import PLAN_ROOT_ITEM_ID, walk_active_tree
from top_down_planning.domain.reviews import find_whole_plan_approval
from top_down_planning.domain.sub_tdp_units import SubTdpUnit, derive_sub_tdp_units
from top_down_planning.domain.unit_dependencies import (
    UnitDependencyCycleError,
    derive_unit_dependencies,
    detect_unit_dependency_cycles,
    external_prerequisites_for_unit,
)
from top_down_planning.domain.unit_plan import build_unit_plan_snapshot, collect_assigned_item_ids
from top_down_planning.package.digests import (
    assigned_subtree_digest,
    compute_package_digest,
    digest_plan_file,
)
from top_down_planning.persistence.digests import compute_plan_digest
from top_down_planning.persistence.interface import RunStore
from top_down_planning.persistence.path_ids import validate_store_id


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_package_id(*, now: datetime | None = None) -> str:
    moment = now or datetime.now(UTC)
    suffix = uuid.uuid4().hex[:6]
    package_id = f"tdp-package-{moment.strftime('%Y%m%dT%H%M%S')}-{suffix}"
    return validate_store_id(package_id, label="package_id")


def digest_review_record(review: dict[str, Any]) -> str:
    """Canonical digest of an approval / review attestation artifact."""

    return digest_json(copy.deepcopy(review))


def build_input_ref_inventory(
    input_refs: list[str],
    *,
    workspace: Path,
    aggregate_digest: str,
) -> dict[str, Any]:
    refs: list[dict[str, Any]] = []
    for ref in input_refs:
        path = (workspace / ref).resolve()
        entry: dict[str, Any] = {"path": ref, "sha256": "", "size": 0}
        if path.is_file():
            entry["sha256"] = digest_file(path)
            entry["size"] = path.stat().st_size
        refs.append(entry)
    return {
        "aggregate_digest": aggregate_digest,
        "refs": refs,
    }


def inherited_plan_approval_attestation(
    approval: dict[str, Any],
    *,
    planning_run_id: str,
    approved_plan_digest: str,
) -> dict[str, Any]:
    """Immutable approval attestation copied from the planning whole-plan review."""

    attestation = copy.deepcopy(approval)
    attestation["plan_source"] = "prepared_package"
    attestation["plan_review_inherited"] = True
    attestation["inherited_plan_approval"] = True
    attestation["source_planning_run_id"] = planning_run_id
    attestation["source_review_id"] = str(approval.get("id") or "")
    attestation["approved_plan_digest"] = approved_plan_digest
    # Do not pretend a child reviewer session owned this approval.
    attestation.pop("reviewer_binding", None)
    return attestation


@dataclass(frozen=True)
class BuiltExecutionPackage:
    package_id: str
    manifest_path: Path
    manifest: dict[str, Any]


class ExecutionPackageBuilder:
    """Derive units, snapshots, digests, and manifest.json atomically."""

    def build_from_planning_run(
        self,
        store: RunStore,
        planning_run_id: str,
        *,
        output_dir: Path,
        replace: bool = False,
    ) -> BuiltExecutionPackage:
        run = store.load_run(planning_run_id)
        plan = store.load_plan_model(planning_run_id)
        config = store.load_resolved_config(planning_run_id)
        reviews = store.list_reviews(planning_run_id)
        approval = find_whole_plan_approval(reviews, plan.revision)
        if approval is None:
            raise ValueError("whole plan must be approved before package materialization")

        units = derive_sub_tdp_units(plan)
        self._validate_unit_coverage(plan, units)
        unit_deps = derive_unit_dependencies(plan, units)
        try:
            detect_unit_dependency_cycles(unit_deps)
        except UnitDependencyCycleError as exc:
            raise ValueError(str(exc)) from exc

        output_dir = output_dir.resolve()
        if output_dir.exists() and not replace:
            raise ValueError(
                f"execution package output already exists: {output_dir}; "
                "pass replace=True to overwrite"
            )

        staging = output_dir.parent / f".staging-{output_dir.name}-{uuid.uuid4().hex[:8]}"
        backup: Path | None = None
        try:
            if staging.exists():
                shutil.rmtree(staging)
            staging.mkdir(parents=True)

            built = self._materialize_into(
                staging,
                store=store,
                planning_run_id=planning_run_id,
                run=run,
                plan=plan,
                config=config,
                approval=approval,
                units=units,
                unit_deps=unit_deps,
            )

            from top_down_planning.package.loader import ExecutionPackageLoader

            ExecutionPackageLoader().load(staging, verify_workspace=False)

            if output_dir.exists():
                backup = output_dir.parent / f".backup-{output_dir.name}-{uuid.uuid4().hex[:8]}"
                output_dir.rename(backup)
            staging.rename(output_dir)
            if backup is not None and backup.exists():
                shutil.rmtree(backup)
            return BuiltExecutionPackage(
                package_id=built.package_id,
                manifest_path=output_dir / "manifest.json",
                manifest=built.manifest,
            )
        except Exception:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            if backup is not None and backup.exists() and not output_dir.exists():
                backup.rename(output_dir)
            raise

    def _materialize_into(
        self,
        staging: Path,
        *,
        store: RunStore,
        planning_run_id: str,
        run: dict[str, Any],
        plan: Plan,
        config: dict[str, Any],
        approval: dict[str, Any],
        units: list[SubTdpUnit],
        unit_deps: dict[str, list[str]],
    ) -> BuiltExecutionPackage:
        parent_plan_path = staging / "parent" / "plan.json"
        parent_plan_path.parent.mkdir(parents=True)
        atomic_write_json(parent_plan_path, plan.to_dict())
        parent_digest = digest_plan_file(parent_plan_path)

        digests = dict(run.get("digests") or {})
        approved_plan_digest = str(digests.get("plan") or compute_plan_digest(plan))
        workspace = Path(str(run.get("workspace") or "")).resolve()
        input_refs = list((config.get("run") or {}).get("input_refs") or [])
        input_inventory = build_input_ref_inventory(
            input_refs,
            workspace=workspace,
            aggregate_digest=str(digests.get("input") or ""),
        )

        package_id = new_package_id()
        attestation = inherited_plan_approval_attestation(
            approval,
            planning_run_id=planning_run_id,
            approved_plan_digest=approved_plan_digest,
        )
        review_digest = digest_review_record(attestation)

        approval_path = staging / "parent" / "inherited_plan_approval.json"
        atomic_write_json(approval_path, attestation)

        execution_config_dir = staging / "execution"
        execution_config_dir.mkdir(parents=True)
        atomic_write_json(execution_config_dir / "resolved_config.json", config)

        context_binding = run.get("context_snapshot_binding")
        if isinstance(context_binding, dict):
            atomic_write_json(
                execution_config_dir / "context_snapshot_binding.json",
                context_binding,
            )

        manifest_units: list[dict[str, Any]] = []
        unit_plan_digests: list[str] = []
        contract_digests = {
            unit.plan_item_id: assigned_subtree_digest(plan, unit.plan_item_id)
            for unit in units
        }
        for unit in units:
            unit_plan = build_unit_plan_snapshot(
                plan,
                unit,
                all_units=units,
                package_id=package_id,
            )
            unit_dir = staging / "units" / unit.directory
            unit_dir.mkdir(parents=True)
            unit_plan_path = unit_dir / "plan.json"
            atomic_write_json(unit_plan_path, unit_plan.to_dict())
            unit_digest = digest_plan_file(unit_plan_path)
            unit_plan_digests.append(unit_digest)
            assigned_ids = collect_assigned_item_ids(plan, unit.plan_item_id)
            external = external_prerequisites_for_unit(
                plan,
                unit,
                units,
                owning_unit_contract_digests=contract_digests,
            )
            depends_on = list(unit_deps.get(unit.plan_item_id) or [])
            required_upstream = [
                {
                    "owning_unit_id": entry["owning_unit_id"],
                    "dependency_item_id": entry["dependency_item_id"],
                    "upstream_contract_digest": entry["upstream_contract_digest"],
                }
                for entry in external
            ]
            manifest_units.append(
                {
                    "unit_id": unit.plan_item_id,
                    "ordinal": unit.ordinal,
                    "title": unit.title,
                    "plan_file": f"units/{unit.directory}/plan.json",
                    "plan_digest": unit_digest,
                    "assigned_root_item_id": unit.plan_item_id,
                    "assigned_item_ids": assigned_ids,
                    "assigned_subtree_digest": assigned_subtree_digest(
                        plan, unit.plan_item_id
                    ),
                    "depends_on": depends_on,
                    "external_prerequisites": external,
                    "required_upstream_outputs": required_upstream,
                    "execution_contract_digest": unit_digest,
                }
            )

        active_item_ids = [item_id for item_id, _, _ in walk_active_tree(plan).rows]
        manifest: dict[str, Any] = {
            "schema_version": 1,
            "package_id": package_id,
            "created_at": _utc_now(),
            "planning_run": {
                "run_id": planning_run_id,
                "approved_plan_revision": plan.revision,
                "approved_plan_digest": approved_plan_digest,
                "whole_plan_review_id": str(approval.get("id") or ""),
                "whole_plan_review_digest": review_digest,
                "inherited_plan_approval": attestation,
                "inherited_plan_approval_file": "parent/inherited_plan_approval.json",
            },
            "workspace": {
                "path": str(workspace),
                "portability": "workspace_bound",
            },
            "context": {
                "input_refs": input_inventory,
                "output_goal_digest": str(digests.get("output_goal") or ""),
                "config_contract_digest": str(digests.get("config_contract") or ""),
                "config_execution_digest": str(digests.get("config_execution") or ""),
                "context_spec_digest": str(digests.get("context_spec") or ""),
                "context_snapshot_digest": str(digests.get("context_snapshot") or ""),
                "context_snapshot_binding_file": (
                    "execution/context_snapshot_binding.json"
                    if isinstance(context_binding, dict)
                    else None
                ),
            },
            "execution_config": {
                "resolved_config_file": "execution/resolved_config.json",
            },
            "parent": {
                "plan_file": "parent/plan.json",
                "plan_digest": parent_digest,
                "output_goal": plan.output_goal,
                "active_item_ids": active_item_ids,
            },
            "units": manifest_units,
            "execution": {
                "unit_ordering": "dependency_then_ordinal",
                "nested_sub_tdps_allowed": False,
            },
        }
        context_digests = {
            key: str(value)
            for key, value in (manifest.get("context") or {}).items()
            if key.endswith("_digest") and value
        }
        manifest["package_digest"] = compute_package_digest(
            manifest,
            parent_plan_digest=parent_digest,
            unit_plan_digests=unit_plan_digests,
            approved_plan_digest=approved_plan_digest,
            context_digests=context_digests,
        )
        manifest_path = staging / "manifest.json"
        atomic_write_json(manifest_path, manifest)
        return BuiltExecutionPackage(
            package_id=package_id,
            manifest_path=manifest_path,
            manifest=manifest,
        )

    def _validate_unit_coverage(self, plan: Plan, units: list[SubTdpUnit]) -> None:
        assigned: set[str] = set()
        for unit in units:
            for item_id in collect_assigned_item_ids(plan, unit.plan_item_id):
                if item_id in assigned:
                    raise ValueError(f"active work item {item_id!r} assigned to multiple units")
                assigned.add(item_id)

        for item_id, _, _ in walk_active_tree(plan).rows:
            item = plan.items[item_id]
            if item.kind == "work" and item_id not in assigned:
                raise ValueError(
                    f"active work item {item_id!r} is not assigned to any unit"
                )
        if PLAN_ROOT_ITEM_ID in assigned:
            raise ValueError("plan root must not be assigned to a unit")


__all__ = [
    "BuiltExecutionPackage",
    "ExecutionPackageBuilder",
    "build_input_ref_inventory",
    "digest_review_record",
    "inherited_plan_approval_attestation",
    "new_package_id",
]
