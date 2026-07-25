"""Tests for batched render manifest, batching, and render-only mode."""

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
    RenderBatchStrategy,
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


def test_manifest_includes_actionable_leaves_once(tmp_path: Path, example_input: Path) -> None:
    loaded_goal = render_output_goal()
    plan = make_root_plan(
        output_goal=loaded_goal.text,
        output_goal_digest=loaded_goal.digest,
    )
    plan.plan[0].decomposition_status = DecompositionStatus.ACTIONABLE
    plan_digest = compute_plan_digest(plan)
    manifest = build_render_manifest(
        plan,
        plan_digest=plan_digest,
        output_goal_digest=loaded_goal.digest,
        output_goal_text=loaded_goal.text,
        render_config=RenderConfig(),
    )
    assert len(manifest.items) == 2
    intermediate = next(item for item in manifest.items if item.artifact_role == "intermediate")
    assert intermediate.artifact_key == "artifact-001"
    assert intermediate.relative_path.startswith("intermediates/")


def test_coherent_batching_groups_by_branch(tmp_path: Path, example_input: Path) -> None:
    multi_file_goal = """Produce TODO folder.

## Output artifacts

- `plans/demo/todos/INDEX.md`
- `plans/demo/todos/manifest.yaml`
"""
    loaded_goal = load_output_goal(inline=multi_file_goal)
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
    manifest = build_render_manifest(
        plan,
        plan_digest=plan_digest,
        output_goal_digest=loaded_goal.digest,
        output_goal_text=loaded_goal.text,
        render_config=RenderConfig(batch_strategy=RenderBatchStrategy.COHERENT, batch_size=5),
    )
    intermediate_batch_ids = [
        item.assigned_batch_id
        for item in manifest.items
        if item.artifact_role == "intermediate"
    ]
    assert len(set(intermediate_batch_ids)) == 1


def test_render_only_rejects_incomplete_plan(tmp_path: Path, example_input: Path) -> None:
    loaded_goal = load_output_goal(inline="goal")
    plan = make_root_plan(output_goal=loaded_goal.text, output_goal_digest=loaded_goal.digest)
    output_dir = tmp_path / "out"
    output_dir.mkdir(parents=True)
    save_plan(output_dir, plan)
    save_run_state(
        output_dir,
        new_run_state(
            input_file=str(example_input),
            output_goal=loaded_goal.source_label,
            input_digest="a" * 64,
            output_goal_digest=loaded_goal.digest,
            limits=PlanningLimits(),
            generation=default_generation(),
        ),
    )
    with pytest.raises(PlanningToolError, match="needs_expansion"):
        validate_render_only_preconditions(
            output_dir,
            output_goal=loaded_goal,
            goal_overridden=False,
        )


@pytest.mark.asyncio
async def test_render_only_does_not_modify_plan_yaml(
    tmp_path: Path,
    example_input: Path,
    fake_agent_bin: str,
) -> None:
    loaded_goal = render_output_goal()
    plan = make_root_plan(
        input_file=str(example_input),
        output_goal=loaded_goal.text,
        input_digest="a" * 64,
        output_goal_digest=loaded_goal.digest,
    )
    plan.plan[0].decomposition_status = DecompositionStatus.ACTIONABLE
    plan.result.status = FinalStatus.COMPLETE
    plan.result.review_status = ReviewStatus.CONFIRMED
    output_dir = tmp_path / "planning-output"
    output_dir.mkdir(parents=True, exist_ok=True)
    save_plan(output_dir, plan)
    plan_digest = compute_plan_digest(plan)
    save_run_state(
        output_dir,
        new_run_state(
            input_file=str(example_input),
            output_goal=loaded_goal.source_label,
            input_digest="a" * 64,
            output_goal_digest=loaded_goal.digest,
            limits=PlanningLimits(),
            generation=default_generation(),
            render=RenderConfig(final_review=False),
        ),
    )
    write_json(
        whole_plan_review_result_path(output_dir),
        {
            "stage": "whole_plan_review",
            "plan_digest": plan_digest,
            "decision": "approve",
            "summary": "ok",
            "findings": [],
        },
    )
    write_json(
        final_confirmation_result_path(output_dir),
        {
            "stage": "final_confirmation",
            "plan_digest": plan_digest,
            "decision": "confirmed",
            "summary": "ok",
            "findings": [],
        },
    )

    before = load_plan(output_dir)
    assert before is not None

    config = RunConfig(
        input_path=example_input,
        output_goal=loaded_goal,
        output_dir=output_dir,
        workspace_root=tmp_path,
        limits=PlanningLimits(),
        render=RenderConfig(final_review=False),
        render_only=True,
        agent_bin=fake_agent_bin,
        skip_probe=True,
    )
    await Orchestrator(config).run()
    after = load_plan(output_dir)
    assert after is not None
    assert after.model_dump() == before.model_dump()


def test_manifest_digest_is_deterministic(tmp_path: Path) -> None:
    loaded_goal = render_output_goal()
    plan = make_root_plan(output_goal=loaded_goal.text, output_goal_digest=loaded_goal.digest)
    plan.plan[0].decomposition_status = DecompositionStatus.ACTIONABLE
    plan_digest = compute_plan_digest(plan)
    first = build_render_manifest(
        plan,
        plan_digest=plan_digest,
        output_goal_digest=loaded_goal.digest,
        output_goal_text=loaded_goal.text,
        render_config=RenderConfig(),
    )
    second = build_render_manifest(
        plan,
        plan_digest=plan_digest,
        output_goal_digest=loaded_goal.digest,
        output_goal_text=loaded_goal.text,
        render_config=RenderConfig(),
    )
    assert compute_manifest_digest(first) == compute_manifest_digest(second)
