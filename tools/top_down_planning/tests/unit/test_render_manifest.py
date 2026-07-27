from top_down_planning.digest import compute_plan_digest
from top_down_planning.input_loader import load_output_goal
from top_down_planning.models import DecompositionStatus, RenderConfig
from top_down_planning.render_manifest import build_render_manifest
from top_down_planning.render_scheduler import build_progressive_schedule
from tests.plan_factory import make_root_plan


def test_build_render_manifest_schedules_actionable_nodes() -> None:
    loaded_goal = load_output_goal(inline="Produce an actionable implementation plan")
    plan = make_root_plan(
        output_goal=loaded_goal.text,
        output_goal_digest=loaded_goal.digest,
    )
    plan.plan[0].decomposition_status = DecompositionStatus.ACTIONABLE
    manifest, errors = build_render_manifest(
        plan,
        run_id="run-test",
        plan_digest=compute_plan_digest(plan),
        output_goal_digest=loaded_goal.digest,
        render_config=RenderConfig(),
    )
    assert errors == []
    assert len(manifest.items) == 1
    assert manifest.items[0].plan_item_id == "item-001"
    assert manifest.items[0].wave == 0


def test_build_progressive_schedule_respects_render_dependencies() -> None:
    loaded_goal = load_output_goal(inline="goal")
    plan = make_root_plan(
        output_goal=loaded_goal.text,
        output_goal_digest=loaded_goal.digest,
    )
    plan.plan[0].decomposition_status = DecompositionStatus.ACTIONABLE
    child = plan.plan[0].model_copy(
        update={
            "id": "item-002",
            "parent_id": "item-001",
            "title": "Child",
            "depth": 1,
            "order": 2,
            "decomposition_status": DecompositionStatus.ACTIONABLE,
        }
    )
    plan.plan.append(child)
    items, errors = build_progressive_schedule(
        plan,
        render_config=RenderConfig(),
        render_dependencies={"item-002": ["item-001"]},
    )
    assert errors == []
    parent = next(item for item in items if item.plan_item_id == "item-001")
    child_item = next(item for item in items if item.plan_item_id == "item-002")
    assert parent.wave < child_item.wave
