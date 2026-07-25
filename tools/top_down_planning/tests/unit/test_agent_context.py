"""Agent context tests for the planning tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.agent_context import (
    AgentContextConfig,
    PhaseAgentContext,
    resolve_phase_agent_context,
    resolve_phase_model,
    validate_agent_context_paths,
)
from top_down_planning.config_loader import load_run_config_file, merge_run_options
from top_down_planning.errors import PlanningToolError
from top_down_planning.input_loader import LoadedInput, LoadedOutputGoal
from top_down_planning.prompts import build_render_batch_prompt, build_planning_prompt
from tests.helpers import planning_prompt_kwargs
from tests.plan_factory import make_root_plan


def test_config_loader_parses_agent_context(tmp_path: Path) -> None:
    skill = tmp_path / "skill.md"
    skill.write_text("# skill\n", encoding="utf-8")
    config_path = tmp_path / "planning.config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "input: idea.md",
                "output: out",
                "output_goal: Plan",
                "agent_context:",
                "  default:",
                f"    skills: [{skill.name}]",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "idea.md").write_text("# idea\n", encoding="utf-8")

    loaded = load_run_config_file(config_path)
    options = merge_run_options(
        config_path=config_path,
        input_path=tmp_path / "idea.md",
        output_dir=tmp_path / "out",
        output_goal="Plan",
        workspace=tmp_path,
    )

    assert loaded.agent_context is not None
    assert options.agent_context is not None
    assert options.agent_context.default.skills == (skill.name,)


def test_resolve_phase_model_uses_later_layers() -> None:
    config = AgentContextConfig(
        default=PhaseAgentContext(model="default-model"),
        planning=PhaseAgentContext(model="planning-model"),
        rendering=PhaseAgentContext(model="rendering-model"),
    )
    assert resolve_phase_model("planning", "cli-model", config) == "planning-model"
    assert resolve_phase_model("rendering", "cli-model", config) == "rendering-model"
    assert resolve_phase_model("planning", "cli-model", None) == "cli-model"


def test_planning_and_render_prompts_include_phase_context() -> None:
    loaded_input = LoadedInput(path=Path("idea.md"), text="# idea", digest="abc")
    output_goal = LoadedOutputGoal(text="Produce a plan", digest="goal")
    plan = make_root_plan()
    planning_ctx = resolve_phase_agent_context(
        "planning",
        AgentContextConfig(
            planning=PhaseAgentContext(skills=("skills/plan.md",)),
        ),
    )
    render_ctx = resolve_phase_agent_context(
        "rendering",
        AgentContextConfig(
            rendering=PhaseAgentContext(rules=("rules/render.mdc",)),
        ),
    )

    root = plan.plan[0]
    planning_prompt = build_planning_prompt(
        loaded_input=loaded_input,
        workspace=Path("."),
        output_goal=output_goal,
        plan=plan,
        selected_items=[root],
        embed_threshold=4000,
        agent_context=planning_ctx,
        **planning_prompt_kwargs(
            plan=plan,
            selected_items=[root],
            output_dir=Path("out"),
        ),
    )
    render_prompt = build_render_batch_prompt(
        batch_id="batch-001",
        plan_digest="d" * 64,
        output_goal_digest=output_goal.digest,
        render_config_digest="c" * 64,
        batch_context_markdown="## Assigned items\n- `item-001` → `todo-item-001` → section 1\n",
        output_goal=output_goal,
        workspace=Path("."),
        embed_threshold=4000,
        agent_context=render_ctx,
    )

    assert "skills/plan.md" in planning_prompt
    assert "rules/render.mdc" not in planning_prompt
    assert "rules/render.mdc" in render_prompt
    assert "skills/plan.md" not in render_prompt


def test_validate_agent_context_paths_missing_file(tmp_path: Path) -> None:
    resolved = resolve_phase_agent_context(
        "planning",
        AgentContextConfig(
            planning=PhaseAgentContext(skills=("missing.md",)),
        ),
    )
    with pytest.raises(PlanningToolError, match="not a file"):
        validate_agent_context_paths(
            tmp_path,
            resolved,
            label="planning agent_context",
        )
