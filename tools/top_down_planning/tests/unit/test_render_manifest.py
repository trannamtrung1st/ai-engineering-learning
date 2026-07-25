import pytest

from top_down_planning.digest import compute_plan_digest
from top_down_planning.errors import PlanningToolError
from top_down_planning.input_loader import load_output_goal
from top_down_planning.models import DecompositionStatus, RenderConfig
from top_down_planning.render_flow import _expand_rerender_batch_ids
from top_down_planning.render_manifest import FINAL_BATCH_ID, build_render_manifest, manifest_matches_output_goal
from tests.plan_factory import make_root_plan


def test_manifest_matches_output_goal_requires_final_items() -> None:
    goal = """# Goal

## Output artifacts

- `plans/demo/todos/INDEX.md`
- `plans/demo/todos/manifest.yaml`
"""
    loaded_goal = load_output_goal(inline=goal)
    plan = make_root_plan(
        output_goal=loaded_goal.text,
        output_goal_digest=loaded_goal.digest,
    )
    plan.plan[0].decomposition_status = DecompositionStatus.ACTIONABLE
    manifest = build_render_manifest(
        plan,
        plan_digest=compute_plan_digest(plan),
        output_goal_digest=loaded_goal.digest,
        output_goal_text=loaded_goal.text,
        render_config=RenderConfig(),
    )
    assert manifest_matches_output_goal(manifest, loaded_goal.text)

    stale_manifest = manifest.model_copy(
        update={
            "items": [
                item for item in manifest.items if item.artifact_role == "intermediate"
            ]
        }
    )
    assert not manifest_matches_output_goal(stale_manifest, loaded_goal.text)


def test_final_items_assigned_to_final_batch() -> None:
    goal = """# Goal

## Output artifacts

- `plans/demo/todos/INDEX.md`
"""
    loaded_goal = load_output_goal(inline=goal)
    plan = make_root_plan(
        output_goal=loaded_goal.text,
        output_goal_digest=loaded_goal.digest,
    )
    plan.plan[0].decomposition_status = DecompositionStatus.ACTIONABLE
    manifest = build_render_manifest(
        plan,
        plan_digest=compute_plan_digest(plan),
        output_goal_digest=loaded_goal.digest,
        output_goal_text=loaded_goal.text,
        render_config=RenderConfig(),
    )
    final_items = [item for item in manifest.items if item.artifact_role == "final"]
    assert len(final_items) == 1
    assert final_items[0].assigned_batch_id == FINAL_BATCH_ID
    assert final_items[0].relative_path == "plans/demo/todos/INDEX.md"


def test_manifest_matches_output_goal_rejects_stale_roles() -> None:
    goal = """# Goal

## Output artifacts

- `implementation-plan.md`
"""
    loaded_goal = load_output_goal(inline=goal)
    plan = make_root_plan(
        output_goal=loaded_goal.text,
        output_goal_digest=loaded_goal.digest,
    )
    plan.plan[0].decomposition_status = DecompositionStatus.ACTIONABLE
    manifest = build_render_manifest(
        plan,
        plan_digest=compute_plan_digest(plan),
        output_goal_digest=loaded_goal.digest,
        output_goal_text=loaded_goal.text,
        render_config=RenderConfig(),
    )
    stale = manifest.model_copy(
        update={
            "items": [
                item.model_copy(update={"artifact_role": "leaf"})
                for item in manifest.items
                if item.artifact_role == "intermediate"
            ]
            + [item for item in manifest.items if item.artifact_role == "final"]
        }
    )
    assert not manifest_matches_output_goal(stale, loaded_goal.text)


def test_build_render_manifest_rejects_directory_only_goal() -> None:
    goal = """# Goal

## Output artifacts

Deliver under:

- `plans/demo/todos/`
"""
    loaded_goal = load_output_goal(inline=goal)
    plan = make_root_plan(
        output_goal=loaded_goal.text,
        output_goal_digest=loaded_goal.digest,
    )
    plan.plan[0].decomposition_status = DecompositionStatus.ACTIONABLE
    with pytest.raises(PlanningToolError, match="at least one file path"):
        build_render_manifest(
            plan,
            plan_digest=compute_plan_digest(plan),
            output_goal_digest=loaded_goal.digest,
            output_goal_text=loaded_goal.text,
            render_config=RenderConfig(),
        )


def test_expand_rerender_batch_ids_includes_final_when_intermediate_affected() -> None:
    goal = """# Goal

## Output artifacts

- `implementation-plan.md`
"""
    loaded_goal = load_output_goal(inline=goal)
    plan = make_root_plan(
        output_goal=loaded_goal.text,
        output_goal_digest=loaded_goal.digest,
    )
    plan.plan[0].decomposition_status = DecompositionStatus.ACTIONABLE
    manifest = build_render_manifest(
        plan,
        plan_digest=compute_plan_digest(plan),
        output_goal_digest=loaded_goal.digest,
        output_goal_text=loaded_goal.text,
        render_config=RenderConfig(),
    )
    intermediate = next(
        item for item in manifest.items if item.artifact_role == "intermediate"
    )
    expanded = _expand_rerender_batch_ids({intermediate.assigned_batch_id}, manifest)
    assert FINAL_BATCH_ID in expanded

    final_only = _expand_rerender_batch_ids({FINAL_BATCH_ID}, manifest)
    assert final_only == {FINAL_BATCH_ID}
