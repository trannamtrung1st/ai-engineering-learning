from pathlib import Path

from top_down_planning.completeness import leaf_actionable_count
from top_down_planning.render_brief import actionable_leaf_items, build_render_brief
from tests.plan_factory import make_root_plan
from top_down_planning.models import DecompositionStatus, PlanItem


def test_render_brief_matches_actionable_leaf_count() -> None:
    plan = make_root_plan(
        input_file="./idea.md",
        output_goal="goal",
        input_digest="a",
        output_goal_digest="b",
    )
    plan.plan.extend(
        [
            PlanItem(
                id="item-002",
                parent_id="item-001",
                title="Checkpoint A",
                objective="Do A",
                depth=1,
                order=2,
                decomposition_status=DecompositionStatus.ACTIONABLE,
            ),
            PlanItem(
                id="item-003",
                parent_id="item-001",
                title="Checkpoint B",
                objective="Do B",
                depth=1,
                order=3,
                decomposition_status=DecompositionStatus.ACTIONABLE,
            ),
        ]
    )

    leaves = actionable_leaf_items(plan)
    brief = build_render_brief(plan)

    assert len(leaves) == leaf_actionable_count(plan) == 2
    assert "### 1. Checkpoint A" in brief
    assert "### 2. Checkpoint B" in brief


def test_render_batch_prompt_references_assigned_items(
    tmp_path: Path,
    example_input: Path,
) -> None:
    from top_down_planning.input_loader import load_markdown_input, load_output_goal
    from top_down_planning.models import DEFAULT_INLINE_EMBED_THRESHOLD
    from top_down_planning.prompts import build_render_batch_prompt

    loaded_input = load_markdown_input(example_input)
    output_goal = load_output_goal(inline="Produce an actionable implementation plan")
    plan = make_root_plan(
        input_file=str(example_input),
        output_goal=output_goal.text,
        input_digest="a",
        output_goal_digest="b",
    )
    plan.plan.append(
        PlanItem(
            id="item-002",
            parent_id="item-001",
            title="Unique checkpoint title",
            objective="Complete the checkpoint",
            depth=1,
            order=2,
            decomposition_status=DecompositionStatus.ACTIONABLE,
            expected_outputs=["Deliverable artifact"],
            acceptance_criteria=["Validation passes"],
        )
    )
    batch_context = "\n".join(
        [
            "## Assigned items",
            "- `item-002` → `artifact-002` → staging `intermediates/render-batch-001/item-002.md`",
            "",
            "### item-002: Unique checkpoint title",
            "- Objective: Complete the checkpoint",
        ]
    )

    prompt = build_render_batch_prompt(
        batch_id="batch-001",
        plan_digest="d" * 64,
        output_goal_digest=output_goal.digest,
        render_config_digest="c" * 64,
        batch_context_markdown=batch_context,
        output_goal=output_goal,
        workspace=tmp_path,
        embed_threshold=DEFAULT_INLINE_EMBED_THRESHOLD,
    )

    assert "Render batch session: batch-001" in prompt
    assert "Unique checkpoint title" in prompt
    assert "Complete the checkpoint" in prompt
    assert "planning-render-tool" in prompt
    assert "Produce an actionable implementation plan" in prompt
