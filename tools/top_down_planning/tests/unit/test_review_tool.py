"""Review-tool discovery and offline validation tests."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from top_down_planning.review_tool import app
from top_down_planning.schema_docs import review_example


runner = CliRunner()


def test_review_tool_usage() -> None:
    result = runner.invoke(app, ["usage", "--stage", "whole_plan_review"])
    assert result.exit_code == 0
    assert "planning-review-tool schema" in result.stdout


def test_review_tool_schema_and_example_offline() -> None:
    for stage in (
        "whole_plan_review",
        "final_confirmation",
        "render_batch_review",
        "rendered_output_review",
    ):
        schema = runner.invoke(app, ["schema", "--stage", stage])
        assert schema.exit_code == 0
        assert '"properties"' in schema.stdout

        example = runner.invoke(app, ["example", "--stage", stage])
        assert example.exit_code == 0
        payload = json.loads(example.stdout)
        validate = runner.invoke(
            app,
            ["validate", "--json", json.dumps(payload), "--stage", stage],
        )
        assert validate.exit_code == 0
        assert "Valid" in validate.stdout


def test_review_tool_validate_rejects_invalid_payload() -> None:
    payload = review_example("whole_plan_review")
    payload["decision"] = "not-a-decision"
    result = runner.invoke(
        app,
        [
            "validate",
            "--json",
            json.dumps(payload),
            "--stage",
            "whole_plan_review",
        ],
    )
    assert result.exit_code == 1
