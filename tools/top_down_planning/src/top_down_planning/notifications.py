"""Fail-soft desktop notifications for the top-down planning driver CLI."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

from top_down_planning.models import FinalStatus

if TYPE_CHECKING:
    from top_down_planning.models import PlanningReport

APP_NAME = "top-down-planning"
ENV_NOTIFY = "PLANNING_TOOL_NOTIFY"
DEFAULT_NOTIFY = True
MAX_MESSAGE_LENGTH = 240

_TRUTHY = frozenset({"true", "1", "yes", "on", "t", "y"})
_FALSY = frozenset({"false", "0", "no", "off", "f", "n"})


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUTHY


def _parse_optional_bool(value: str | None, *, name: str) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in _TRUTHY:
        return True
    if normalized in _FALSY:
        return False
    raise ValueError(f"Invalid value for {name}: {value!r} (expected true or false)")


def is_headless_environment() -> bool:
    if _env_truthy("CI"):
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
        return _parse_optional_bool(env_raw, name=ENV_NOTIFY)
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


def notify_planning_report(
    report: PlanningReport,
    *,
    enabled: bool,
    render_fallback: bool = False,
) -> None:
    if not should_notify(enabled=enabled):
        return

    status = report.status
    if status == FinalStatus.COMPLETE:
        artifact_hint = ""
        if report.artifacts:
            artifact_hint = f" Deliverable: {report.artifacts[0]}"
        if render_fallback:
            send_notification(
                "Planning complete (fallback artifact)",
                f"{report.items} items, {report.actionable_items} actionable."
                f"{artifact_hint}",
                enabled=enabled,
            )
            return
        send_notification(
            "Planning complete",
            f"{report.items} items, {report.actionable_items} actionable."
            f"{artifact_hint}",
            enabled=enabled,
        )
        return

    if status == FinalStatus.INCOMPLETE_LIMIT_REACHED:
        send_notification(
            "Planning stopped (limit reached)",
            f"{report.items} items after {report.iterations} iteration(s)",
            enabled=enabled,
        )
        return

    if status == FinalStatus.INCOMPLETE_BLOCKED:
        send_notification(
            "Planning incomplete",
            f"{report.blocked_items} blocked item(s); {report.items} total",
            enabled=enabled,
        )
        return

    if status == FinalStatus.FAILED:
        send_notification(
            "Planning failed",
            report.summary or "Planning run failed",
            enabled=enabled,
        )
        return

    send_notification(
        "Planning finished",
        report.summary or f"status={status.value}",
        enabled=enabled,
    )


def notify_interrupted(*, enabled: bool, message: str | None = None) -> None:
    send_notification(
        "Planning paused",
        message or "Interrupted — resume with --resume",
        enabled=enabled,
    )


def notify_error(*, enabled: bool, message: str) -> None:
    send_notification("Planning failed", message, enabled=enabled)
