"""Agent context resolution and prompt rendering tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from todos_tool.agent_context import (
    AgentContextConfig,
    PhaseAgentContext,
    resolve_phase_agent_context,
    resolve_phase_model,
    validate_agent_context_paths,
)
from todos_tool.errors import ValidationError
from todos_tool.models import ItemType, Manifest, ManifestSettings, TodoItem
from todos_tool.prompts import build_review_prompt, build_work_prompt


def _item() -> TodoItem:
    return TodoItem(
        id="TASK-001",
        title="Add helper",
        type=ItemType.FEATURE,
        description="Implement helper.",
        acceptance_criteria=["Helper exists."],
    )


def test_resolve_phase_agent_context_additive_merge() -> None:
    run_cfg = AgentContextConfig(
        default=PhaseAgentContext(skills=("skills/a.md",), rules=("rules/a.mdc",)),
        implement=PhaseAgentContext(skills=("skills/b.md",)),
    )
    manifest_cfg = AgentContextConfig(
        implement=PhaseAgentContext(rules=("rules/c.mdc",)),
    )
    item_cfg = AgentContextConfig(
        review=PhaseAgentContext(skills=("skills/review.md",)),
    )

    implement = resolve_phase_agent_context(
        "implement", run_cfg, manifest_cfg, item_cfg
    )
    review = resolve_phase_agent_context(
        "review", run_cfg, manifest_cfg, item_cfg
    )

    assert implement.skills == ("skills/a.md", "skills/b.md")
    assert implement.rules == ("rules/a.mdc", "rules/c.mdc")
    assert review.skills == ("skills/a.md", "skills/review.md")
    assert review.rules == ("rules/a.mdc",)


def test_resolve_phase_model_precedence() -> None:
    run_cfg = AgentContextConfig(
        default=PhaseAgentContext(model="base-default"),
        implement=PhaseAgentContext(model="implement-model"),
        review=PhaseAgentContext(model="review-model"),
    )
    manifest_cfg = AgentContextConfig(
        implement=PhaseAgentContext(model="manifest-implement"),
    )
    item_cfg = AgentContextConfig(
        review=PhaseAgentContext(model="item-review"),
    )

    assert resolve_phase_model("implement", "cli-model", run_cfg) == "implement-model"
    assert (
        resolve_phase_model("implement", "cli-model", run_cfg, manifest_cfg)
        == "manifest-implement"
    )
    assert (
        resolve_phase_model("review", "cli-model", run_cfg, manifest_cfg, item_cfg)
        == "item-review"
    )
    assert resolve_phase_model("review", "cli-model", None) == "cli-model"


def test_prompts_include_phase_specific_agent_context() -> None:
    ctx = resolve_phase_agent_context(
        "implement",
        AgentContextConfig(
            default=PhaseAgentContext(skills=("skills/shared.md",)),
            implement=PhaseAgentContext(rules=("rules/implement.mdc",)),
        ),
    )
    work = build_work_prompt(
        _item(),
        logical_attempt=1,
        resolved_commands=[],
        agent_context=ctx,
    )
    review = build_review_prompt(
        _item(),
        logical_attempt=1,
        resolved_commands=[],
        work_summary="done",
        git_diff="",
        git_status="",
        agent_context=resolve_phase_agent_context(
            "review",
            AgentContextConfig(
                review=PhaseAgentContext(skills=("skills/review.md",)),
            ),
        ),
    )

    assert "skills/shared.md" in work
    assert "rules/implement.mdc" in work
    assert "skills/review.md" in review
    assert "rules/implement.mdc" not in review


def test_prompts_omit_agent_context_when_unconfigured() -> None:
    work = build_work_prompt(_item(), logical_attempt=1, resolved_commands=[])
    assert "Agent context" not in work


def test_validate_agent_context_paths_missing_file(git_project: Path) -> None:
    resolved = resolve_phase_agent_context(
        "implement",
        AgentContextConfig(
            implement=PhaseAgentContext(skills=("missing-skill.md",)),
        ),
    )
    with pytest.raises(ValidationError, match="not a file"):
        validate_agent_context_paths(
            git_project,
            resolved,
            label="test implement agent_context",
        )


def test_manifest_and_item_parse_agent_context() -> None:
    manifest = Manifest.from_dict(
        {
            "version": 1,
            "settings": {},
            "items": [],
            "agent_context": {
                "review": {"skills": ["skills/review.md"], "model": "review-model"},
            },
        }
    )
    item = TodoItem.from_dict(
        {
            "version": 1,
            "id": "TASK-001",
            "title": "Title",
            "type": "feature",
            "description": "Do work",
            "acceptance_criteria": ["Done"],
            "agent_context": {
                "implement": {"rules": ["rules/item.mdc"], "model": "implement-model"},
            },
        }
    )
    assert manifest.agent_context is not None
    assert manifest.agent_context.review.skills == ("skills/review.md",)
    assert manifest.agent_context.review.model == "review-model"
    assert item.agent_context is not None
    assert item.agent_context.implement.rules == ("rules/item.mdc",)
    assert item.agent_context.implement.model == "implement-model"
