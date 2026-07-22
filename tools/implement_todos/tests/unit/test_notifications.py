"""Unit tests for desktop notification helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from todos_tool.notifications import (
    APP_NAME,
    ENV_NOTIFY,
    notify_commit_success,
    notify_error,
    notify_interrupted,
    notify_run_report,
    resolve_notify_enabled,
    send_notification,
    should_notify,
)
from todos_tool.orchestrator import RunReport


@pytest.mark.parametrize(
    ("cli_value", "config_value", "env_value", "expected"),
    [
        (True, False, "false", True),
        (False, True, "true", False),
        (None, False, None, False),
        (None, True, None, True),
        (None, True, "false", False),
        (None, False, "true", True),
        (None, None, "false", False),
        (None, None, "true", True),
        (None, None, None, True),
    ],
)
def test_resolve_notify_enabled_precedence(
    monkeypatch: pytest.MonkeyPatch,
    cli_value: bool | None,
    config_value: bool | None,
    env_value: str | None,
    expected: bool,
) -> None:
    if env_value is None:
        monkeypatch.delenv(ENV_NOTIFY, raising=False)
    else:
        monkeypatch.setenv(ENV_NOTIFY, env_value)
    assert (
        resolve_notify_enabled(cli_value=cli_value, config_value=config_value)
        == expected
    )


def test_should_notify_respects_enabled_and_headless(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CI", raising=False)
    assert should_notify(enabled=True) is True
    assert should_notify(enabled=False) is False
    monkeypatch.setenv("CI", "true")
    assert should_notify(enabled=True) is False


@patch("notifypy.Notify")
def test_send_notification_uses_backend(mock_notify_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_notify_cls.return_value = mock_instance

    send_notification("Title", "Message", enabled=True)

    mock_notify_cls.assert_called_once()
    mock_instance.send.assert_called_once()
    assert mock_instance.application_name == APP_NAME
    assert mock_instance.title == "Title"
    assert mock_instance.message == "Message"


@patch("notifypy.Notify", side_effect=RuntimeError("boom"))
def test_send_notification_swallows_backend_errors(
    mock_notify_cls: MagicMock,
) -> None:
    send_notification("Title", "Message", enabled=True)
    mock_notify_cls.assert_called_once()


def test_send_notification_skips_when_disabled() -> None:
    with patch("notifypy.Notify") as mock_notify_cls:
        send_notification("Title", "Message", enabled=False)
        mock_notify_cls.assert_not_called()


@patch("todos_tool.notifications.send_notification")
def test_notify_run_report_success(mock_send: MagicMock) -> None:
    report = RunReport(completed=["TASK-001", "TASK-002"])
    notify_run_report(report, enabled=True)
    mock_send.assert_called_once_with(
        "Todos run complete",
        "2 item(s) completed",
        enabled=True,
    )


@patch("todos_tool.notifications.send_notification")
def test_notify_run_report_issues(mock_send: MagicMock) -> None:
    report = RunReport(completed=["TASK-001"], failed=["TASK-002"], blocked=["TASK-003"])
    notify_run_report(report, enabled=True)
    mock_send.assert_called_once()
    assert mock_send.call_args.args[0] == "Todos run finished with issues"


@patch("todos_tool.notifications.send_notification")
def test_notify_interrupted_and_error(mock_send: MagicMock) -> None:
    notify_interrupted(enabled=True, message="Stopped")
    notify_error(enabled=True, message="Bad state")
    notify_commit_success(enabled=True, item_id="TASK-001", sha="abc12345")
    assert mock_send.call_count == 3
