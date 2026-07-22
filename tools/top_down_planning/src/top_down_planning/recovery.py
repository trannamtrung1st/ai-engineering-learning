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
    """Return iteration audit files, preferring response JSON with transaction fallback."""
    it_dir = state_dir(output_dir) / "iterations"
    if not it_dir.is_dir():
        return []

    chosen: dict[int, Path] = {}
    for path in it_dir.glob("*-response.json"):
        prefix = path.name.split("-", 1)[0]
        if prefix.isdigit():
            chosen[int(prefix)] = path
    for path in it_dir.glob("*-transaction.json"):
        prefix = path.name.split("-", 1)[0]
        if prefix.isdigit():
            iteration = int(prefix)
            chosen.setdefault(iteration, path)
    return [chosen[key] for key in sorted(chosen)]


def recover_plan_from_iterations(output_dir: Path, plan: PlanState) -> PlanState | None:
    """Replay stored iteration responses onto a fresh root plan."""
    response_paths = list_iteration_response_paths(output_dir)
    if not response_paths:
        return None

    recovered = _root_plan_from_source(plan)
    applied = 0
    for path in response_paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            response = AgentResponse.model_validate(payload)
        except (OSError, json.JSONDecodeError, PydanticValidationError, ValueError):
            continue
        if not response.operations:
            continue
        recovered = apply_response(recovered, response)
        applied += 1

    if applied == 0 or plan_looks_reset(recovered):
        return None
    return recovered


def backup_canonical_plan(output_dir: Path) -> Path:
    """Copy plan.yaml to a backup file before an agent-mode session."""
    source = plan_path(output_dir)
    if not source.is_file():
        raise PersistenceError(f"Cannot back up missing plan file: {source}")
    backup = state_dir(output_dir) / PLAN_BACKUP_FILENAME
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, backup)
    return backup


def restore_canonical_plan(output_dir: Path, backup: Path, *, min_items: int) -> bool:
    """Restore plan.yaml when an agent session corrupted or reset it."""
    if not backup.is_file():
        return False
    current = load_plan(output_dir)
    if current is not None and len(current.plan) >= min_items:
        backup.unlink(missing_ok=True)
        return False
    target = plan_path(output_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup, target)
    backup.unlink(missing_ok=True)
    return True
