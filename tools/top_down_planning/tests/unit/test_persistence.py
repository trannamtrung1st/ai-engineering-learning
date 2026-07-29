import json
from pathlib import Path

import pytest

from top_down_planning.errors import PersistenceError, ResumeError
from top_down_planning.models import PlanningLimits, RenderConfig, RunState
from top_down_planning.persistence import (
    ensure_resume_compatible,
    load_run_state,
    resolve_resume_limits,
    save_run_state,
)


def test_resume_rejects_render_mismatch(tmp_path: Path) -> None:
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
        render=RenderConfig(final_review=True),
    )
    save_run_state(output_dir, run_state)

    with pytest.raises(ResumeError, match="render.final_review"):
        ensure_resume_compatible(
            output_dir,
            input_digest="input-digest",
            output_goal_digest="goal-digest",
            limits=PlanningLimits(),
            render=RenderConfig(final_review=False),
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
        iteration=40,
    )
    save_run_state(output_dir, run_state)

    plan, loaded = ensure_resume_compatible(
        output_dir,
        input_digest="input-digest",
        output_goal_digest="goal-digest",
        limits=PlanningLimits(max_iterations=80),
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
    )
    save_run_state(output_dir, run_state)

    with pytest.raises(ResumeError, match="Incompatible plan schema version: 1"):
        ensure_resume_compatible(
            output_dir,
            input_digest="input-digest",
            output_goal_digest="goal-digest",
            limits=PlanningLimits(),
            render=RenderConfig(),
            resume=True,
        )


def test_load_run_state_rejects_obsolete_generation_field(tmp_path: Path) -> None:
    output_dir = tmp_path / "planning-output"
    state_dir = output_dir / ".planning-output"
    state_dir.mkdir(parents=True)
    (state_dir / "run-state.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "input_digest": "input-digest",
                "output_goal_digest": "goal-digest",
                "generation": {"whole_plan_context": "embedded"},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(PersistenceError, match="Failed to load run state"):
        load_run_state(output_dir)
