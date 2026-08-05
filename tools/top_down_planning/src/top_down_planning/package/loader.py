"""Load and verify execution packages (proposal §7–8)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from top_down_planning.domain.models import Plan
from top_down_planning.package.digests import (
    compute_package_digest,
    digest_manifest_content,
    digest_plan_file,
)


class ExecutionPackageError(ValueError):
    """Package validation failure before execution may start."""


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


@dataclass(frozen=True)
class LoadedExecutionPackage:
    manifest_path: Path
    manifest: dict[str, Any]
    parent_plan: Plan
    units: dict[str, LoadedUnit]
    workspace_path: Path


class ExecutionPackageLoader:
    """Load manifest.json and verify digests before provider sessions."""

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

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if int(manifest.get("schema_version") or 0) != 1:
            raise ExecutionPackageError("unsupported package schema_version")

        workspace_info = manifest.get("workspace") or {}
        workspace_path = Path(str(workspace_info.get("path") or "")).resolve()
        if verify_workspace and not workspace_path.is_dir():
            raise ExecutionPackageError(f"workspace path missing: {workspace_path}")

        parent_info = manifest.get("parent") or {}
        parent_plan_rel = str(parent_info.get("plan_file") or "")
        parent_plan_path = (package_dir / parent_plan_rel).resolve()
        if not parent_plan_path.is_file():
            raise ExecutionPackageError(f"parent plan snapshot missing: {parent_plan_path}")
        parent_digest = digest_plan_file(parent_plan_path)
        expected_parent_digest = str(parent_info.get("plan_digest") or "")
        if parent_digest != expected_parent_digest:
            raise ExecutionPackageError(
                f"parent plan digest mismatch: expected {expected_parent_digest}, got {parent_digest}"
            )
        parent_plan = Plan.from_dict(json.loads(parent_plan_path.read_text(encoding="utf-8")))

        units: dict[str, LoadedUnit] = {}
        unit_plan_digests: list[str] = []
        for raw_unit in manifest.get("units") or []:
            if not isinstance(raw_unit, dict):
                raise ExecutionPackageError("each manifest unit must be an object")
            unit_id = str(raw_unit.get("unit_id") or "")
            plan_rel = str(raw_unit.get("plan_file") or "")
            unit_plan_path = (package_dir / plan_rel).resolve()
            if not unit_plan_path.is_file():
                raise ExecutionPackageError(f"unit plan snapshot missing: {unit_plan_path}")
            unit_digest = digest_plan_file(unit_plan_path)
            expected_unit_digest = str(raw_unit.get("plan_digest") or "")
            if unit_digest != expected_unit_digest:
                raise ExecutionPackageError(
                    f"unit {unit_id} plan digest mismatch"
                )
            unit_plan_digests.append(unit_digest)
            assigned_ids = list(raw_unit.get("assigned_item_ids") or [])
            unit_plan = Plan.from_dict(json.loads(unit_plan_path.read_text(encoding="utf-8")))
            active_unit_ids = {
                item_id
                for item_id in unit_plan.items
                if item_id != "item-root"
            }
            if set(assigned_ids) - active_unit_ids:
                raise ExecutionPackageError(
                    f"unit {unit_id} assigned_item_ids do not match snapshot inventory"
                )
            units[unit_id] = LoadedUnit(
                unit_id=unit_id,
                ordinal=int(raw_unit.get("ordinal") or 0),
                title=str(raw_unit.get("title") or ""),
                plan_file=unit_plan_path,
                plan_digest=unit_digest,
                assigned_root_item_id=str(raw_unit.get("assigned_root_item_id") or unit_id),
                assigned_item_ids=assigned_ids,
                assigned_subtree_digest=str(raw_unit.get("assigned_subtree_digest") or ""),
                depends_on=list(raw_unit.get("depends_on") or []),
                plan=unit_plan,
            )

        planning_run = manifest.get("planning_run") or {}
        approved_plan_digest = str(planning_run.get("approved_plan_digest") or "")
        context = manifest.get("context") or {}
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
        )


__all__ = [
    "ExecutionPackageError",
    "ExecutionPackageLoader",
    "LoadedExecutionPackage",
    "LoadedUnit",
]
