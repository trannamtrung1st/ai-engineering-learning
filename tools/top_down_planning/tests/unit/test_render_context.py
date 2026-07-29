from pathlib import Path

from top_down_planning.digest import compute_plan_digest
from top_down_planning.input_loader import load_output_goal
from top_down_planning.models import DecompositionStatus, RenderBatchItem
from top_down_planning.render_context import prepare_batch_context, prepare_scaffold_context
from tests.helpers import render_output_goal
from tests.plan_factory import make_root_plan


def test_prepare_scaffold_context(tmp_path: Path) -> None:
    loaded_goal = render_output_goal()
    plan = make_root_plan(
        output_goal=loaded_goal.text,
        output_goal_digest=loaded_goal.digest,
    )
    plan.plan[0].decomposition_status = DecompositionStatus.ACTIONABLE
    prepared = prepare_scaffold_context(
        plan=plan,
        output_dir=tmp_path / "out",
        workspace=tmp_path,
        output_goal=loaded_goal,
        plan_digest=compute_plan_digest(plan),
        embed_threshold=4000,
    )
    assert prepared.context_digest
    assert "Scaffold context" in prepared.context_markdown


def test_prepare_batch_context_includes_assigned_items(tmp_path: Path) -> None:
    loaded_goal = render_output_goal()
    plan = make_root_plan(
        output_goal=loaded_goal.text,
        output_goal_digest=loaded_goal.digest,
    )
    plan.plan[0].decomposition_status = DecompositionStatus.ACTIONABLE
    batch = RenderBatchItem(batch_index=0, item_ids=["item-001"], title="Root")
    prepared = prepare_batch_context(
        plan=plan,
        batch=batch,
        output_dir=tmp_path / "out",
        workspace=tmp_path,
        output_goal=loaded_goal,
        plan_digest=compute_plan_digest(plan),
        embed_threshold=4000,
        artifact_paths=["implementation-plan.md"],
    )
    assert "item-001" in prepared.context_markdown
    assert "implementation-plan.md" in prepared.context_markdown
