"""Sub-TDP orchestration state on parent production.json."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from top_down_planning.domain.sub_tdp_units import SubTdpUnit

_CHILD_OUTPUT_VALIDATED_PHASE = "output_validated"

ORCHESTRATION_STATUS_PREPARING = "preparing"
ORCHESTRATION_STATUS_RUNNING = "running"
ORCHESTRATION_STATUS_COMPLETED = "completed"
ORCHESTRATION_STATUS_FAILED = "failed"

UNIT_STATUS_PENDING = "pending"
UNIT_STATUS_RUNNING = "running"
UNIT_STATUS_PAUSED = "paused"
UNIT_STATUS_COMPLETED = "completed"
UNIT_STATUS_FAILED = "failed"


def _unit_record(unit: SubTdpUnit, *, package_unit: Any | None = None) -> dict[str, Any]:
    record = {
        "id": unit.plan_item_id,
        "plan_item_id": unit.plan_item_id,
        "title": unit.title,
        "directory": unit.directory,
        "ordinal": unit.ordinal,
        "status": UNIT_STATUS_PENDING,
        "child_run_id": None,
        "notes": [],
    }
    if package_unit is not None:
        record["unit_plan_digest"] = str(getattr(package_unit, "plan_digest", "") or "")
        record["assigned_subtree_digest"] = str(
            getattr(package_unit, "assigned_subtree_digest", "") or ""
        )
        record["depends_on"] = list(getattr(package_unit, "depends_on", None) or [])
    return record


def initial_sub_tdp_state(units: list[SubTdpUnit]) -> dict[str, Any]:
    return {
        "version": 2,
        "status": ORCHESTRATION_STATUS_PREPARING,
        "active_unit_id": None,
        "units": [_unit_record(unit) for unit in units],
    }


def initial_sub_tdp_state_from_package(
    package_manifest: dict[str, Any],
    *,
    manifest_path: str,
    units: list[SubTdpUnit],
    package_units: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = {
        "version": 2,
        "status": ORCHESTRATION_STATUS_PREPARING,
        "active_unit_id": None,
        "units": [
            _unit_record(
                unit,
                package_unit=(package_units or {}).get(unit.plan_item_id),
            )
            for unit in units
        ],
    }
    state["package_id"] = package_manifest.get("package_id")
    state["package_digest"] = package_manifest.get("package_digest")
    state["manifest_path"] = manifest_path
    return state


def load_sub_tdp_state(production: dict[str, Any]) -> dict[str, Any] | None:
    raw = production.get("sub_tdps")
    if not isinstance(raw, dict):
        return None
    return deepcopy(raw)


def merge_sub_tdp_state_into_production(
    production: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    merged = deepcopy(production)
    merged["sub_tdps"] = deepcopy(state)
    return merged


def find_unit(state: dict[str, Any], plan_item_id: str) -> dict[str, Any] | None:
    for unit in state.get("units") or []:
        if isinstance(unit, dict) and str(unit.get("plan_item_id") or "") == plan_item_id:
            return unit
    return None


def unit_dependencies_satisfied(
    state: dict[str, Any],
    package_units: dict[str, Any],
    unit_id: str,
) -> bool:
    """Return whether orchestration state shows all package dependencies completed."""

    from top_down_planning.package.lineage import verify_accepted_result_attestation

    loaded = package_units.get(unit_id)
    if loaded is None:
        raise ValueError(f"unknown unit in dependency check: {unit_id!r}")
    depends_on = list(getattr(loaded, "depends_on", None) or [])
    for dep_id in depends_on:
        dep_record = find_unit(state, dep_id)
        if dep_record is None:
            return False
        if str(dep_record.get("status") or "") != UNIT_STATUS_COMPLETED:
            return False
        try:
            verify_accepted_result_attestation(dep_record)
        except ValueError:
            return False
    return True


def next_ready_unit_id(
    state: dict[str, Any],
    package_units: dict[str, Any],
) -> str | None:
    """Select the next unit to run by ordinal among dependency-ready, non-completed units."""

    candidates = sorted(
        package_units.values(),
        key=lambda unit: int(getattr(unit, "ordinal", 0)),
    )
    for loaded in candidates:
        unit_id = str(getattr(loaded, "unit_id", "") or "")
        if not unit_id:
            continue
        record = find_unit(state, unit_id)
        if record is None:
            continue
        status = str(record.get("status") or UNIT_STATUS_PENDING)
        if status in {UNIT_STATUS_COMPLETED, UNIT_STATUS_FAILED}:
            continue
        if unit_dependencies_satisfied(state, package_units, unit_id):
            return unit_id
    return None


def sub_tdp_progress(state: dict[str, Any] | None) -> tuple[int, int, str | None]:
    """Return (completed_count, total_count, active_unit_id) for status display."""

    if not isinstance(state, dict):
        return 0, 0, None
    units = [unit for unit in state.get("units") or [] if isinstance(unit, dict)]
    completed = sum(
        1 for unit in units if str(unit.get("status") or "") == UNIT_STATUS_COMPLETED
    )
    active = str(state.get("active_unit_id") or "").strip() or None
    return completed, len(units), active


def unit_status_from_child_run(run: dict[str, Any]) -> str:
    status = str(run.get("status") or "")
    phase = str(run.get("phase") or "")
    outcome = str(run.get("outcome") or "")
    if (
        status == "completed"
        and phase == _CHILD_OUTPUT_VALIDATED_PHASE
        and outcome == "accepted"
    ):
        return UNIT_STATUS_COMPLETED
    if status == "completed" and phase == _CHILD_OUTPUT_VALIDATED_PHASE:
        # Completed output review without acceptance is a failed unit delivery.
        return UNIT_STATUS_FAILED
    if status == "paused":
        return UNIT_STATUS_PAUSED
    if status == "failed":
        return UNIT_STATUS_FAILED
    if status == "running":
        return UNIT_STATUS_RUNNING
    return UNIT_STATUS_PENDING


def export_state_yaml_payload(state: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(state)


def ensure_sub_tdp_state_matches_units(
    state: dict[str, Any],
    units: list[SubTdpUnit],
) -> None:
    expected_ids = {unit.plan_item_id for unit in units}
    actual_ids = {
        str(unit.get("plan_item_id") or "")
        for unit in state.get("units") or []
        if isinstance(unit, dict)
    }
    if expected_ids != actual_ids:
        missing = sorted(expected_ids - actual_ids)
        stale = sorted(actual_ids - expected_ids)
        detail = []
        if missing:
            detail.append(f"missing units: {', '.join(missing)}")
        if stale:
            detail.append(f"stale units: {', '.join(stale)}")
        raise ValueError(
            "sub_tdps orchestration state does not match approved plan units: "
            + "; ".join(detail)
        )


def all_units_completed(state: dict[str, Any], units: list[SubTdpUnit]) -> bool:
    from top_down_planning.package.lineage import verify_accepted_result_attestation

    unit_records = {
        str(unit.get("plan_item_id") or ""): unit
        for unit in state.get("units") or []
        if isinstance(unit, dict)
    }
    for unit in units:
        record = unit_records.get(unit.plan_item_id)
        if record is None:
            return False
        if str(record.get("status") or "") != UNIT_STATUS_COMPLETED:
            return False
        try:
            verify_accepted_result_attestation(record)
        except ValueError:
            return False
    return True


__all__ = [
    "ORCHESTRATION_STATUS_COMPLETED",
    "ORCHESTRATION_STATUS_FAILED",
    "ORCHESTRATION_STATUS_PREPARING",
    "ORCHESTRATION_STATUS_RUNNING",
    "UNIT_STATUS_COMPLETED",
    "UNIT_STATUS_FAILED",
    "UNIT_STATUS_PAUSED",
    "UNIT_STATUS_PENDING",
    "UNIT_STATUS_RUNNING",
    "export_state_yaml_payload",
    "find_unit",
    "initial_sub_tdp_state",
    "initial_sub_tdp_state_from_package",
    "load_sub_tdp_state",
    "merge_sub_tdp_state_into_production",
    "all_units_completed",
    "ensure_sub_tdp_state_matches_units",
    "next_ready_unit_id",
    "sub_tdp_progress",
    "unit_dependencies_satisfied",
    "unit_status_from_child_run",
]
