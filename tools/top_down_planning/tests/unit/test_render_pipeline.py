"""Tests for per-node render manifest and render-only mode."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.digest import compute_plan_digest
from top_down_planning.errors import PlanningToolError
from top_down_planning.input_loader import load_output_goal
from top_down_planning.models import (
    DecompositionStatus,
    FinalStatus,
    PlanningLimits,
    RenderConfig,
    ReviewStatus,
)
from top_down_planning.orchestrator import Orchestrator, RunConfig
from top_down_planning.persistence import (
    final_confirmation_result_path,
    load_plan,
    new_run_state,
    save_plan,
    save_run_state,
    whole_plan_review_result_path,
    write_json,
)
from top_down_planning.render_manifest import build_render_manifest, compute_manifest_digest
from top_down_planning.render_preconditions import validate_render_only_preconditions
from tests.helpers import default_generation, render_output_goal
from tests.plan_factory import make_root_plan


def test_manifest_includes_actionable_nodes_once(tmp_path: Path, example_input: Path) -> None:
    loaded_goal = render_output_goal()
    plan = make_root_plan(
        output_goal=loaded_goal.text,
        output_goal_digest=loaded_goal.digest,
    )
    plan.plan[0].decomposition_status = DecompositionStatus.ACTIONABLE
    plan_digest = compute_plan_digest(plan)
    manifest, errors = build_render_manifest(
        plan,
        run_id="run-test",
        plan_digest=plan_digest,
        output_goal_digest=loaded_goal.digest,
        render_config=RenderConfig(),
    )
    assert errors == []
    assert len(manifest.items) == 1
    assert manifest.items[0].plan_item_id == "item-001"


def test_manifest_assigns_wave_ids_for_siblings(tmp_path: Path, example_input: Path) -> None:
    loaded_goal = load_output_goal(inline="Produce TODO folder.")
    plan = make_root_plan(output_goal=loaded_goal.text, output_goal_digest=loaded_goal.digest)
    plan.plan[0].decomposition_status = DecompositionStatus.ACTIONABLE
    for index, item_id in enumerate(("item-002", "item-003"), start=2):
        plan.plan.append(
            plan.plan[0].model_copy(
                update={
                    "id": item_id,
                    "parent_id": "item-001",
                    "title": f"Leaf {index}",
                    "depth": 1,
                    "order": index,
                    "decomposition_status": DecompositionStatus.ACTIONABLE,
                }
            )
        )
    plan_digest = compute_plan_digest(plan)
    manifest, errors = build_render_manifest(
        plan,
        run_id="run-test",
        plan_digest=plan_digest,
        output_goal_digest=loaded_goal.digest,
        render_config=RenderConfig(),
    )
    assert errors == []
    assert len(manifest.items) == 3
    assert all(item.assigned_wave_id for item in manifest.items)


def test_render_only_rejects_incomplete_plan(tmp_path: Path, example_input: Path) -> None:
    loaded_goal = load_output_goal(inline="goal")
    plan = make_root_plan(output_goal=loaded_goal.text, output_goal_digest=loaded_goal.digest)
    output_dir = tmp_path / "out"
    output_dir.mkdir(parents=True)
    save_plan(output_dir, plan)
    run_state = new_run_state(
        input_file=str(example_input),
        output_goal=loaded_goal.text,
        input_digest="in",
        output_goal_digest=loaded_goal.digest,
        limits=PlanningLimits(),
        generation=default_generation(),
    )
    save_run_state(output_dir, run_state)
    with pytest.raises(PlanningToolError):
        validate_render_only_preconditions(
            output_dir,
            output_goal=loaded_goal,
            goal_overridden=False,
        )


@pytest.mark.asyncio
async def test_render_only_with_confirmed_plan(
    tmp_path: Path,
    example_input: Path,
    fake_agent_bin: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_AGENT_RENDER_PRODUCE_NODE", "item-001")
    output_dir = tmp_path / "planning-output"
    loaded_goal = render_output_goal()
    plan = make_root_plan(
        input_file=str(example_input),
        output_goal=loaded_goal.text,
        input_digest="in",
        output_goal_digest=loaded_goal.digest,
    )
    plan.plan[0].decomposition_status = DecompositionStatus.ACTIONABLE
    plan.result.review_status = ReviewStatus.CONFIRMED
    plan.result.status = FinalStatus.COMPLETE
    save_plan(output_dir, plan)
    run_state = new_run_state(
        input_file=str(example_input),
        output_goal=loaded_goal.text,
        input_digest="in",
        output_goal_digest=loaded_goal.digest,
        limits=PlanningLimits(max_iterations=5),
        generation=default_generation(),
    )
    save_run_state(output_dir, run_state)
    write_json(
        whole_plan_review_result_path(output_dir),
        {
            "stage": "whole_plan_review",
            "plan_digest": compute_plan_digest(plan),
            "decision": "approve",
            "summary": "ok",
            "findings": [],
        },
    )
    write_json(
        final_confirmation_result_path(output_dir),
        {
            "stage": "final_confirmation",
            "plan_digest": compute_plan_digest(plan),
            "decision": "confirmed",
            "summary": "ok",
            "findings": [],
        },
    )
    config = RunConfig(
        input_path=example_input,
        output_goal=loaded_goal,
        output_dir=output_dir,
        workspace_root=tmp_path,
        limits=PlanningLimits(max_iterations=5),
        agent_bin=fake_agent_bin,
        skip_probe=True,
        render_only=True,
    )
    report = await Orchestrator(config).run()
    assert report.status == FinalStatus.COMPLETE
    manifest, _ = build_render_manifest(
        load_plan(output_dir),
        run_id="run-test",
        plan_digest=compute_plan_digest(load_plan(output_dir)),
        output_goal_digest=loaded_goal.digest,
        render_config=RenderConfig(),
    )
    assert compute_manifest_digest(manifest)
