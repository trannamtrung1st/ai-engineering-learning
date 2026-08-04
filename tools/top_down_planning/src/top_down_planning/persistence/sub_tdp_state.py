"""Sub-TDP orchestration state on parent production.json."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from core_tools.persistence import dump_yaml

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


def _unit_record(unit: SubTdpUnit) -> dict[str, Any]:
    return {
        "id": unit.plan_item_id,
        "plan_item_id": unit.plan_item_id,
        "title": unit.title,
        "directory": unit.directory,
        "status": UNIT_STATUS_PENDING,
        "child_run_id": None,
        "notes": [],
    }


def initial_sub_tdp_state(units: list[SubTdpUnit]) -> dict[str, Any]:
    return {
        "version": 1,
        "status": ORCHESTRATION_STATUS_PREPARING,
        "active_unit_id": None,
        "units": [_unit_record(unit) for unit in units],
    }


def load_sub_tdp_state(production: dict[str, Any]) -> dict[str, Any] | None:
    raw = production.get("sub_tdps")
    if not isinstance(raw, dict):
        return None
    return dict(raw)


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


def unit_status_from_child_run(run: dict[str, Any]) -> str:
    status = str(run.get("status") or "")
    phase = str(run.get("phase") or "")
    if status == "completed" and phase == _CHILD_OUTPUT_VALIDATED_PHASE:
        return UNIT_STATUS_COMPLETED
    if status == "paused":
        return UNIT_STATUS_PAUSED
    if status == "failed":
        return UNIT_STATUS_FAILED
    if status == "running":
        return UNIT_STATUS_RUNNING
    return UNIT_STATUS_PENDING


def export_state_yaml_payload(state: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(state)


def write_sub_tdp_state_yaml(
    workspace: Path,
    state_file: str | None,
    state: dict[str, Any],
) -> None:
    if not state_file:
        return
    path = workspace / state_file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        dump_yaml(export_state_yaml_payload(state)) + "\n",
        encoding="utf-8",
    )


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
    "load_sub_tdp_state",
    "merge_sub_tdp_state_into_production",
    "all_units_completed",
    "ensure_sub_tdp_state_matches_units",
    "write_sub_tdp_state_yaml",
    "unit_status_from_child_run",
]
