from pathlib import Path

from top_down_planning.completeness import leaf_actionable_count
from top_down_planning.input_loader import load_markdown_input, load_output_goal
from top_down_planning.models import DEFAULT_INLINE_EMBED_THRESHOLD, DecompositionStatus, PlanItem
from top_down_planning.prompts import build_final_render_prompt
from top_down_planning.render_brief import actionable_leaf_items, build_render_brief
from tests.plan_factory import make_root_plan


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


def test_render_prompt_inlines_breakdown_from_plan(
    tmp_path: Path,
    example_input: Path,
) -> None:
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
    output_dir = tmp_path / "planning-output"
    render_brief_path = output_dir / ".planning-output" / "iterations" / "render-brief.md"
    render_brief_path.parent.mkdir(parents=True, exist_ok=True)
    render_brief_path.write_text(build_render_brief(plan), encoding="utf-8")

    prompt = build_final_render_prompt(
        loaded_input=loaded_input,
        plan_file=output_dir / ".planning-output" / "plan.yaml",
        output_dir=output_dir,
        workspace=tmp_path,
        output_goal=output_goal,
        plan=plan,
        embed_threshold=DEFAULT_INLINE_EMBED_THRESHOLD,
        render_brief_file=render_brief_path,
    )

    assert "Breakdown to render" in prompt
    assert "Unique checkpoint title" in prompt
    assert "Complete the checkpoint" in prompt
    assert "Deliverable artifact" in prompt
    assert "Actionable deliverable units: 1" in prompt
    assert render_brief_path.read_text(encoding="utf-8") == build_render_brief(plan)
