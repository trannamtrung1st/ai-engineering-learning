"""CLI notification hook tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from todos_tool.cli import (
    _cli_notify_override,
    _cli_notify_per_item_override,
    _finalize_run_config,
    _print_report,
    main,
)
from todos_tool.orchestrator import RunReport
from todos_tool.run_config import RunConfig
from pathlib import Path


def test_cli_notify_override() -> None:
    assert _cli_notify_override(argparse_like(notify=True, no_notify=False)) is True
    assert _cli_notify_override(argparse_like(notify=False, no_notify=True)) is False
    assert _cli_notify_override(argparse_like(notify=False, no_notify=False)) is None


def test_cli_notify_per_item_override() -> None:
    assert (
        _cli_notify_per_item_override(
            argparse_like_per_item(notify_per_item=True, no_notify_per_item=False)
        )
        is True
    )
    assert (
        _cli_notify_per_item_override(
            argparse_like_per_item(notify_per_item=False, no_notify_per_item=True)
        )
        is False
    )
    assert (
        _cli_notify_per_item_override(
            argparse_like_per_item(notify_per_item=False, no_notify_per_item=False)
        )
        is None
    )


def argparse_like(*, notify: bool, no_notify: bool):
    return type("Args", (), {"notify": notify, "no_notify": no_notify})()


def argparse_like_per_item(*, notify_per_item: bool, no_notify_per_item: bool):
    return type(
        "Args",
        (),
        {"notify_per_item": notify_per_item, "no_notify_per_item": no_notify_per_item},
    )()


def test_finalize_run_config_applies_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TODOS_TOOL_NOTIFY", "false")
    config = RunConfig(workspace_root=Path("."), notify=True)
    args = argparse_like(notify=False, no_notify=False)
    finalized = _finalize_run_config(config, args)
    assert finalized.notify is False


def test_finalize_run_config_applies_notify_per_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TODOS_TOOL_NOTIFY_PER_ITEM", raising=False)
    config = RunConfig(workspace_root=Path("."), notify=True, notify_per_item=True)
    args = argparse_like_per_item(notify_per_item=False, no_notify_per_item=True)
    finalized = _finalize_run_config(config, args)
    assert finalized.notify_per_item is False


@patch("todos_tool.cli.notify_run_report")
def test_print_report_notifies(mock_notify: MagicMock) -> None:
    report = RunReport(completed=["TASK-001"])
    assert _print_report(report, no_color=True, notify_enabled=True) == 0
    mock_notify.assert_called_once_with(report, enabled=True)


def test_run_help_lists_notify_flags(capsys) -> None:
    with pytest.raises(SystemExit):
        main(["run", "--help"])
    captured = capsys.readouterr()
    assert "--notify" in captured.out
    assert "--no-notify" in captured.out


@patch("todos_tool.cli.notify_error")
@patch("todos_tool.cli.Orchestrator")
def test_cmd_run_notifies_on_tool_error(
    mock_orch_cls: MagicMock,
    mock_notify_error: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from todos_tool.errors import TodosToolError

    mock_orch = MagicMock()
    mock_orch.run = AsyncMock(side_effect=TodosToolError("boom"))
    mock_orch_cls.return_value = mock_orch

    assert main(["run", "--workspace", ".", "--no-notify"]) == 1
    mock_notify_error.assert_called_once_with(enabled=False, message="boom")

    mock_orch.run = AsyncMock(side_effect=TodosToolError("boom"))
    mock_notify_error.reset_mock()
    assert main(["run", "--workspace", ".", "--notify"]) == 1
    mock_notify_error.assert_called_once_with(enabled=True, message="boom")
