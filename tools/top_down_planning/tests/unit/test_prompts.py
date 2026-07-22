from pathlib import Path

from top_down_planning.input_loader import load_markdown_input, load_output_goal, load_stop_hint
from top_down_planning.models import DEFAULT_INLINE_EMBED_THRESHOLD
from top_down_planning.prompts import (
    build_final_render_prompt,
    build_planning_prompt,
    format_embedded_markdown,
    format_input_document_section,
    format_input_file_reference,
    format_output_goal_section,
    format_stop_hint_section,
    should_embed_content,
)
from top_down_planning.scheduler import initialize_root_plan
from tests.plan_factory import make_root_plan


def test_should_embed_content_respects_threshold() -> None:
    assert should_embed_content("short", embed_threshold=10)
    assert not should_embed_content("too long", embed_threshold=3)


def test_format_embedded_markdown_wraps_content() -> None:
    assert format_embedded_markdown("  # Goal\n\nDo the thing.\n  ") == (
        "```markdown\n# Goal\n\nDo the thing.\n```"
    )


def test_embedded_sections_use_markdown_fences_consistently(
    tmp_path: Path,
    example_input: Path,
) -> None:
    loaded_input = load_markdown_input(example_input)
    output_goal = load_output_goal(inline="# Goal\n\nShip the feature.")
    stop_hint = load_stop_hint(inline="# Stop\n\nStop at actionable leaves.")

    input_section = format_input_document_section(
        loaded_input=loaded_input,
        workspace=tmp_path,
        embed_threshold=DEFAULT_INLINE_EMBED_THRESHOLD,
    )
    goal_section = format_output_goal_section(
        output_goal=output_goal,
        workspace=tmp_path,
        embed_threshold=DEFAULT_INLINE_EMBED_THRESHOLD,
    )
    stop_section = format_stop_hint_section(
        stop_hint=stop_hint,
        workspace=tmp_path,
        embed_threshold=DEFAULT_INLINE_EMBED_THRESHOLD,
    )

    for section in (input_section, goal_section, stop_section):
        assert "```markdown\n" in section
        assert section.endswith("```")

    assert "The complete primary input Markdown document:" in input_section
    assert "Ship the feature." in goal_section
    assert "Stop at actionable leaves." in stop_section


def test_large_file_backed_sections_reference_paths_not_fences(
    tmp_path: Path,
    example_input: Path,
) -> None:
    goal_file = tmp_path / "goal.md"
    goal_file.write_text("# Goal\n\n" + ("y" * 5000), encoding="utf-8")
    hint_file = tmp_path / "stop.md"
    hint_file.write_text("# Stop\n\n" + ("z" * 5000), encoding="utf-8")
    input_file = tmp_path / "large-input.md"
    input_file.write_text("# Large\n\n" + ("x" * 5000), encoding="utf-8")

    goal_section = format_output_goal_section(
        output_goal=load_output_goal(goal_file=goal_file),
        workspace=tmp_path,
        embed_threshold=DEFAULT_INLINE_EMBED_THRESHOLD,
    )
    stop_section = format_stop_hint_section(
        stop_hint=load_stop_hint(hint_file=hint_file),
        workspace=tmp_path,
        embed_threshold=DEFAULT_INLINE_EMBED_THRESHOLD,
    )
    input_section = format_input_document_section(
        loaded_input=load_markdown_input(input_file),
        workspace=tmp_path,
        embed_threshold=DEFAULT_INLINE_EMBED_THRESHOLD,
    )

    for section in (input_section, goal_section, stop_section):
        assert "```markdown" not in section
        assert "- Path:" in section
        assert "- Absolute:" in section


def test_prompt_embeds_small_input_document(
    example_input: Path,
    tmp_path: Path,
) -> None:
    loaded_input = load_markdown_input(example_input)
    output_goal = load_output_goal(inline="Produce an actionable implementation plan")
    plan = make_root_plan(
        input_file=str(example_input),
        output_goal=output_goal.text,
        input_digest="a",
        output_goal_digest="b",
    )
    root = plan.item_by_id("item-001")
    assert root is not None

    prompt = build_planning_prompt(
        loaded_input=loaded_input,
        workspace=tmp_path,
        output_goal=output_goal,
        plan=plan,
        selected_items=[root],
        embed_threshold=DEFAULT_INLINE_EMBED_THRESHOLD,
    )

    assert "The complete primary input Markdown document" in prompt
    assert "```markdown" in prompt
    assert "Build a small CLI that converts CSV" in prompt
    assert "Produce an actionable implementation plan" in prompt
    goal_section = format_output_goal_section(
        output_goal=output_goal,
        workspace=tmp_path,
        embed_threshold=DEFAULT_INLINE_EMBED_THRESHOLD,
    )
    assert goal_section.startswith("```markdown\n")


