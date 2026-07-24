"""Tests for artifact path extraction."""

from __future__ import annotations

from todos_tool.artifact_paths import extract_artifact_paths


def test_extracts_backtick_and_bullet_paths() -> None:
    summary = """
## Artifacts
- ai-harness/generated/runs/screenshots/slice/overview-1440x900.png
Captured ` .playwright-mcp/page-20260724.png ` during QA.
"""
    paths = extract_artifact_paths(summary)
    assert "ai-harness/generated/runs/screenshots/slice/overview-1440x900.png" in paths
    assert ".playwright-mcp/page-20260724.png" in paths


def test_ignores_unrelated_paths() -> None:
    summary = "Updated src/app/page.tsx and docs/guide.md"
    assert extract_artifact_paths(summary) == []
