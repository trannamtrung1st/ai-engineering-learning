"""Atomic persistence for plan.yaml and run-state.json."""

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
    PlanningState,
    RenderConfig,
    RenderState,
    ReviewState,
    ReviewStatus,
    RunActiveStatus,
    RunState,
    SCHEMA_VERSION,
    SessionStrategy,
    SourceMetadata,
)


PLAN_FILENAME = "plan.yaml"
PLANNING_STATE_FILENAME = "planning-state.yaml"
RUN_STATE_FILENAME = "run-state.json"
REVIEW_STATE_FILENAME = "review-state.json"
ITERATIONS_DIR = "iterations"
CONTEXT_DIR = "context"
REVIEWS_DIR = "reviews"
STATE_DIRNAME = ".planning-output"
RENDER_DIRNAME = "render"
RENDER_STATE_FILENAME = "render-state.json"


def state_dir(output_dir: Path) -> Path:
    return output_dir / STATE_DIRNAME


def plan_path(output_dir: Path) -> Path:
    return state_dir(output_dir) / PLAN_FILENAME


def planning_state_path(output_dir: Path) -> Path:
    return state_dir(output_dir) / PLANNING_STATE_FILENAME


def run_state_path(output_dir: Path) -> Path:
    return state_dir(output_dir) / RUN_STATE_FILENAME


def iterations_dir(output_dir: Path) -> Path:
    return state_dir(output_dir) / ITERATIONS_DIR


def iteration_prefix(output_dir: Path, iteration: int) -> str:
    return str(iterations_dir(output_dir) / f"{iteration:03d}")


def iteration_transaction_path(output_dir: Path, iteration: int) -> Path:
    prefix = Path(iteration_prefix(output_dir, iteration))
    return prefix.with_name(prefix.name + "-transaction.json")


def context_dir(output_dir: Path) -> Path:
    return state_dir(output_dir) / CONTEXT_DIR


def plan_overview_artifact_path(output_dir: Path, plan_digest: str) -> Path:
    return context_dir(output_dir) / f"plan-overview-{plan_digest}.md"


def iteration_context_path(output_dir: Path, iteration: int) -> Path:
    prefix = Path(iteration_prefix(output_dir, iteration))
    return prefix.with_name(prefix.name + "-context.md")


def iteration_request_path(output_dir: Path, iteration: int) -> Path:
    prefix = Path(iteration_prefix(output_dir, iteration))
    return prefix.with_name(prefix.name + "-request.json")


def reviews_dir(output_dir: Path) -> Path:
    return state_dir(output_dir) / REVIEWS_DIR


def review_state_path(output_dir: Path) -> Path:
    return state_dir(output_dir) / REVIEW_STATE_FILENAME


