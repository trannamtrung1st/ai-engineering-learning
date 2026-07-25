"""CLI notification hook tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from top_down_planning.cli import _cli_notify_override, app
from top_down_planning.models import FinalStatus, PlanningReport


runner = CliRunner()


def test_cli_notify_override() -> None:
    assert _cli_notify_override(notify=True, no_notify=False) is True
    assert _cli_notify_override(notify=False, no_notify=True) is False
    assert _cli_notify_override(notify=False, no_notify=False) is None


def test_run_help_lists_notify_flags() -> None:
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "--notify" in result.stdout
    assert "--no-notify" in result.stdout


@patch("top_down_planning.cli.asyncio.run")
@patch("top_down_planning.cli.Orchestrator")
@patch("top_down_planning.cli.notify_planning_report")
@patch("top_down_planning.cli.merge_run_options")
def test_execute_run_notifies_on_success(
    mock_merge: MagicMock,
    mock_notify_report: MagicMock,
    mock_orch_cls: MagicMock,
    mock_asyncio_run: MagicMock,
    tmp_path,
) -> None:
    from top_down_planning.config_loader import ResolvedRunOptions

    input_path = tmp_path / "idea.md"
    output_dir = tmp_path / "out"
    input_path.write_text("# Idea", encoding="utf-8")
    output_dir.mkdir()

    mock_merge.return_value = ResolvedRunOptions(
        input_path=input_path,
        output_dir=output_dir,
        output_goal="Goal",
        output_goal_file=None,
        stop_hint=None,
        stop_hint_file=None,
        workspace=tmp_path,
        max_iterations=10,
        max_depth=4,
        max_items=50,
        max_retries=2,
        max_children_per_expansion=8,
        session_timeout_seconds=600,
        parse_error_threshold=20,
        resume=False,
        stream_json=False,
        no_color=True,
        notify=True,
        model=None,
        agent_bin=None,
        skip_probe=True,
        embed_threshold=None,
    )
    report = PlanningReport(status=FinalStatus.COMPLETE, items=3, actionable_items=2)
    mock_asyncio_run.return_value = report

    result = runner.invoke(
        app,
        [
            "run",
            "--input",
            str(input_path),
            "--output-goal",
            "Goal",
            "--output",
            str(output_dir),
            "--notify",
        ],
    )
    assert result.exit_code == 0
    mock_notify_report.assert_called_once_with(
        report,
        enabled=True,
    )
