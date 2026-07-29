"""Tests for planning-review-tool CLI."""

from __future__ import annotations

from typer.testing import CliRunner

from top_down_planning.review_tool import app
from top_down_planning.schema_docs import review_example


def test_usage_lists_specialist_stage() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["usage", "--stage", "specialist_review"])
    assert result.exit_code == 0
    assert "specialist_review" in result.stdout


def test_example_specialist_review_is_valid() -> None:
    payload = review_example("specialist_review")
    runner = CliRunner()
    import json

    result = runner.invoke(
        app,
        [
            "validate",
            "--json",
            json.dumps(payload),
            "--stage",
            "specialist_review",
        ],
    )
    assert result.exit_code == 0
