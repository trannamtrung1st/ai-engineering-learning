from pathlib import Path

import pytest

from top_down_planning.config_loader import load_run_config_file, merge_run_options
from top_down_planning.errors import PlanningToolError


def test_load_run_config_file_resolves_paths_relative_to_config(tmp_path: Path) -> None:
    config_dir = tmp_path / "project"
    config_dir.mkdir()
    input_file = config_dir / "docs" / "idea.md"
    input_file.parent.mkdir()
    input_file.write_text("# Idea\n", encoding="utf-8")
    goal_file = config_dir / "goal.md"
    goal_file.write_text("# Goal\n", encoding="utf-8")
    config_path = config_dir / "planning.yaml"
    config_path.write_text(
        "\n".join(
            [
                "input: ./docs/idea.md",
                "output: ./planning-output",
                "output_goal_file: ./goal.md",
                "workspace: .",
            ]
        ),
        encoding="utf-8",
    )

    loaded = load_run_config_file(config_path)
    options = merge_run_options(config_path=config_path)

    assert loaded.input == Path("./docs/idea.md")
    assert options.input_path == input_file.resolve()
    assert options.output_dir == (config_dir / "planning-output").resolve()
    assert options.output_goal_file == goal_file.resolve()
    assert options.workspace == config_dir.resolve()


def test_merge_run_options_uses_nested_limits(tmp_path: Path) -> None:
    config_path = tmp_path / "planning.yaml"
    config_path.write_text(
        "\n".join(
            [
                "input: ./idea.md",
                "output: ./out",
                "output_goal: Produce a plan",
                "limits:",
                "  max_iterations: 12",
                "  batch_size: 5",
                "  session_timeout_seconds: 900",
            ]
        ),
        encoding="utf-8",
    )

    options = merge_run_options(config_path=config_path)

    assert options.max_iterations == 12
    assert options.batch_size == 5
    assert options.max_depth == 6
    assert options.session_timeout_seconds == 900


def test_options_to_planning_limits_includes_advanced_fields(tmp_path: Path) -> None:
    config_path = tmp_path / "planning.yaml"
    config_path.write_text(
        "\n".join(
            [
                "input: ./idea.md",
                "output: ./out",
                "output_goal: Produce a plan",
                "max_children_per_expansion: 8",
                "parse_error_threshold: 10",
            ]
        ),
        encoding="utf-8",
    )
    from top_down_planning.config_loader import options_to_planning_limits

    options = merge_run_options(config_path=config_path)
    limits = options_to_planning_limits(options)

    assert limits.max_children_per_expansion == 8
    assert limits.parse_error_threshold == 10
    assert limits.session_timeout_seconds == 600


def test_merge_run_options_cli_overrides_config(tmp_path: Path) -> None:
    config_path = tmp_path / "planning.yaml"
    config_path.write_text(
        "\n".join(
            [
                "input: ./idea.md",
                "output: ./out",
                "output_goal: From config",
                "max_iterations: 12",
            ]
        ),
        encoding="utf-8",
    )
    override_input = tmp_path / "override.md"
    override_input.write_text("# Override\n", encoding="utf-8")

    options = merge_run_options(
        config_path=config_path,
        input_path=override_input,
        output_goal="From CLI",
        max_iterations=99,
    )

    assert options.input_path == override_input.resolve()
    assert options.output_goal == "From CLI"
    assert options.max_iterations == 99


def test_merge_run_options_rejects_both_goal_sources_in_config(tmp_path: Path) -> None:
    config_path = tmp_path / "planning.yaml"
    config_path.write_text(
        "\n".join(
            [
                "input: ./idea.md",
                "output: ./out",
                "output_goal: Inline",
                "output_goal_file: ./goal.md",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(PlanningToolError):
        merge_run_options(config_path=config_path)


def test_merge_run_options_resolves_content_paths_relative_to_workspace(
    tmp_path: Path,
) -> None:
    """Paths like input/output/goal file are workspace-relative, not config-dir-relative."""
    project_root = tmp_path / "project"
    config_dir = project_root / "temp"
    config_dir.mkdir(parents=True)
    input_file = project_root / "plans" / "feature" / "proposal.md"
    input_file.parent.mkdir(parents=True)
    input_file.write_text("# Proposal\n", encoding="utf-8")
    goal_file = config_dir / "planning-goal.md"
    goal_file.write_text("# Goal\n", encoding="utf-8")
    config_path = config_dir / "planning.config.yaml"
    config_path.write_text(
        "\n".join(
            [
                f"input: plans/feature/proposal.md",
                "output: temp",
                f"workspace: {project_root}",
                "output_goal_file: temp/planning-goal.md",
            ]
        ),
        encoding="utf-8",
    )

    options = merge_run_options(config_path=config_path)

    assert options.workspace == project_root.resolve()
    assert options.input_path == input_file.resolve()
    assert options.output_dir == config_dir.resolve()
    assert options.output_goal_file == goal_file.resolve()


def test_merge_run_options_requires_input_and_output(tmp_path: Path) -> None:
    config_path = tmp_path / "planning.yaml"
    config_path.write_text("output_goal: Produce a plan\n", encoding="utf-8")

    with pytest.raises(PlanningToolError, match="input"):
        merge_run_options(config_path=config_path)

    with pytest.raises(PlanningToolError, match="output"):
        merge_run_options(
            config_path=config_path,
            input_path=tmp_path / "idea.md",
        )
