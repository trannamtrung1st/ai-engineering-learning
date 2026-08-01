"""CLI-only notification outcomes (cancel, partial until milestone)."""

from __future__ import annotations

from typing import Any, Literal

from top_down_planning.notifications.bridge import phase_label, short_run_id
from top_down_planning.notifications.desktop import send_desktop_notification
from top_down_planning.notifications.options import NotificationOptions

OutcomeKind = Literal["cancelled", "target_reached"]


def notify_run_outcome(
    kind: OutcomeKind,
    *,
    run_id: str,
    run: dict[str, Any],
    options: NotificationOptions,
    until: str | None = None,
) -> bool:
    """Send a desktop notification for CLI-only run outcomes."""

    if not options.enabled:
        return False

    phase = phase_label(str(run.get("phase") or "") or None)
    short_id = short_run_id(run_id)
    if kind == "cancelled":
        title = "TDP run cancelled"
        message = f"{short_id}: {phase} — cancelled by user"
        return send_desktop_notification(title, message)

    # target_reached uses terminal tier whenever master switch is on (locked decision #2).
    if kind == "target_reached":
        status = str(run.get("status") or "")
        if status in {"completed", "failed", "paused"}:
            return False
        until_text = until or "milestone"
        title = "TDP milestone reached"
        message = f"{short_id}: {phase} — reached target {until_text!r}"
        return send_desktop_notification(title, message)

    return False