def load_review_state(output_dir: Path) -> ReviewState | None:
    path = review_state_path(output_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ReviewState.model_validate(data)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise PersistenceError(f"Failed to load review state from {path}: {exc}") from exc


def save_review_state(output_dir: Path, state: ReviewState) -> None:
    directory = state_dir(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / REVIEW_STATE_FILENAME
    state.updated_at = datetime.now(timezone.utc)
    _atomic_write_json(target, state.model_dump(mode="json"))


def new_review_state() -> ReviewState:
    return ReviewState()


def update_review_status(plan: PlanState, review_status: ReviewStatus) -> None:
    plan.result.review_status = review_status


def render_dir(output_dir: Path) -> Path:
    return state_dir(output_dir) / RENDER_DIRNAME


def render_state_path(output_dir: Path) -> Path:
    return render_dir(output_dir) / RENDER_STATE_FILENAME


def render_batches_dir(output_dir: Path) -> Path:
    return render_dir(output_dir) / "batches"


def batch_review_result_path(output_dir: Path, batch_index: int) -> Path:
    return render_batches_dir(output_dir) / f"{batch_index:03d}" / "review-result.json"


def render_reviews_dir(output_dir: Path) -> Path:
    return render_dir(output_dir) / "reviews"


def rendered_output_review_result_path(output_dir: Path) -> Path:
    return render_reviews_dir(output_dir) / "output-review-result.json"


def load_render_state(output_dir: Path) -> RenderState | None:
    path = render_state_path(output_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return RenderState.model_validate(data)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise PersistenceError(f"Failed to load render state from {path}: {exc}") from exc


def save_render_state(output_dir: Path, state: RenderState) -> None:
    directory = render_dir(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / RENDER_STATE_FILENAME
    state.updated_at = datetime.now(timezone.utc)
    _atomic_write_json(target, state.model_dump(mode="json"))


def new_render_state() -> RenderState:
    return RenderState()


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
    directory = state_dir(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / PLAN_FILENAME
    payload = plan.model_dump(mode="json")
    _atomic_write_yaml(target, payload)


def load_planning_state(output_dir: Path) -> PlanningState | None:
    path = planning_state_path(output_dir)
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return PlanningState.model_validate(data)
    except (OSError, yaml.YAMLError, ValueError) as exc:
        raise PersistenceError(f"Failed to load planning state from {path}: {exc}") from exc


def save_planning_state(output_dir: Path, state: PlanningState) -> None:
    directory = state_dir(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / PLANNING_STATE_FILENAME
    payload = state.model_dump(mode="json")
    _atomic_write_yaml(target, payload)


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
    directory = state_dir(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / RUN_STATE_FILENAME
    state.updated_at = datetime.now(timezone.utc)
    payload = state.model_dump(mode="json")
    _atomic_write_json(target, payload)


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
    render: RenderConfig | None = None,
    stop_hint_digest: str | None = None,
    planning_model: str | None = None,
    review_model: str | None = None,
    rendering_model: str | None = None,
) -> RunState:
    return RunState(
        input_file=input_file,
        output_goal=output_goal,
        input_digest=input_digest,
        output_goal_digest=output_goal_digest,
        stop_hint_digest=stop_hint_digest,
        limits=limits,
        render=render or RenderConfig(),
        planning_model=planning_model,
        review_model=review_model,
        rendering_model=rendering_model,
        active_status=RunActiveStatus.RUNNING,
    )


def ensure_resume_compatible(
    output_dir: Path,
    *,
    input_digest: str,
    output_goal_digest: str,
    stop_hint_digest: str | None = None,
    limits: PlanningLimits,
    render: RenderConfig,
    resume: bool,
    session_strategy: SessionStrategy | None = None,
) -> tuple[PlanState | None, RunState | None]:
    existing_plan = load_plan(output_dir)
    existing_run = load_run_state(output_dir)

    if existing_plan or existing_run:
        if not resume:
            raise ResumeError(
                f"Output directory already contains planning state under "
                f"{STATE_DIRNAME}/. "
                "Pass --resume to continue or choose a different --output path."
            )
        if existing_run is None:
            raise ResumeError(
                f"Cannot resume: {RUN_STATE_FILENAME} missing under "
                f"{output_dir}/{STATE_DIRNAME}/"
            )
        if existing_plan is None:
            raise ResumeError(
                f"Cannot resume: {PLAN_FILENAME} missing under "
                f"{output_dir}/{STATE_DIRNAME}/"
            )
        if existing_run.input_digest != input_digest:
            raise ResumeError(
                "Input digest mismatch: the input file changed since the last run"
            )
        if existing_run.output_goal_digest != output_goal_digest:
            raise ResumeError(
                "Output goal digest mismatch: the output goal changed since the last run"
            )
        if existing_run.stop_hint_digest != stop_hint_digest:
            raise ResumeError(
                "Stop hint digest mismatch: the stop hint changed since the last run"
            )
        if existing_run.schema_version != SCHEMA_VERSION:
            raise ResumeError(
                f"Incompatible run-state schema version: {existing_run.schema_version}"
            )
        if existing_plan.schema_version != SCHEMA_VERSION:
            raise ResumeError(
                f"Incompatible plan schema version: {existing_plan.schema_version}"
            )
        _assert_run_config_compatible(
            existing_run.limits,
            existing_run.render,
            limits,
            render,
            existing_run.session_strategy,
            session_strategy,
        )
        return existing_plan, existing_run

    if resume:
        raise ResumeError(
            f"Cannot resume: no existing planning state found in {output_dir}"
        )
    return None, None


# Limits that may change on resume (e.g. after hitting max_iterations).
_RELAXABLE_LIMIT_FIELDS = frozenset(
    {
        "max_iterations",
        "max_depth",
        "max_children_per_expansion",
        "max_retries",
        "session_timeout_seconds",
        "parse_error_threshold",
    }
)

assert _RELAXABLE_LIMIT_FIELDS == frozenset(PlanningLimits.model_fields.keys()), (
    "PlanningLimits fields must all be classified for resume compatibility"
)


def resolve_resume_limits(
    stored_limits: PlanningLimits,
    requested_limits: PlanningLimits,
) -> PlanningLimits:
    """Validate resume limits and return the effective limits to use."""
    merged = stored_limits.model_copy()
    for field in _RELAXABLE_LIMIT_FIELDS:
        setattr(merged, field, getattr(requested_limits, field))
    return merged


def describe_resume_limit_changes(
    before: PlanningLimits,
    after: PlanningLimits,
) -> str:
    parts: list[str] = []
    for field in sorted(_RELAXABLE_LIMIT_FIELDS):
        before_value = getattr(before, field)
        after_value = getattr(after, field)
        if before_value != after_value:
            parts.append(f"{field} {before_value}->{after_value}")
    return ", ".join(parts)


def _assert_run_config_compatible(
    stored_limits: PlanningLimits,
    stored_render: RenderConfig,
    requested_limits: PlanningLimits,
    requested_render: RenderConfig,
    stored_strategy: SessionStrategy,
    requested_strategy: SessionStrategy | None,
) -> None:
    resolve_resume_limits(stored_limits, requested_limits)
    mismatches: list[str] = []
    for field in RenderConfig.model_fields:
        stored_value = getattr(stored_render, field)
        requested_value = getattr(requested_render, field)
        if stored_value != requested_value:
            mismatches.append(
                f"render.{field}: stored={stored_value!r}, requested={requested_value!r}"
            )
    if requested_strategy is not None and stored_strategy != requested_strategy:
        mismatches.append(
            "session_strategy changed since the last run; start a new output directory"
        )
    if mismatches:
        raise ResumeError(
            "Resume config mismatch with stored run-state:\n"
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
