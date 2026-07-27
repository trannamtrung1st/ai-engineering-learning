import json
from pathlib import Path

import pytest

from top_down_planning.errors import ResumeError
from top_down_planning.models import GenerationConfig, PlanningLimits, RenderConfig, RunState
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
        generation=GenerationConfig(concurrent_batches=1),
    )
    save_run_state(output_dir, run_state)

    with pytest.raises(ResumeError, match="generation.concurrent_batches"):
        ensure_resume_compatible(
            output_dir,
            input_digest="input-digest",
            output_goal_digest="goal-digest",
            limits=PlanningLimits(),
            generation=GenerationConfig(concurrent_batches=3),
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


def test_resume_rejects_structural_limit_mismatch(tmp_path: Path) -> None:
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
        limits=PlanningLimits(max_depth=6),
        generation=default_generation(),
    )
    save_run_state(output_dir, run_state)

    with pytest.raises(ResumeError, match="limits.max_depth"):
        ensure_resume_compatible(
            output_dir,
            input_digest="input-digest",
            output_goal_digest="goal-digest",
            limits=PlanningLimits(max_depth=8),
            generation=default_generation(),
            render=RenderConfig(),
            resume=True,
        )


def test_resume_allows_increased_max_children_per_expansion(tmp_path: Path) -> None:
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
        limits=PlanningLimits(max_children_per_expansion=10),
        generation=default_generation(),
    )
    save_run_state(output_dir, run_state)

    plan, loaded = ensure_resume_compatible(
        output_dir,
        input_digest="input-digest",
        output_goal_digest="goal-digest",
        limits=PlanningLimits(max_children_per_expansion=15),
        generation=default_generation(),
        render=RenderConfig(),
        resume=True,
    )
    assert plan is not None
    assert loaded is not None

    resolved = resolve_resume_limits(
        loaded.limits,
        PlanningLimits(max_children_per_expansion=15),
    )
    assert resolved.max_children_per_expansion == 15


def test_resume_rejects_decreased_max_children_per_expansion(tmp_path: Path) -> None:
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
        limits=PlanningLimits(max_children_per_expansion=15),
        generation=default_generation(),
    )
    save_run_state(output_dir, run_state)

    with pytest.raises(ResumeError, match="limits.max_children_per_expansion"):
        ensure_resume_compatible(
            output_dir,
            input_digest="input-digest",
            output_goal_digest="goal-digest",
            limits=PlanningLimits(max_children_per_expansion=10),
            generation=default_generation(),
            render=RenderConfig(),
            resume=True,
        )
