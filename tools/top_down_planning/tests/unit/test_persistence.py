import json
from pathlib import Path

import pytest

from top_down_planning.errors import ResumeError
from top_down_planning.models import GenerationConfig, PlanningLimits, RenderConfig, RunState, WholePlanContextMode
from top_down_planning.persistence import (
    ensure_resume_compatible,
    resolve_resume_limits,
    save_run_state,
)
from tests.helpers import default_generation


def test_resume_rejects_generation_mismatch(tmp_path: Path) -> None:
    output_dir = tmp_path / "planning-output"
    output_dir.mkdir()
    state_dir = output_dir / ".planning-output"
    state_dir.mkdir()
    (state_dir / "plan.yaml").write_text(
        "\n".join(
            [
                "schema_version: 2",
                "source:",
                "  input_file: ./idea.md",
                "  output_goal: goal",
                "  input_digest: input-digest",
                "  output_goal_digest: goal-digest",
                "plan:",
                "  - id: item-001",
                "    title: Root",
                "    objective: Root objective",
                "    depth: 0",
                "    order: 1",
                "result:",
                "  status: planning",
            ]
        ),
        encoding="utf-8",
    )
    run_state = RunState(
        input_digest="input-digest",
        output_goal_digest="goal-digest",
        generation=GenerationConfig(whole_plan_context=WholePlanContextMode.HYBRID),
    )
    save_run_state(output_dir, run_state)

    with pytest.raises(ResumeError, match="generation.whole_plan_context"):
        ensure_resume_compatible(
            output_dir,
            input_digest="input-digest",
            output_goal_digest="goal-digest",
            limits=PlanningLimits(),
            generation=GenerationConfig(whole_plan_context=WholePlanContextMode.REFERENCED),
            render=RenderConfig(),
            resume=True,
        )


def test_resume_allows_increased_max_iterations(tmp_path: Path) -> None:
    output_dir = tmp_path / "planning-output"
    output_dir.mkdir()
    state_dir = output_dir / ".planning-output"
    state_dir.mkdir()
    (state_dir / "plan.yaml").write_text(
        "\n".join(
            [
                "schema_version: 2",
                "source:",
                "  input_file: ./idea.md",
                "  output_goal: goal",
                "  input_digest: input-digest",
                "  output_goal_digest: goal-digest",
                "plan:",
                "  - id: item-001",
                "    title: Root",
                "    objective: Root objective",
                "    depth: 0",
                "    order: 1",
                "result:",
                "  status: planning",
            ]
        ),
        encoding="utf-8",
    )
    run_state = RunState(
        input_digest="input-digest",
        output_goal_digest="goal-digest",
        limits=PlanningLimits(max_iterations=40),
        generation=default_generation(),
        iteration=40,
    )
    save_run_state(output_dir, run_state)

    plan, loaded = ensure_resume_compatible(
        output_dir,
        input_digest="input-digest",
        output_goal_digest="goal-digest",
        limits=PlanningLimits(max_iterations=80),
        generation=default_generation(),
        render=RenderConfig(),
        resume=True,
    )
    assert plan is not None
    assert loaded is not None

    resolved = resolve_resume_limits(
        loaded.limits,
        PlanningLimits(max_iterations=80),
    )
    assert resolved == PlanningLimits(max_iterations=80)


def test_resume_rejects_schema_version_one(tmp_path: Path) -> None:
    output_dir = tmp_path / "planning-output"
    output_dir.mkdir()
    state_dir = output_dir / ".planning-output"
    state_dir.mkdir()
    (state_dir / "plan.yaml").write_text(
        "\n".join(
            [
                "schema_version: 1",
                "source:",
                "  input_file: ./idea.md",
                "  output_goal: goal",
                "  input_digest: input-digest",
                "  output_goal_digest: goal-digest",
                "plan:",
                "  - id: item-001",
                "    title: Root",
                "    objective: Root objective",
                "    depth: 0",
                "    order: 1",
                "result:",
                "  status: planning",
            ]
        ),
        encoding="utf-8",
    )
    run_state = RunState(
        input_digest="input-digest",
        output_goal_digest="goal-digest",
        generation=default_generation(),
    )
    save_run_state(output_dir, run_state)

    with pytest.raises(ResumeError, match="Incompatible plan schema version: 1"):
        ensure_resume_compatible(
            output_dir,
            input_digest="input-digest",
            output_goal_digest="goal-digest",
            limits=PlanningLimits(),
            generation=default_generation(),
            render=RenderConfig(),
            resume=True,
        )
