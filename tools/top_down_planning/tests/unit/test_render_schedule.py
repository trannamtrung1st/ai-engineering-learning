from top_down_planning.digest import compute_plan_digest
from top_down_planning.input_loader import load_output_goal
from top_down_planning.models import DecompositionStatus, RenderConfig
from top_down_planning.render_schedule import build_render_schedule
from tests.plan_factory import make_root_plan


def test_build_render_schedule_schedules_actionable_leaves() -> None:
    loaded_goal = load_output_goal(inline="Produce an actionable implementation plan")
    plan = make_root_plan(
        output_goal=loaded_goal.text,
        output_goal_digest=loaded_goal.digest,
    )
    plan.plan[0].decomposition_status = DecompositionStatus.ACTIONABLE
    schedule, errors = build_render_schedule(
        plan,
        run_id="run-test",
        plan_digest=compute_plan_digest(plan),
        output_goal_digest=loaded_goal.digest,
        render_config=RenderConfig(),
    )
    assert errors == []
    assert len(schedule.batches) == 1
    assert schedule.batches[0].item_ids == ["item-001"]
