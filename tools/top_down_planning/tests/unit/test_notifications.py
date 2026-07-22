"""Unit tests for desktop notification helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from top_down_planning.models import FinalStatus, PlanningReport
from top_down_planning.notifications import (
    APP_NAME,
    ENV_NOTIFY,
    notify_error,
    notify_interrupted,
    notify_planning_report,
    resolve_notify_enabled,
    send_notification,
    should_notify,
)


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


@patch("top_down_planning.notifications.send_notification")
def test_notify_planning_report_complete(mock_send: MagicMock) -> None:
    report = PlanningReport(
        status=FinalStatus.COMPLETE,
        items=5,
        actionable_items=3,
        artifacts=["planning-output/implementation-plan.md"],
    )
    notify_planning_report(report, enabled=True)
    mock_send.assert_called_once()
    assert mock_send.call_args.args[0] == "Planning complete"


@patch("top_down_planning.notifications.send_notification")
def test_notify_planning_report_fallback(mock_send: MagicMock) -> None:
    report = PlanningReport(
        status=FinalStatus.COMPLETE,
        items=2,
        actionable_items=2,
        artifacts=["planning-output/.planning-output/fallback.md"],
        render_fallback=True,
    )
    notify_planning_report(report, enabled=True, render_fallback=True)
    mock_send.assert_called_once()
    assert mock_send.call_args.args[0] == "Planning complete (fallback artifact)"


@patch("top_down_planning.notifications.send_notification")
def test_notify_interrupted_and_error(mock_send: MagicMock) -> None:
    notify_interrupted(enabled=True)
    notify_error(enabled=True, message="Planning failed")
    assert mock_send.call_count == 2
