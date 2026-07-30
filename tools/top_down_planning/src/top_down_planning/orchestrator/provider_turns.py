"""Observe provider turns and run-store mutations during orchestration."""

from __future__ import annotations

from typing import Any

from top_down_planning.orchestrator.errors import ProviderRunError
from top_down_planning.persistence.interface import RunStore
from core_tools.provider import Provider


def extract_completion_signal_from_text(
    text: str | None,
    *,
    allowed: frozenset[str],
) -> str | None:
    """Return a completion signal when *text* is exactly one allowed token."""

    if not text:
        return None

    stripped = text.strip()
    if stripped in allowed:
        return stripped

    for line in text.splitlines():
        line_stripped = line.strip()
        if line_stripped in allowed:
            return line_stripped

    return None


def resolve_turn_signal(
    *,
    done_signal: str | None,
    assistant_text: str,
    done_text: str | None,
    allowed: frozenset[str],
) -> str | None:
    """Resolve a turn completion signal from provider metadata and text."""

    if done_signal is not None:
        normalized = str(done_signal)
        if normalized in allowed:
            return normalized

    for text in (assistant_text, done_text):
        signal = extract_completion_signal_from_text(text, allowed=allowed)
        if signal is not None:
            return signal

    return None


class TurnTextAccumulator:
    """Collect assistant/done text while streaming a provider turn."""

    def __init__(self) -> None:
        self._assistant_parts: list[str] = []
        self._done_text: str | None = None
        self._done_signal: str | None = None

    def ingest(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "")
        if event_type == "assistant":
            text = event.get("text")
            if isinstance(text, str) and text:
                self._assistant_parts.append(text)
            return

        if event_type != "done":
            return

        text = event.get("text")
        if isinstance(text, str):
            self._done_text = text

        signal = event.get("signal")
        if signal is not None:
            self._done_signal = str(signal)

    @property
    def assistant_text(self) -> str:
        return "\n".join(self._assistant_parts)

    def resolve_signal(self, allowed: frozenset[str]) -> str | None:
        return resolve_turn_signal(
            done_signal=self._done_signal,
            assistant_text=self.assistant_text,
            done_text=self._done_text,
            allowed=allowed,
        )


def consume_provider_turn(
    provider: Provider,
    session_id: str,
    *,
    allowed_signals: frozenset[str],
) -> str | None:
    """Drain one provider turn and resolve its completion signal."""

    accumulator = TurnTextAccumulator()
    for event in provider.stream_events(session_id):
        event_type = str(event.get("type") or "")
        if event_type == "error":
            text = event.get("text") or "provider error"
            raise ProviderRunError(str(text))
        if event_type in {"assistant", "done"}:
            accumulator.ingest(event)
        if event_type == "done":
            if event.get("is_error"):
                text = event.get("text") or "provider turn failed"
                raise ProviderRunError(str(text))
    return accumulator.resolve_signal(allowed_signals)


def find_pending_focused_review_loop_id(
    store: RunStore,
    run_id: str,
    *,
    review_type: str,
) -> str | None:
    """Return a focused review loop awaiting its first reviewer session."""

    for review in store.list_reviews(run_id):
        if str(review.get("type") or "") != review_type:
            continue
        if str(review.get("status") or "") != "pending":
            continue
        if review.get("reviewer_session_id") is not None:
            continue
        loop_id = review.get("id")
        if loop_id is None:
            continue
        return str(loop_id)
    return None


def run_pending_focused_review(
    store: RunStore,
    run_id: str,
    provider: Provider,
    *,
    review_type: str,
) -> None:
    """Run a focused review loop when the store shows one is due."""

    from top_down_planning.orchestrator.focused_review import FocusedReviewOrchestrator

    loop_id = find_pending_focused_review_loop_id(
        store,
        run_id,
        review_type=review_type,
    )
    if loop_id is None:
        return

    result = FocusedReviewOrchestrator(store, run_id, provider).run(loop_id)
    if not result.ok:
        raise ProviderRunError(
            result.reason or f"{review_type} focused review did not complete successfully"
        )


def review_decision_from_store(
    store: RunStore,
    run_id: str,
    loop_id: str,
) -> str | None:
    """Return a terminal review decision recorded in the run store."""

    review = store.load_review(run_id, loop_id)
    status = str(review.get("status") or "")
    if status == "pending":
        return None
    return status


def count_new_plan_items(
    before_item_ids: set[str],
    after_item_ids: set[str],
) -> int:
    """Count net-new plan items added during a provider turn."""

    return len(after_item_ids - before_item_ids)


def sync_planning_items_added(
    store: RunStore,
    run_id: str,
    *,
    before_item_ids: set[str],
    persist_metrics: Any,
    append_event: Any,
) -> None:
    """Record planning expansion metrics after CLI plan mutations."""

    after_item_ids = set(store.load_plan_model(run_id).items.keys())
    added = count_new_plan_items(before_item_ids, after_item_ids)
    if added <= 0:
        return

    run = store.load_run(run_id)
    planning = run.get("planning") or {}
    metrics = {
        "agent_turns": int(planning.get("agent_turns") or 0),
        "items_added": int(planning.get("items_added") or 0) + added,
    }
    persist_metrics(run_id, metrics)
    append_event(
        "planning_expansion_recorded",
        items_added=metrics["items_added"],
        added_items=added,
    )
