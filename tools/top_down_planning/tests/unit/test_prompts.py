from pathlib import Path

from top_down_planning.input_loader import load_output_goal
from top_down_planning.prompts import (
    build_final_render_prompt,
    build_planning_prompt,
    format_input_file_reference,
)
from top_down_planning.scheduler import initialize_root_plan


def test_prompt_references_input_file_instead_of_embedding_content(
    example_input: Path,
    tmp_path: Path,
) -> None:
    output_goal = load_output_goal(inline="Produce an actionable implementation plan")
    plan = initialize_root_plan(
        input_file=str(example_input),
        output_goal=output_goal.text,
        input_digest="a",
        output_goal_digest="b",
    )
    root = plan.item_by_id("item-001")
    assert root is not None

    prompt = build_planning_prompt(
        input_file=example_input,
        workspace=tmp_path,
        output_goal=output_goal,
        plan=plan,
        selected_items=[root],
    )

    assert "Read the complete primary input Markdown file" in prompt
    assert str(example_input.resolve()) in prompt
    assert "```markdown" not in prompt
    assert "Build a small CLI that converts CSV" not in prompt
    assert "Produce an actionable implementation plan" in prompt


def test_prompt_references_output_goal_file(tmp_path: Path, example_input: Path) -> None:
    goal_file = tmp_path / "goals" / "plan.md"
    goal_file.parent.mkdir()
    goal_file.write_text(
        "# Goal\n\nProduce an actionable implementation plan with phases.\n",
        encoding="utf-8",
    )
    output_goal = load_output_goal(goal_file=goal_file)
    plan = initialize_root_plan(
        input_file=str(example_input),
        output_goal=output_goal.text,
        output_goal_file=str(goal_file),
        input_digest="a",
        output_goal_digest="b",
    )
    root = plan.item_by_id("item-001")
    assert root is not None

    prompt = build_planning_prompt(
        input_file=example_input,
        workspace=tmp_path,
        output_goal=output_goal,
        plan=plan,
        selected_items=[root],
    )

    assert "Read the output goal specification" in prompt
    assert str(goal_file.resolve()) in prompt
    assert "with phases" not in prompt


def test_input_file_reference_prefers_workspace_relative_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    input_file = workspace / "ideas" / "feature.md"
    input_file.parent.mkdir()
    input_file.write_text("# Feature\n", encoding="utf-8")

    reference = format_input_file_reference(input_file, workspace)
    assert "ideas/feature.md" in reference
    assert str(input_file.resolve()) in reference


def test_final_render_prompt_references_plan_and_output_goal(
    tmp_path: Path,
    example_input: Path,
) -> None:
    output_goal = load_output_goal(inline="Produce an actionable implementation plan")
    plan = initialize_root_plan(
        input_file=str(example_input),
        output_goal=output_goal.text,
        input_digest="a",
        output_goal_digest="b",
    )
    plan_file = tmp_path / ".top-down-planning" / "plan.yaml"
    plan_file.parent.mkdir(parents=True)

    prompt = build_final_render_prompt(
        input_file=example_input,
        plan_file=plan_file,
        workspace=tmp_path,
        output_goal=output_goal,
        plan=plan,
    )

    assert "Final planning render" in prompt
    assert str(plan_file.resolve()) in prompt
    assert "Produce an actionable implementation plan" in prompt
    assert "artifacts" in prompt
