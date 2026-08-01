"""RunStore decorator that sends desktop notifications on audit events."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from top_down_planning.persistence.interface import RunStore

from top_down_planning.notifications.bridge import NotificationDedupeState, handle_audit_event
from top_down_planning.notifications.options import NotificationOptions
from top_down_planning.observability import ObservabilityContext, wrap_store_with_observability


@dataclass
class NotificationContext:
    """Active notification settings and per-run dedupe state."""

    options: NotificationOptions
    _dedupe_by_run: dict[str, NotificationDedupeState] = field(default_factory=dict)

    @property
    def enabled(self) -> bool:
        return self.options.enabled

    def dedupe_state_for(self, run_id: str) -> NotificationDedupeState:
        if run_id not in self._dedupe_by_run:
            self._dedupe_by_run[run_id] = NotificationDedupeState()
        return self._dedupe_by_run[run_id]


class NotifyingRunStore:
    """RunStore decorator that mirrors append_event to desktop notifications."""

    def __init__(self, store: RunStore, context: NotificationContext) -> None:
        self._store = store
        self._context = context

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)

    def append_event(self, run_id: str, event: dict[str, Any]) -> None:
        self._store.append_event(run_id, event)
        if not self._context.enabled:
            return
        try:
            run = self._store.load_run(run_id)
            phase = str(run.get("phase") or "") or None
            handle_audit_event(
                event,
                run_id=run_id,
                options=self._context.options,
                phase=phase,
                run=run,
                dedupe_state=self._context.dedupe_state_for(run_id),
            )
        except Exception:
            return


def wrap_store_with_notifications(
    store: RunStore,
    context: NotificationContext,
) -> RunStore:
    """Wrap a run store to send desktop notifications on append_event."""

    if isinstance(store, NotifyingRunStore):
        return store
    return NotifyingRunStore(store, context)


def wrap_run_store(
    store: RunStore,
    *,
    observability: ObservabilityContext,
    notifications: NotificationContext | None,
) -> RunStore:
    """Compose observability (inner) and notifications (outer) store decorators."""

    wrapped = wrap_store_with_observability(store, observability)
    if notifications is not None and notifications.enabled:
        wrapped = wrap_store_with_notifications(wrapped, notifications)
    return wrapped
