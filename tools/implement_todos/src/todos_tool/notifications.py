"""Fail-soft desktop notifications for the todos driver CLI."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

from todos_tool.flags import env_truthy, parse_optional_bool

if TYPE_CHECKING:
    from todos_tool.orchestrator import RunReport

APP_NAME = "todos-tool"
ENV_NOTIFY = "TODOS_TOOL_NOTIFY"
DEFAULT_NOTIFY = True
MAX_MESSAGE_LENGTH = 240


def is_headless_environment() -> bool:
    if env_truthy("CI"):
        return True
    if sys.platform.startswith("linux"):
        return not (
            os.environ.get("DISPLAY")
            or os.environ.get("WAYLAND_DISPLAY")
            or os.environ.get("DBUS_SESSION_BUS_ADDRESS")
        )
    return False


def resolve_notify_enabled(
    *,
    cli_value: bool | None,
    config_value: bool | None,
    default: bool = DEFAULT_NOTIFY,
) -> bool:
    if cli_value is not None:
        return cli_value
    env_raw = os.environ.get(ENV_NOTIFY)
    if env_raw is not None and env_raw.strip():
        return parse_optional_bool(env_raw, name=ENV_NOTIFY)
    if config_value is not None:
        return config_value
    return default


def should_notify(*, enabled: bool) -> bool:
    return enabled and not is_headless_environment()


def _truncate(text: str, *, limit: int = MAX_MESSAGE_LENGTH) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def send_notification(
    title: str,
    message: str,
    *,
    enabled: bool,
) -> None:
    if not should_notify(enabled=enabled):
        return
    try:
        from notifypy import Notify
    except ImportError:
        return

    try:
        notification = Notify()
        notification.application_name = APP_NAME
        notification.title = _truncate(title, limit=64)
        notification.message = _truncate(message)
        notification.send()
    except Exception:
        return


def notify_run_report(report: RunReport, *, enabled: bool) -> None:
    if not should_notify(enabled=enabled):
        return
    completed = len(report.completed)
    failed = len(report.failed)
    retryable = len(report.retryable)
    blocked = len(report.blocked)
    if failed or retryable or blocked:
        parts = []
        if failed:
            parts.append(f"{failed} failed")
        if retryable:
            parts.append(f"{retryable} retryable")
        if blocked:
            parts.append(f"{blocked} blocked")
        send_notification(
            "Todos run finished with issues",
            f"{completed} completed; {', '.join(parts)}",
            enabled=enabled,
        )
        return
    send_notification(
        "Todos run complete",
        f"{completed} item(s) completed",
        enabled=enabled,
    )


def notify_interrupted(*, enabled: bool, message: str | None = None) -> None:
    send_notification(
        "Todos run paused",
        message or "Interrupted — resume with todos-tool resume",
        enabled=enabled,
    )


def notify_error(*, enabled: bool, message: str) -> None:
    send_notification("Todos run failed", message, enabled=enabled)


def notify_commit_success(*, enabled: bool, item_id: str, sha: str) -> None:
    send_notification(
        "Todo committed",
        f"{item_id} committed as {sha[:8]}",
        enabled=enabled,
    )


def notify_commit_failure(*, enabled: bool, item_id: str, message: str) -> None:
    send_notification(
        "Todo commit failed",
        f"{item_id}: {message}",
        enabled=enabled,
    )
