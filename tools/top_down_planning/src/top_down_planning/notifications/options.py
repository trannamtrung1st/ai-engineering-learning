"""Notification presentation options."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NotificationOptions:
    """Desktop notification tier toggles for blocking run/resume."""

    enabled: bool = True
    terminal: bool = True
    phase: bool = True
    progress: bool = False
