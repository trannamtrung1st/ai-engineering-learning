import pytest

from top_down_planning.errors import PlanningToolError
from top_down_planning.output_goal_artifacts import parse_output_goal_artifacts


def test_parse_single_document_output_goal() -> None:
    goal = """# Goal

Produce an actionable implementation plan.

## Output artifacts

Write one Markdown deliverable:

- `implementation-plan.md`
"""
    parsed = parse_output_goal_artifacts(goal)
    assert parsed.paths == ["implementation-plan.md"]
    assert parsed.deliverable_root is None
    assert parsed.declared_set_level_files == []
    assert parsed.item_paths == []


def test_parse_multi_file_goal_with_fenced_paths() -> None:
    goal = """# Goal

## Output artifacts

Deliver under:

```
plans/demo/todos/INDEX.md
plans/demo/todos/manifest.yaml
plans/demo/todos/01-first-item.yaml
```

Evidence: run `./scripts/test-critical` on HEAD when complete.
"""
    parsed = parse_output_goal_artifacts(goal)
    assert parsed.deliverable_root == "plans/demo/todos/"
    assert "INDEX.md" in parsed.declared_set_level_files
    assert "manifest.yaml" in parsed.declared_set_level_files
    assert "01-first-item.yaml" in parsed.item_paths
    assert "./scripts/test-critical" not in parsed.paths
    assert "HEAD" not in parsed.paths


def test_parse_goal_uses_index_parent_as_root() -> None:
    goal = """# Goal

## Output artifacts

- `plans/14-sm-evolution-p5/todos/INDEX.md`
- `plans/14-sm-evolution-p5/todos/manifest.yaml`
- `plans/14-sm-evolution-p5/todos/13-docs-packaging-and-exit.yaml`
"""
    parsed = parse_output_goal_artifacts(goal)
    assert parsed.deliverable_root == "plans/14-sm-evolution-p5/todos/"
    assert parsed.declared_set_level_files == ["INDEX.md", "manifest.yaml"]


def test_parse_requires_output_artifacts_section() -> None:
    with pytest.raises(PlanningToolError, match="Output artifacts"):
        parse_output_goal_artifacts("Produce a plan without artifact paths.")


def test_parse_rejects_path_traversal() -> None:
    goal = """# Goal

## Output artifacts

- `../../../tmp/evil.yaml`
"""
    with pytest.raises(ValueError, match="must not contain"):
        parse_output_goal_artifacts(goal)


def test_parse_rejects_ambiguous_deliverable_roots() -> None:
    goal = """# Goal

## Output artifacts

- `plans/a/todos/INDEX.md`
- `plans/b/todos/INDEX.md`
"""
    with pytest.raises(PlanningToolError, match="multiple deliverable roots"):
        parse_output_goal_artifacts(goal)
