"""Atomic persistence for plan.yaml and run-state.json.

Adapted from tools/implement_todos/src/todos_tool/persistence.py.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from top_down_planning.errors import PersistenceError, ResumeError
from top_down_planning.models import (
    FinalStatus,
    PlanState,
    PlanningLimits,
    RunActiveStatus,
    RunState,
    SCHEMA_VERSION,
    SourceMetadata,
)


PLAN_FILENAME = "plan.yaml"
RUN_STATE_FILENAME = "run-state.json"
ITERATIONS_DIR = "iterations"


def plan_path(output_dir: Path) -> Path:
    return output_dir / PLAN_FILENAME


def run_state_path(output_dir: Path) -> Path:
    return output_dir / RUN_STATE_FILENAME


def iterations_dir(output_dir: Path) -> Path:
    return output_dir / ITERATIONS_DIR


def iteration_prefix(output_dir: Path, iteration: int) -> str:
    return str(iterations_dir(output_dir) / f"{iteration:03d}")


def load_plan(output_dir: Path) -> PlanState | None:
    path = plan_path(output_dir)
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return PlanState.model_validate(data)
    except (OSError, yaml.YAMLError, ValueError) as exc:
        raise PersistenceError(f"Failed to load plan from {path}: {exc}") from exc


def save_plan(output_dir: Path, plan: PlanState) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = plan.model_dump(mode="json")
    _atomic_write_yaml(plan_path(output_dir), payload)


def load_run_state(output_dir: Path) -> RunState | None:
    path = run_state_path(output_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return RunState.model_validate(data)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise PersistenceError(f"Failed to load run state from {path}: {exc}") from exc


def save_run_state(output_dir: Path, state: RunState) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    state.updated_at = datetime.now(timezone.utc)
    payload = state.model_dump(mode="json")
    _atomic_write_json(run_state_path(output_dir), payload)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, dict):
        data = payload
    else:
        data = {"value": payload}
    _atomic_write_json(path, data)


def append_ndjson(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, default=str) + "\n")


def new_run_state(
    *,
    input_file: str,
    output_goal: str,
    input_digest: str,
    output_goal_digest: str,
    limits: PlanningLimits,
) -> RunState:
    return RunState(
        input_file=input_file,
        output_goal=output_goal,
        input_digest=input_digest,
        output_goal_digest=output_goal_digest,
        limits=limits,
        active_status=RunActiveStatus.RUNNING,
    )


def ensure_resume_compatible(
    output_dir: Path,
    *,
    input_digest: str,
    output_goal_digest: str,
    limits: PlanningLimits,
    resume: bool,
) -> tuple[PlanState | None, RunState | None]:
    existing_plan = load_plan(output_dir)
    existing_run = load_run_state(output_dir)

    if existing_plan or existing_run:
        if not resume:
            raise ResumeError(
                f"Output directory already contains planning state: {output_dir}. "
                "Pass --resume to continue or choose a different --output path."
            )
        if existing_run is None:
            raise ResumeError(
                f"Cannot resume: {RUN_STATE_FILENAME} missing in {output_dir}"
            )
        if existing_plan is None:
            raise ResumeError(
                f"Cannot resume: {PLAN_FILENAME} missing in {output_dir}"
            )
        if existing_run.input_digest != input_digest:
            raise ResumeError(
                "Input digest mismatch: the input file changed since the last run"
            )
        if existing_run.output_goal_digest != output_goal_digest:
            raise ResumeError(
                "Output goal digest mismatch: --output-goal changed since the last run"
            )
        if existing_run.schema_version != SCHEMA_VERSION:
            raise ResumeError(
                f"Incompatible run-state schema version: {existing_run.schema_version}"
            )
        if existing_plan.schema_version != SCHEMA_VERSION:
            raise ResumeError(
                f"Incompatible plan schema version: {existing_plan.schema_version}"
            )
        _assert_limits_compatible(existing_run.limits, limits)
        return existing_plan, existing_run

    if resume:
        raise ResumeError(
            f"Cannot resume: no existing planning state found in {output_dir}"
        )
    return None, None


def _assert_limits_compatible(stored: PlanningLimits, requested: PlanningLimits) -> None:
    mismatches: list[str] = []
    for field in PlanningLimits.model_fields:
        stored_value = getattr(stored, field)
        requested_value = getattr(requested, field)
        if stored_value != requested_value:
            mismatches.append(
                f"{field}: stored={stored_value!r}, requested={requested_value!r}"
            )
    if mismatches:
        raise ResumeError(
            "Resume limits mismatch with stored run-state:\n"
            + "\n".join(f"  - {line}" for line in mismatches)
        )


def record_history(
    output_dir: Path,
    run_state: RunState,
    *,
    event: str,
    **extra: Any,
) -> None:
    entry: dict[str, Any] = {
        "event": event,
        "at": datetime.now(timezone.utc).isoformat(),
        "iteration": run_state.iteration,
        "retry_count": run_state.retry_count,
    }
    entry.update(extra)
    run_state.history.append(entry)
    save_run_state(output_dir, run_state)


def mark_last_success(output_dir: Path, run_state: RunState) -> None:
    run_state.last_successful_update = datetime.now(timezone.utc)
    run_state.last_error = None
    save_run_state(output_dir, run_state)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _atomic_write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def update_final_status(plan: PlanState, status: FinalStatus, summary: str | None) -> None:
    plan.result.status = status
    plan.result.summary = summary
