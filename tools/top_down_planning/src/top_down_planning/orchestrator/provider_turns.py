"""Observe provider turns and run-store mutations during orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core_tools.provider import Provider
from core_tools.provider.errors import ProviderSessionNotFoundError
from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.orchestrator.capability import (
    bind_provider_capability,
    issue_session_capability,
)
from top_down_planning.orchestrator.errors import (
    ProducerReplacementBlocked,
    ProviderRunError,
    SessionRecoveryExhausted,
    SessionRecoveryPaused,
)
from top_down_planning.orchestrator.session_recovery_enforcement import (
    assert_replacement_allowed,
    fail_session_recovery_exhausted,
    finalize_successful_phase_action_turn,
    mark_replacement_attempt,
)
from top_down_planning.orchestrator.recovery_manifest import (
    build_planner_recovery_manifest,
    build_producer_recovery_manifest,
    build_reviewer_recovery_manifest,
)
from top_down_planning.orchestrator.reviewer_session import reviewer_loop_provider_session_id
from top_down_planning.orchestrator.run_transitions import generate_phase_action_id
from top_down_planning.orchestrator.session_lineage import emit_session_replacement_failed
from top_down_planning.orchestrator.session_recovery import (
    PrimarySessionRecoverySpec,
    ReviewerSessionRecoverySpec,
    replace_primary_session,
    replace_reviewer_session,
)
from top_down_planning.persistence.interface import RunStore
from top_down_planning.workspace import run_workspace


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


def ensure_phase_action_id(store: RunStore, run_id: str) -> str:
    """Assign or reuse the logical phase action id for a provider turn (§13.1)."""

    run = store.load_run(run_id)
    existing = run.get("phase_action_id")
    if isinstance(existing, str) and existing.strip():
        return existing

    action_id = generate_phase_action_id()
    expected_revision = int(run["revision"])
    updated = dict(run)
    updated["revision"] = expected_revision + 1
    updated["phase_action_id"] = action_id
    store.save_run(run_id, updated, expected_revision)
    store.append_event(
        run_id,
        {
            "type": "phase_action_assigned",
            "run_id": run_id,
            "phase_action_id": action_id,
        },
    )
    return action_id


def clear_phase_action_id(store: RunStore, run_id: str) -> None:
    """Clear phase_action_id after a provider turn completes."""

    run = store.load_run(run_id)
    if run.get("phase_action_id") is None:
        return

    expected_revision = int(run["revision"])
    updated = dict(run)
    updated["revision"] = expected_revision + 1
    updated["phase_action_id"] = None
    store.save_run(run_id, updated, expected_revision)


@dataclass(frozen=True)
class ProviderTurnOutcome:
    signal: str | None
    session_id: str
    replaced: bool = False
    domain_budget_committed: bool = False
    capability_token: str | None = None


def _recovery_role_phase_loop(
    recovery: PrimarySessionRecoverySpec | ReviewerSessionRecoverySpec,
) -> tuple[str, str, str | None]:
    if isinstance(recovery, PrimarySessionRecoverySpec):
        return recovery.role, recovery.phase, None
    return "reviewer", recovery.phase, recovery.loop_id


def _finalize_phase_action_turn(
    store: RunStore,
    run_id: str,
    phase_action_id: str,
) -> bool:
    return finalize_successful_phase_action_turn(store, run_id, phase_action_id)


def _drain_provider_turn(
    provider: Provider,
    session_id: str,
    *,
    allowed_signals: frozenset[str],
) -> str | None:
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


def consume_provider_turn(
    provider: Provider,
    session_id: str,
    *,
    allowed_signals: frozenset[str],
    store: RunStore | None = None,
    run_id: str | None = None,
) -> str | None:
    """Drain one provider turn and resolve its completion signal."""

    if store is not None and run_id is not None:
        phase_action_id = ensure_phase_action_id(store, run_id)
    else:
        phase_action_id = None

    signal = _drain_provider_turn(
        provider,
        session_id,
        allowed_signals=allowed_signals,
    )
    if store is not None and run_id is not None and phase_action_id is not None:
        _finalize_phase_action_turn(store, run_id, phase_action_id)
    elif store is not None and run_id is not None:
        clear_phase_action_id(store, run_id)
    return signal


def consume_provider_turn_with_session_recovery(
    store: RunStore,
    run_id: str,
    provider: Provider,
    session_id: str,
    *,
    allowed_signals: frozenset[str],
    recovery: PrimarySessionRecoverySpec | ReviewerSessionRecoverySpec,
) -> ProviderTurnOutcome:
    """Resume an existing session, replacing it once when the provider reports not-found."""

    ensure_phase_action_id(store, run_id)
    run = store.load_run(run_id)
    phase_action_id = str(run.get("phase_action_id") or generate_phase_action_id())
    role, phase, loop_id = _recovery_role_phase_loop(recovery)

    try:
        signal = _drain_provider_turn(
            provider,
            session_id,
            allowed_signals=allowed_signals,
        )
        domain_budget_committed = _finalize_phase_action_turn(store, run_id, phase_action_id)
        return ProviderTurnOutcome(
            signal=signal,
            session_id=session_id,
            replaced=False,
            domain_budget_committed=domain_budget_committed,
        )
    except ProviderSessionNotFoundError:
        assert_replacement_allowed(
            store,
            run_id,
            phase_action_id=phase_action_id,
            phase=phase,
            role=role,
            provider_session_id=session_id,
            loop_id=loop_id,
        )
        mark_replacement_attempt(store, run_id, phase_action_id)
        manifest = recovery.build_recovery_manifest(phase_action_id)
        try:
            if isinstance(recovery, PrimarySessionRecoverySpec):
                new_session_id = replace_primary_session(
                    store,
                    run_id,
                    provider,
                    role=recovery.role,
                    phase=recovery.phase,
                    old_provider_session_id=session_id,
                    phase_action_id=phase_action_id,
                    append_event=recovery.append_event,
                    model=recovery.model,
                    manifest=manifest,
                    workspace=recovery.workspace,
                )
            else:
                loop = ReviewLoop.from_dict(store.load_review(run_id, recovery.loop_id))
                new_session_id = replace_reviewer_session(
                    store,
                    run_id,
                    provider,
                    loop=loop,
                    phase=recovery.phase,
                    old_provider_session_id=session_id,
                    phase_action_id=phase_action_id,
                    append_event=recovery.append_event,
                    model=recovery.model,
                    manifest=manifest,
                )
        except ProducerReplacementBlocked as exc:
            _emit_replacement_blocked(store, run_id, recovery, phase_action_id, session_id, str(exc))
            raise ProviderRunError(str(exc)) from exc
        except SessionRecoveryPaused:
            raise

        role_for_cap, phase_for_cap, loop_id_for_cap = _recovery_role_phase_loop(recovery)
        session_kind = (
            "primary" if isinstance(recovery, PrimarySessionRecoverySpec) else "reviewer"
        )
        capability_token = issue_session_capability(
            store,
            run_id,
            role=role_for_cap,
            phase=phase_for_cap,
            session_id=new_session_id,
            session_kind=session_kind,
            loop_id=loop_id_for_cap,
        )
        bind_provider_capability(provider, capability_token)

        try:
            signal = _drain_provider_turn(
                provider,
                new_session_id,
                allowed_signals=allowed_signals,
            )
        except ProviderSessionNotFoundError as exc:
            fail_session_recovery_exhausted(
                store,
                run_id,
                phase=phase,
                role=role,
                phase_action_id=phase_action_id,
                message=(
                    "replacement provider session is missing for "
                    f"phase_action_id {phase_action_id}"
                ),
                loop_id=loop_id,
            )
            raise SessionRecoveryExhausted(str(exc)) from exc

        domain_budget_committed = _finalize_phase_action_turn(store, run_id, phase_action_id)
        return ProviderTurnOutcome(
            signal=signal,
            session_id=new_session_id,
            replaced=True,
            domain_budget_committed=domain_budget_committed,
            capability_token=capability_token,
        )


def _emit_replacement_blocked(
    store: RunStore,
    run_id: str,
    recovery: PrimarySessionRecoverySpec | ReviewerSessionRecoverySpec,
    phase_action_id: str,
    provider_session_id: str,
    reason: str,
) -> None:
    run = store.load_run(run_id)
    if isinstance(recovery, PrimarySessionRecoverySpec):
        from top_down_planning.persistence.session_bindings import get_primary_binding

        binding = get_primary_binding(run, recovery.role)
        if binding is None:
            return
        emit_session_replacement_failed(
            store,
            run_id,
            phase=recovery.phase,
            role=recovery.role,
            session_instance_id=binding.session_instance_id,
            generation=binding.generation,
            reason=reason,
            provider_session_id=provider_session_id,
            phase_action_id=phase_action_id,
        )
        return

    loop = ReviewLoop.from_dict(store.load_review(run_id, recovery.loop_id))
    binding = loop.reviewer_binding
    if binding is None:
        return
    emit_session_replacement_failed(
        store,
        run_id,
        phase=recovery.phase,
        role="reviewer",
        session_instance_id=binding.session_instance_id,
        generation=binding.generation,
        reason=reason,
        provider_session_id=provider_session_id,
        phase_action_id=phase_action_id,
        loop_id=recovery.loop_id,
    )


def build_planner_turn_recovery(
    store: RunStore,
    run_id: str,
    *,
    phase: str,
    expected_next_action: str,
    append_event: Any,
    model: str | None,
) -> PrimarySessionRecoverySpec:
    config = store.load_resolved_config(run_id)
    plan = store.load_plan_model(run_id)

    def build_manifest(phase_action_id: str) -> dict[str, Any]:
        return build_planner_recovery_manifest(
            store,
            run_id,
            config,
            plan,
            phase_action_id=phase_action_id,
            expected_next_action=expected_next_action,
        )

    return PrimarySessionRecoverySpec(
        role="planner",
        phase=phase,
        expected_next_action=expected_next_action,
        append_event=append_event,
        model=model,
        build_recovery_manifest=build_manifest,
    )


def build_producer_turn_recovery(
    store: RunStore,
    run_id: str,
    *,
    phase: str,
    expected_next_action: str,
    append_event: Any,
    model: str | None,
) -> PrimarySessionRecoverySpec:
    config = store.load_resolved_config(run_id)
    plan = store.load_plan_model(run_id)
    workspace = run_workspace(store.load_run(run_id))

    def build_manifest(phase_action_id: str) -> dict[str, Any]:
        return build_producer_recovery_manifest(
            store,
            run_id,
            config,
            plan,
            phase_action_id=phase_action_id,
            expected_next_action=expected_next_action,
        )

    return PrimarySessionRecoverySpec(
        role="producer",
        phase=phase,
        expected_next_action=expected_next_action,
        append_event=append_event,
        model=model,
        build_recovery_manifest=build_manifest,
        workspace=workspace,
    )


def build_reviewer_turn_recovery(
    store: RunStore,
    run_id: str,
    *,
    loop_id: str,
    phase: str,
    expected_next_action: str,
    append_event: Any,
    model: str | None,
    review_package: dict[str, Any],
) -> ReviewerSessionRecoverySpec:
    config = store.load_resolved_config(run_id)
    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))

    def build_manifest(phase_action_id: str) -> dict[str, Any]:
        return build_reviewer_recovery_manifest(
            store,
            run_id,
            config,
            loop,
            review_package=review_package,
            phase_action_id=phase_action_id,
            expected_next_action=expected_next_action,
        )

    return ReviewerSessionRecoverySpec(
        phase=phase,
        loop_id=loop_id,
        expected_next_action=expected_next_action,
        append_event=append_event,
        model=model,
        build_recovery_manifest=build_manifest,
    )


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
        if reviewer_loop_provider_session_id(review) is not None:
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