def test_prompt_references_large_input_file_by_path(tmp_path: Path) -> None:
    input_file = tmp_path / "large-input.md"
    input_file.write_text("# Large\n\n" + ("x" * 5000), encoding="utf-8")
    loaded_input = load_markdown_input(input_file)
    output_goal = load_output_goal(inline="Produce an actionable implementation plan")
    plan = make_root_plan(
        input_file=str(input_file),
        output_goal=output_goal.text,
        input_digest="a",
        output_goal_digest="b",
    )
    root = plan.item_by_id("item-001")
    assert root is not None

    prompt = build_planning_prompt(
        loaded_input=loaded_input,
        workspace=tmp_path,
        output_goal=output_goal,
        plan=plan,
        selected_items=[root],
        embed_threshold=DEFAULT_INLINE_EMBED_THRESHOLD,
    )

    assert "Read the complete primary input Markdown file" in prompt
    assert str(input_file.resolve()) in prompt
    assert "xxxxx" not in prompt


def test_prompt_embeds_short_output_goal_file(tmp_path: Path, example_input: Path) -> None:
    goal_file = tmp_path / "goals" / "plan.md"
    goal_file.parent.mkdir()
    goal_file.write_text(
        "# Goal\n\nProduce an actionable implementation plan with phases.\n",
        encoding="utf-8",
    )
    loaded_input = load_markdown_input(example_input)
    output_goal = load_output_goal(goal_file=goal_file)
    plan = make_root_plan(
        input_file=str(example_input),
        output_goal=output_goal.text,
        output_goal_file=str(goal_file),
        input_digest="a",
        output_goal_digest="b",
    )
    root = plan.item_by_id("item-001")
    assert root is not None

    prompt = build_planning_prompt(
        loaded_input=loaded_input,
        workspace=tmp_path,
        output_goal=output_goal,
        plan=plan,
        selected_items=[root],
        embed_threshold=DEFAULT_INLINE_EMBED_THRESHOLD,
    )

    assert "with phases" in prompt
    assert "Read the output goal specification" not in prompt
    assert "```markdown" in prompt


def test_prompt_references_large_output_goal_file(tmp_path: Path, example_input: Path) -> None:
    goal_file = tmp_path / "goals" / "plan.md"
    goal_file.parent.mkdir()
    goal_file.write_text("# Goal\n\n" + ("y" * 5000), encoding="utf-8")
    loaded_input = load_markdown_input(example_input)
    output_goal = load_output_goal(goal_file=goal_file)
    plan = make_root_plan(
        input_file=str(example_input),
        output_goal=output_goal.text,
        output_goal_file=str(goal_file),
        input_digest="a",
        output_goal_digest="b",
    )
    root = plan.item_by_id("item-001")
    assert root is not None

    prompt = build_planning_prompt(
        loaded_input=loaded_input,
        workspace=tmp_path,
        output_goal=output_goal,
        plan=plan,
        selected_items=[root],
        embed_threshold=DEFAULT_INLINE_EMBED_THRESHOLD,
    )

    assert "Read the output goal specification" in prompt
    assert str(goal_file.resolve()) in prompt
    assert "yyyyy" not in prompt


def test_embed_threshold_zero_prefers_path_refs_for_file_backed_content(
    tmp_path: Path,
    example_input: Path,
) -> None:
    goal_file = tmp_path / "goal.md"
    goal_file.write_text("# Goal\n\nShort goal from file.\n", encoding="utf-8")
    loaded_input = load_markdown_input(example_input)
    output_goal = load_output_goal(goal_file=goal_file)

    input_section = format_input_document_section(
        loaded_input=loaded_input,
        workspace=tmp_path,
        embed_threshold=0,
    )
    goal_section = format_output_goal_section(
        output_goal=output_goal,
        workspace=tmp_path,
        embed_threshold=0,
    )

    assert "Read the complete primary input Markdown file" in input_section
    assert "Build a small CLI" not in input_section
    assert "Read the output goal specification" in goal_section
    assert "Short goal from file" not in goal_section


def test_long_inline_output_goal_embeds_when_no_path_exists() -> None:
    output_goal = load_output_goal(inline="g" * 5000)
    section = format_output_goal_section(
        output_goal=output_goal,
        workspace=Path("."),
        embed_threshold=DEFAULT_INLINE_EMBED_THRESHOLD,
    )

    assert "g" * 100 in section
    assert "Read the output goal specification" not in section
    assert section.startswith("```markdown\n")


def test_should_embed_content_uses_inclusive_boundary() -> None:
    exact = "x" * DEFAULT_INLINE_EMBED_THRESHOLD
    assert should_embed_content(exact, embed_threshold=DEFAULT_INLINE_EMBED_THRESHOLD)
    assert not should_embed_content(
        exact + "y",
        embed_threshold=DEFAULT_INLINE_EMBED_THRESHOLD,
    )


