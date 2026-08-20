"""Fail-soft desktop notification transport."""

from __future__ import annotations

import os
import sys

from core_tools.observability import redact_value

_MAX_TITLE_LENGTH = 120
_MAX_MESSAGE_LENGTH = 240
_APPLICATION_NAME = "tdp"


def _notifications_suppressed() -> bool:
    if os.environ.get("CI", "").lower() in {"1", "true", "yes"}:
        return True
    if sys.platform.startswith("linux"):
        if not any(
            os.environ.get(key)
            for key in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS")
        ):
            return True
    return False


def send_desktop_notification(title: str, message: str) -> bool:
    """Send a desktop notification when supported; return False on any failure."""

    if _notifications_suppressed():
        return False

    title = str(redact_value(title))[:_MAX_TITLE_LENGTH]
    message = str(redact_value(message))[:_MAX_MESSAGE_LENGTH]

    try:
        from notifypy import Notify
    except ImportError:
        return False

    try:
        notification = Notify()
        notification.title = title
        notification.message = message
        notification.application_name = _APPLICATION_NAME
        return bool(notification.send())
    except Exception:
        return False
