"""Build immutable execution packages from approved planning runs (proposal §7–11)."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core_tools.persistence import atomic_write_json

from top_down_planning.domain.models import Plan
from top_down_planning.domain.plan_tree import PLAN_ROOT_ITEM_ID, walk_active_tree
from top_down_planning.domain.reviews import find_whole_plan_approval
from top_down_planning.domain.sub_tdp_units import SubTdpUnit, derive_sub_tdp_units
from top_down_planning.domain.unit_plan import build_unit_plan_snapshot, collect_assigned_item_ids
from top_down_planning.package.digests import (
    assigned_subtree_digest,
    compute_package_digest,
    digest_plan_file,
)
from top_down_planning.persistence.interface import RunStore
from top_down_planning.persistence.path_ids import validate_store_id


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_package_id(*, now: datetime | None = None) -> str:
    import uuid

    moment = now or datetime.now(UTC)
    suffix = uuid.uuid4().hex[:6]
    package_id = f"tdp-package-{moment.strftime('%Y%m%dT%H%M%S')}-{suffix}"
    return validate_store_id(package_id, label="package_id")


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

        output_dir = output_dir.resolve()
        if output_dir.exists():
            if not replace:
                raise ValueError(
                    f"execution package output already exists: {output_dir}; "
                    "pass replace=True to overwrite"
                )
            shutil.rmtree(output_dir)

        staging = output_dir.parent / f".staging-{output_dir.name}"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)

        parent_plan_path = staging / "parent" / "plan.json"
        parent_plan_path.parent.mkdir(parents=True)
        parent_plan_payload = plan.to_dict()
        atomic_write_json(parent_plan_path, parent_plan_payload)
        parent_digest = digest_plan_file(parent_plan_path)

        digests = dict(run.get("digests") or {})
        approved_plan_digest = str(digests.get("plan") or compute_plan_digest(plan))
        workspace = str(run.get("workspace") or "")
        input_refs = list((config.get("run") or {}).get("input_refs") or [])
        input_ref_entries = [
            {"path": ref, "digest": str(digests.get("input") or "")}
            for ref in input_refs
        ]

        manifest_units: list[dict[str, Any]] = []
        unit_plan_digests: list[str] = []
        prior_unit_id: str | None = None
        for unit in units:
            unit_plan = build_unit_plan_snapshot(plan, unit)
            unit_dir = staging / "units" / unit.directory
            unit_dir.mkdir(parents=True)
            unit_plan_path = unit_dir / "plan.json"
            atomic_write_json(unit_plan_path, unit_plan.to_dict())
            unit_digest = digest_plan_file(unit_plan_path)
            unit_plan_digests.append(unit_digest)
            assigned_ids = collect_assigned_item_ids(plan, unit.plan_item_id)
            depends_on = [prior_unit_id] if prior_unit_id is not None else []
            prior_unit_id = unit.plan_item_id
            manifest_units.append(
                {
                    "unit_id": unit.plan_item_id,
                    "ordinal": unit.ordinal,
                    "title": unit.title,
                    "plan_file": f"units/{unit.directory}/plan.json",
                    "plan_digest": unit_digest,
                    "assigned_root_item_id": unit.plan_item_id,
                    "assigned_item_ids": assigned_ids,
                    "assigned_subtree_digest": assigned_subtree_digest(plan, unit.plan_item_id),
                    "depends_on": depends_on,
                    "required_upstream_outputs": [],
                    "execution_contract_digest": unit_digest,
                }
            )

        active_item_ids = [item_id for item_id, _, _ in walk_active_tree(plan).rows]
        package_id = new_package_id()
        manifest: dict[str, Any] = {
            "schema_version": 1,
            "package_id": package_id,
            "created_at": _utc_now(),
            "planning_run": {
                "run_id": planning_run_id,
                "approved_plan_revision": plan.revision,
                "approved_plan_digest": approved_plan_digest,
                "whole_plan_review_id": str(approval.get("id") or ""),
                "whole_plan_review_digest": approved_plan_digest,
            },
            "workspace": {
                "path": workspace,
                "portability": "workspace_bound",
            },
            "context": {
                "input_refs": input_ref_entries,
                "output_goal_digest": str(digests.get("output_goal") or ""),
                "config_contract_digest": str(digests.get("config_contract") or ""),
                "config_execution_digest": str(digests.get("config_execution") or ""),
                "context_spec_digest": str(digests.get("context_spec") or ""),
                "context_snapshot_digest": str(digests.get("context_snapshot") or ""),
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

        from top_down_planning.package.loader import ExecutionPackageLoader

        ExecutionPackageLoader().load(staging, verify_workspace=False)
        staging.rename(output_dir)

        return BuiltExecutionPackage(
            package_id=package_id,
            manifest_path=output_dir / "manifest.json",
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


__all__ = ["BuiltExecutionPackage", "ExecutionPackageBuilder", "new_package_id"]
