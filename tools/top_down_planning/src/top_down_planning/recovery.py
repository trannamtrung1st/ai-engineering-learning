"""Detect and recover desynced planning state on resume."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from pydantic import ValidationError as PydanticValidationError

from top_down_planning.errors import PersistenceError
from top_down_planning.models import (
    AgentResponse,
    DecompositionStatus,
    PlanState,
    RunState,
)
from top_down_planning.persistence import load_plan, plan_path, state_dir
from top_down_planning.scheduler import initialize_root_plan
from top_down_planning.state_updates import apply_response

PLAN_BACKUP_FILENAME = "plan.yaml.bak"


def plan_looks_reset(plan: PlanState) -> bool:
    """Return True when plan.yaml matches a never-expanded root plan."""
    if len(plan.plan) != 1:
        return False
    root = plan.plan[0]
    return (
        root.id == "item-001"
        and root.parent_id is None
        and root.decomposition_status == DecompositionStatus.NEEDS_EXPANSION
    )


def run_state_expects_progress(run_state: RunState) -> bool:
    if run_state.iteration > 0:
        return True
    return any(
        entry.get("event") == "iteration_applied" for entry in run_state.history
    )


def is_plan_run_state_desynced(plan: PlanState, run_state: RunState) -> bool:
    """Detect stale plan.yaml paired with a run-state that already progressed."""
    return run_state_expects_progress(run_state) and plan_looks_reset(plan)


def _root_plan_from_source(plan: PlanState) -> PlanState:
    return initialize_root_plan(source=plan.source)


def list_iteration_response_paths(output_dir: Path) -> list[Path]:
    """Return iteration response audit files in order."""
    it_dir = state_dir(output_dir) / "iterations"
    if not it_dir.is_dir():
        return []

    chosen: dict[int, Path] = {}
    for path in it_dir.glob("*-response.json"):
        prefix = path.name.split("-", 1)[0]
        if prefix.isdigit():
            chosen[int(prefix)] = path
    return [chosen[key] for key in sorted(chosen)]


def _validation_path_for_response(response_path: Path) -> Path:
    stem = response_path.name[: -len("-response.json")]
    return response_path.with_name(f"{stem}-validation.json")


def _response_passed_validation(response_path: Path) -> bool:
    """Return False when validation audit is missing or records errors."""
    validation_path = _validation_path_for_response(response_path)
    if not validation_path.is_file():
        return False
    try:
        payload = json.loads(validation_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    errors = payload.get("errors")
    return not errors


def recover_plan_from_iterations(output_dir: Path, plan: PlanState) -> PlanState | None:
    """Replay applied iteration responses onto a fresh root plan."""
    response_paths = list_iteration_response_paths(output_dir)
    if not response_paths:
        return None

    recovered = _root_plan_from_source(plan)
    applied = 0
    for path in response_paths:
        if not _response_passed_validation(path):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            response = AgentResponse.model_validate(payload)
        except (OSError, json.JSONDecodeError, PydanticValidationError, ValueError):
            continue
        if not response.operations or not response.plan_digest:
            continue
        recovered = apply_response(recovered, response)
        applied += 1

    if applied == 0 or plan_looks_reset(recovered):
        return None
    return recovered


def backup_canonical_plan(output_dir: Path, *, suffix: str | None = None) -> Path:
    """Copy plan.yaml to a backup file before an agent-mode session."""
    source = plan_path(output_dir)
    if not source.is_file():
        raise PersistenceError(f"Cannot back up missing plan file: {source}")
    if suffix is None:
        backup_name = PLAN_BACKUP_FILENAME
    else:
        backup_name = f"{PLAN_BACKUP_FILENAME}.{suffix}"
    backup = state_dir(output_dir) / backup_name
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, backup)
    return backup


def restore_canonical_plan(output_dir: Path, backup: Path, *, min_items: int) -> bool:
    """Restore plan.yaml when an agent session corrupted or reset it."""
    if not backup.is_file():
        return False
    backup_plan = _load_plan_file(backup)
    if backup_plan is None:
        return False
    current = load_plan(output_dir)
    if current is not None:
        if len(current.plan) >= min_items and not plan_looks_reset(current):
            backup.unlink(missing_ok=True)
            return False
        if (
            plan_looks_reset(current)
            and plan_looks_reset(backup_plan)
            and len(current.plan) == len(backup_plan.plan)
        ):
            backup.unlink(missing_ok=True)
            return False
    target = plan_path(output_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup, target)
    backup.unlink(missing_ok=True)
    return True


def _load_plan_file(path: Path) -> PlanState | None:
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return PlanState.model_validate(data)
    except (OSError, yaml.YAMLError, ValueError, PydanticValidationError):
        return None
