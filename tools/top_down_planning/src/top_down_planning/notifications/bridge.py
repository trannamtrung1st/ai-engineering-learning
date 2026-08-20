"""Map persisted audit events to desktop notifications."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

from core_tools.observability import redact_value

from top_down_planning.notifications.desktop import send_desktop_notification
from top_down_planning.notifications.options import NotificationOptions
from top_down_planning.orchestrator import phases as run_phases

NotificationTier = Literal["terminal", "phase", "progress"]

_DEDUPE_WINDOW_SECONDS = 5.0

# Labels reused from map_audit_event where applicable; unmapped types defined here only.
_EVENT_LABELS: dict[str, str] = {
    "outcome_resolved": "outcome resolved",
    "run_failed": "run failed",
    "run_paused": "run paused",
    "production_failed": "production failed",
    "whole_plan_review_failed": "whole plan review failed",
    "whole_output_review_failed": "whole output review failed",
    "plan_amendment_failed": "plan amendment failed",
    "whole_plan_review_started": "whole-plan review loop started",
    "whole_plan_scope_review_started": "scope review started",
    "whole_output_scope_review_started": "scope review started",
    "whole_plan_review_approved": "whole plan review approved",
    "production_phase_started": "production phase started",
    "production_completed": "production completed",
    "whole_output_review_started": "whole-output review loop started",
    "whole_output_review_approved": "whole output review approved",
    "plan_amendment_started": "plan amendment started",
    "plan_amendment_completed": "plan amendment completed",
    "plan_amendment_production_resumed": "production resumed after amendment",
    "planning_limit_exceeded": "planning limit exceeded",
    "production_limit_exceeded": "production limit exceeded",
    "focused_review_limit_exceeded": "focused review limit exceeded",
    "whole_plan_review_limit_exceeded": "whole plan review limit exceeded",
    "whole_output_review_limit_exceeded": "whole output review limit exceeded",
    "plan_amendment_limit_exceeded": "plan amendment limit exceeded",
    "production_batch_recorded": "batch complete",
    "focused_review_approved": "focused review approved",
    "planning_candidate_ready": "planning candidate ready",
}

_TERMINAL_EVENTS: frozenset[str] = frozenset(
    {
        "outcome_resolved",
        "run_failed",
        "run_paused",
        "production_failed",
        "whole_plan_review_failed",
        "whole_output_review_failed",
        "plan_amendment_failed",
    }
)

_PHASE_EVENTS: frozenset[str] = frozenset(
    {
        "whole_plan_review_started",
        "whole_plan_scope_review_started",
        "whole_output_scope_review_started",
        "whole_plan_review_approved",
        "production_phase_started",
        "production_completed",
        "whole_output_review_started",
        "whole_output_review_approved",
        "plan_amendment_started",
        "plan_amendment_completed",
        "plan_amendment_production_resumed",
        "planning_limit_exceeded",
        "production_limit_exceeded",
        "focused_review_limit_exceeded",
        "whole_plan_review_limit_exceeded",
        "whole_output_review_limit_exceeded",
        "plan_amendment_limit_exceeded",
    }
)

_PROGRESS_EVENTS: frozenset[str] = frozenset(
    {
        "production_batch_recorded",
        "focused_review_approved",
        "planning_candidate_ready",
    }
)

_LIMIT_EXCEEDED_SUFFIX = "_limit_exceeded"

_TERMINAL_TITLES: dict[str, str] = {
    "outcome_resolved": "TDP run complete",
    "run_failed": "TDP run failed",
    "run_paused": "TDP run paused",
    "production_failed": "TDP production stopped",
    "whole_plan_review_failed": "TDP plan review failed",
    "whole_output_review_failed": "TDP output review failed",
    "plan_amendment_failed": "TDP amendment failed",
}

_PHASE_TITLES: dict[str, str] = {
    "whole_plan_review_started": "Plan review started",
    "whole_plan_scope_review_started": "Plan scope review started",
    "whole_output_scope_review_started": "Output scope review started",
    "whole_plan_review_approved": "Plan approved",
    "production_phase_started": "Production started",
    "production_completed": "Production finished",
    "whole_output_review_started": "Output review started",
    "whole_output_review_approved": "Output approved",
    "plan_amendment_started": "Plan amendment started",
    "plan_amendment_completed": "Amendment complete",
    "plan_amendment_production_resumed": "Production resumed",
    "planning_limit_exceeded": "Planning limit hit",
    "production_limit_exceeded": "Production limit hit",
    "focused_review_limit_exceeded": "Review limit hit",
    "whole_plan_review_limit_exceeded": "Whole plan review limit hit",
    "whole_output_review_limit_exceeded": "Whole output review limit hit",
    "plan_amendment_limit_exceeded": "Amendment limit hit",
}

_PROGRESS_TITLES: dict[str, str] = {
    "production_batch_recorded": "Batch complete",
    "focused_review_approved": "Focused review passed",
    "planning_candidate_ready": "Planning candidate ready",
}

_PHASE_LABELS: dict[str, str] = {
    run_phases.PLANNING: "planning",
    run_phases.WHOLE_PLAN_REVIEW: "whole plan review",
    run_phases.PLAN_VALIDATED: "plan validated",
    run_phases.PRODUCTION: "production",
    run_phases.PLAN_AMENDMENT: "plan amendment",
    run_phases.WHOLE_OUTPUT_REVIEW: "whole output review",
    run_phases.OUTPUT_VALIDATED: "output validated",
}


def short_run_id(run_id: str) -> str:
    """Return the random suffix from canonical run ids when present."""

    if run_id.startswith("run-") and run_id.count("-") >= 2:
        return run_id.rsplit("-", 1)[-1]
    return run_id


def phase_label(phase: str | None) -> str:
    if not phase:
        return "unknown"
    return _PHASE_LABELS.get(phase, phase.replace("_", " "))


@dataclass
class NotificationDedupeState:
    """Per-run dedupe state for notification bridge."""

    recent_keys: dict[tuple[str, str], float] = field(default_factory=dict)
    last_run_paused_at: float | None = None
    last_limit_exceeded_at: float | None = None

    def prune(self, *, now: float) -> None:
        expired = [
            key
            for key, ts in self.recent_keys.items()
            if now - ts > _DEDUPE_WINDOW_SECONDS
        ]
        for key in expired:
            del self.recent_keys[key]
        if (
            self.last_run_paused_at is not None
            and now - self.last_run_paused_at > _DEDUPE_WINDOW_SECONDS
        ):
            self.last_run_paused_at = None
        if (
            self.last_limit_exceeded_at is not None
            and now - self.last_limit_exceeded_at > _DEDUPE_WINDOW_SECONDS
        ):
            self.last_limit_exceeded_at = None


def _event_tier(event_type: str) -> NotificationTier | None:
    if event_type in _TERMINAL_EVENTS:
        return "terminal"
    if event_type in _PHASE_EVENTS:
        return "phase"
    if event_type in _PROGRESS_EVENTS:
        return "progress"
    return None


def _tier_enabled(options: NotificationOptions, tier: NotificationTier) -> bool:
    if tier == "terminal":
        return options.terminal
    if tier == "phase":
        return options.phase
    return options.progress


def _tier_allows_notification(
    options: NotificationOptions,
    tier: NotificationTier,
    *,
    event_type: str,
    event: dict[str, Any],
) -> bool:
    if not options.enabled:
        return False
    if event_type == "run_paused" and _is_user_cancelled_pause(event):
        return True
    return _tier_enabled(options, tier)


def _stable_key(event: dict[str, Any]) -> str:
    for field_name in ("batch_id", "loop_id", "amendment_id"):
        value = event.get(field_name)
        if isinstance(value, str) and value:
            return value
    return ""


def _is_user_cancelled_pause(event: dict[str, Any]) -> bool:
    stop = event.get("stop")
    return isinstance(stop, dict) and stop.get("code") == "user_cancelled"


def _detail_line(event: dict[str, Any]) -> str:
    if _is_user_cancelled_pause(event):
        return "cancelled by user"
    stop = event.get("stop")
    if isinstance(stop, dict):
        for key in ("message", "reason", "code"):
            value = stop.get(key)
            if isinstance(value, str) and value.strip():
                return str(redact_value(value.strip()))
    for key in ("outcome", "reason", "until"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return str(redact_value(value.strip()))
    label = _EVENT_LABELS.get(str(event.get("type") or ""), "")
    return str(redact_value(label))


def _format_message(*, run_id: str, phase: str | None, detail: str) -> str:
    phase_text = phase_label(phase)
    short_id = short_run_id(run_id)
    if detail:
        return f"{short_id}: {phase_text} — {detail}"
    return f"{short_id}: {phase_text}"


def _title_for_event(
    event_type: str,
    tier: NotificationTier,
    *,
    event: dict[str, Any],
) -> str:
    if event_type == "run_paused" and _is_user_cancelled_pause(event):
        return "TDP run cancelled"
    if tier == "terminal":
        return _TERMINAL_TITLES.get(event_type, "TDP run update")
    if tier == "phase":
        return _PHASE_TITLES.get(event_type, "TDP phase update")
    return _PROGRESS_TITLES.get(event_type, "TDP progress update")


def _should_defer_output_approval(
    event_type: str,
    *,
    run: dict[str, Any] | None,
    options: NotificationOptions,
) -> bool:
    if event_type != "whole_output_review_approved":
        return False
    if not options.enabled or not options.terminal:
        return False
    return run is not None and str(run.get("status") or "") == "completed"


def _should_skip_dedupe(
    event_type: str,
    *,
    state: NotificationDedupeState,
    now: float,
    stable_key: str,
    run: dict[str, Any] | None,
    options: NotificationOptions,
) -> bool:
    dedupe_key = (event_type, stable_key)
    if dedupe_key in state.recent_keys and now - state.recent_keys[dedupe_key] <= _DEDUPE_WINDOW_SECONDS:
        return True

    if event_type.endswith(_LIMIT_EXCEEDED_SUFFIX):
        if (
            state.last_run_paused_at is not None
            and now - state.last_run_paused_at <= _DEDUPE_WINDOW_SECONDS
        ):
            return True

    if event_type == "run_paused":
        if (
            state.last_limit_exceeded_at is not None
            and now - state.last_limit_exceeded_at <= _DEDUPE_WINDOW_SECONDS
        ):
            return True

    if _should_defer_output_approval(event_type, run=run, options=options):
        return True

    return False


def handle_audit_event(
    event: dict[str, Any],
    *,
    run_id: str,
    options: NotificationOptions,
    phase: str | None = None,
    run: dict[str, Any] | None = None,
    dedupe_state: NotificationDedupeState | None = None,
) -> bool:
    """Map an audit event to a desktop notification; return True when sent."""

    event_type = str(event.get("type") or "")
    tier = _event_tier(event_type)
    if tier is None or not _tier_allows_notification(
        options,
        tier,
        event_type=event_type,
        event=event,
    ):
        return False

    state = dedupe_state or NotificationDedupeState()
    now = time.monotonic()
    state.prune(now=now)

    stable = _stable_key(event)
    if _should_skip_dedupe(
        event_type,
        state=state,
        now=now,
        stable_key=stable,
        run=run,
        options=options,
    ):
        return False

    title = _title_for_event(event_type, tier, event=event)
    detail = _detail_line(event)
    run_phase = phase
    if not run_phase:
        event_phase = event.get("phase")
        if isinstance(event_phase, str) and event_phase:
            run_phase = event_phase
    message = _format_message(run_id=run_id, phase=run_phase, detail=detail)

    sent = send_desktop_notification(title, message)
    if sent:
        state.recent_keys[(event_type, stable)] = now
        if event_type == "run_paused":
            state.last_run_paused_at = now
        if event_type.endswith(_LIMIT_EXCEEDED_SUFFIX):
            state.last_limit_exceeded_at = now
    return sent