def test_input_file_reference_prefers_workspace_relative_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    input_file = workspace / "ideas" / "feature.md"
    input_file.parent.mkdir()
    input_file.write_text("# Feature\n", encoding="utf-8")

    reference = format_input_file_reference(input_file, workspace)
    assert "ideas/feature.md" in reference
    assert str(input_file.resolve()) in reference


def test_prompt_includes_stop_hint_when_provided(
    example_input: Path,
    tmp_path: Path,
) -> None:
    loaded_input = load_markdown_input(example_input)
    output_goal = load_output_goal(inline="Produce an actionable implementation plan")
    stop_hint = load_stop_hint(
        inline="Stop expanding once each major area has actionable leaf tasks."
    )
    plan = make_root_plan(
        input_file=str(example_input),
        output_goal=output_goal.text,
        input_digest="a",
        output_goal_digest="b",
    )
    root = plan.item_by_id("item-001")
    assert root is not None

    prompt = build_planning_prompt(
        loaded_input=loaded_input,
        workspace=tmp_path,
        output_goal=output_goal,
        plan=plan,
        selected_items=[root],
        embed_threshold=DEFAULT_INLINE_EMBED_THRESHOLD,
        stop_hint=stop_hint,
    )

    assert "Expansion stop guidance" in prompt
    assert "actionable leaf tasks" in prompt
    assert "plan_complete" in prompt
    assert prompt.count("```markdown") >= 2


def test_planning_prompt_uses_transaction_cli(
    example_input: Path,
    tmp_path: Path,
) -> None:
    loaded_input = load_markdown_input(example_input)
    output_goal = load_output_goal(inline="Produce an actionable implementation plan")
    plan = make_root_plan(
        input_file=str(example_input),
        output_goal=output_goal.text,
        input_digest="a",
        output_goal_digest="b",
    )
    root = plan.item_by_id("item-001")
    assert root is not None

    prompt = build_planning_prompt(
        loaded_input=loaded_input,
        workspace=tmp_path,
        output_goal=output_goal,
        plan=plan,
        selected_items=[root],
        embed_threshold=DEFAULT_INLINE_EMBED_THRESHOLD,
    )

    assert "Planning transaction CLI" in prompt
    assert "record-operation" in prompt
    assert "Required response format" not in prompt


def test_prompt_omits_stop_hint_section_when_not_provided(
    example_input: Path,
    tmp_path: Path,
) -> None:
    loaded_input = load_markdown_input(example_input)
    output_goal = load_output_goal(inline="Produce an actionable implementation plan")
    plan = make_root_plan(
        input_file=str(example_input),
        output_goal=output_goal.text,
        input_digest="a",
        output_goal_digest="b",
    )
    root = plan.item_by_id("item-001")
    assert root is not None

    prompt = build_planning_prompt(
        loaded_input=loaded_input,
        workspace=tmp_path,
        output_goal=output_goal,
        plan=plan,
        selected_items=[root],
        embed_threshold=DEFAULT_INLINE_EMBED_THRESHOLD,
    )

    assert "Expansion stop guidance" not in prompt


def test_final_render_prompt_references_plan_and_output_goal(
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
    plan_file = tmp_path / ".planning-output" / "plan.yaml"
    plan_file.parent.mkdir(parents=True)

    prompt = build_final_render_prompt(
        loaded_input=loaded_input,
        plan_file=plan_file,
        output_dir=tmp_path / "planning-output",
        workspace=tmp_path,
        output_goal=output_goal,
        plan=plan,
        embed_threshold=DEFAULT_INLINE_EMBED_THRESHOLD,
    )

    assert "Final planning render" in prompt
    assert str(plan_file.resolve()) in prompt
    assert "Produce an actionable implementation plan" in prompt
    assert prompt.count("```markdown") >= 3
    assert "Deliverable directory" in prompt
    assert "Breakdown to render" in prompt
    assert "authoritative scope" in prompt
    assert "Do **not** copy, restore, or reuse pre-existing files" in prompt
    assert ".planning-output" in prompt
    assert '"artifacts"' not in prompt
    assert "Required response format" not in prompt


def test_final_render_prompt_includes_validation_feedback(
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
    plan_file = tmp_path / ".planning-output" / "plan.yaml"
    plan_file.parent.mkdir(parents=True)

    prompt = build_final_render_prompt(
        loaded_input=loaded_input,
        plan_file=plan_file,
        output_dir=tmp_path / "planning-output",
        workspace=tmp_path,
        output_goal=output_goal,
        plan=plan,
        embed_threshold=DEFAULT_INLINE_EMBED_THRESHOLD,
        validation_feedback=["Deliverables do not cover breakdown item item-002"],
    )

    assert "Render validation feedback from previous attempt" in prompt
    assert "item-002" in prompt
