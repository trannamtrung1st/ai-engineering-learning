from pathlib import Path

import pytest

from top_down_planning.models import DecompositionStatus, PlanItem
from top_down_planning.render_brief import (
    actionable_leaf_items,
    build_render_brief,
    validate_render_coverage,
)
from tests.plan_factory import make_root_plan


def _plan_with_leaves() -> tuple:
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
                title="Area A",
                objective="Do A",
                depth=1,
                order=2,
                decomposition_status=DecompositionStatus.ACTIONABLE,
                expected_outputs=["Output A"],
                acceptance_criteria=["Done A"],
            ),
            PlanItem(
                id="item-003",
                parent_id="item-001",
                title="Area B",
                objective="Do B",
                depth=1,
                order=3,
                decomposition_status=DecompositionStatus.ACTIONABLE,
                dependencies=["item-002"],
                expected_outputs=["Output B"],
                acceptance_criteria=["Done B"],
            ),
        ]
    )
    return plan


def test_actionable_leaf_items_excludes_container_nodes() -> None:
    plan = _plan_with_leaves()
    plan.plan[0].decomposition_status = DecompositionStatus.ACTIONABLE
    plan.plan.append(
        PlanItem(
            id="item-004",
            parent_id="item-002",
            title="Nested leaf",
            objective="Nested",
            depth=2,
            order=4,
            decomposition_status=DecompositionStatus.ACTIONABLE,
        )
    )

    leaves = actionable_leaf_items(plan)
    titles = [item.title for item in leaves]

    assert "Understand and plan the requested work" not in titles
    assert "Area A" not in titles
    assert "Area B" in titles
    assert "Nested leaf" in titles


def test_build_render_brief_lists_every_actionable_leaf() -> None:
    plan = _plan_with_leaves()
    brief = build_render_brief(plan)

    assert "authoritative scope" in brief
    assert "### 1. Area A" in brief
    assert "### 2. Area B" in brief
    assert "Output A" in brief
    assert "Done B" in brief


def test_validate_render_coverage_requires_every_leaf_title(tmp_path: Path) -> None:
    plan = _plan_with_leaves()
    covered = tmp_path / "plan.md"
    covered.write_text("# Plan\n\nArea A\nArea B\n", encoding="utf-8")

    assert validate_render_coverage(plan, [covered]) == []

    partial = tmp_path / "partial.md"
    partial.write_text("# Plan\n\nArea A\n", encoding="utf-8")
    errors = validate_render_coverage(plan, [partial])

    assert len(errors) == 1
    assert "Area B" in errors[0]


def test_validate_render_coverage_requires_at_least_one_file() -> None:
    plan = _plan_with_leaves()
    assert validate_render_coverage(plan, []) == ["No deliverable files were written."]
