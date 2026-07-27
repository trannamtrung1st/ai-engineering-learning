from pathlib import Path

from top_down_planning.digest import compute_plan_digest
from top_down_planning.models import DecompositionStatus, RenderConfig
from top_down_planning.render_context import prepare_render_node_context
from tests.helpers import render_output_goal
from tests.plan_factory import make_root_plan


def test_prepare_render_node_context_includes_node_details(tmp_path: Path) -> None:
    loaded_goal = render_output_goal()
    plan = make_root_plan(
        output_goal=loaded_goal.text,
        output_goal_digest=loaded_goal.digest,
    )
    plan.plan[0].decomposition_status = DecompositionStatus.ACTIONABLE
    plan_digest = compute_plan_digest(plan)
    prepared = prepare_render_node_context(
        plan=plan,
        node_id="item-001",
        output_dir=tmp_path,
        workspace=tmp_path,
        output_goal=loaded_goal,
        whole_plan_context=RenderConfig().whole_plan_context,
        embed_threshold=4000,
        plan_digest=plan_digest,
    )

    assert "item-001" in prepared.node_context_markdown
    assert prepared.context_snapshot.node_id == "item-001"
    assert prepared.staging_dir.is_dir()
