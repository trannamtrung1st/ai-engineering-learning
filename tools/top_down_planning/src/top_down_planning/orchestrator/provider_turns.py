"""Observe provider turns and run-store mutations during orchestration."""

from __future__ import annotations

import multiprocessing
import os
import pickle
import queue
import threading
import time
from collections.abc import Callable, Iterator
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core_tools.provider import Provider
from core_tools.provider.errors import (
    ProviderReplacementIdentityError,
    ProviderSessionNotFoundError,
    ProviderTurnStalledError,
)
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
from top_down_planning.orchestrator.producer_session import (
    PRODUCER_BATCH_COMPLETE_SIGNAL,
    PRODUCER_COMPLETION_COMPLETE_SIGNAL,
)
from top_down_planning.orchestrator.reviewer_session import (
    OWNER_FINDING_ACTION_COMPLETE_SIGNAL,
    REVIEWER_DECISION_COMPLETE_SIGNAL,
    reviewer_loop_provider_session_id,
)
from top_down_planning.orchestrator.run_transitions import generate_phase_action_id
from top_down_planning.persistence.commit import CommitSpec
from top_down_planning.orchestrator.session_lineage import emit_session_replacement_failed
from top_down_planning.orchestrator.session_events import (
    discard_unbound_provider_session,
    sync_persisted_session_id,
    sync_reviewer_loop_session_id,
)
from top_down_planning.orchestrator.session_recovery import (
    PrimarySessionRecoverySpec,
    ReviewerSessionRecoverySpec,
    recovery_reason_for_session_loss,
    replace_primary_session,
    replace_reviewer_session,
)
from top_down_planning.persistence.interface import RunStore
from top_down_planning.workspace import run_workspace

_NO_COMPLETION_SIGNALS = frozenset[str]()
NO_COMPLETION_SIGNALS = _NO_COMPLETION_SIGNALS


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
    store.commit(
        run_id,
        CommitSpec(
            run=updated,
            run_expected_revision=expected_revision,
            events=[
                {
                    "type": "phase_action_assigned",
                    "run_id": run_id,
                    "phase_action_id": action_id,
                }
            ],
        ),
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


def _call_provider_lifecycle(
    provider: Provider,
    method_name: str,
    session_id: str,
    *,
    timeout: float,
) -> None:
    """Invoke a timeout-aware provider lifecycle method. No signature fallback."""

    getattr(provider, method_name)(session_id, timeout=timeout)


def _abort_provider_turn(provider: Provider, session_id: str) -> None:
    """Stop an in-flight provider turn when orchestration closes the turn early."""

    _call_provider_lifecycle(
        provider,
        "abort_turn",
        session_id,
        timeout=ABORT_TURN_SECONDS,
    )


def _terminate_provider_session(provider: Provider, session_id: str) -> None:
    _call_provider_lifecycle(
        provider,
        "terminate_session",
        session_id,
        timeout=ABORT_TURN_SECONDS,
    )


def _wait_provider_turn_settled(provider: Provider, session_id: str) -> None:
    """Block until the provider session has no in-flight collector turn."""

    provider.wait_turn_settled(session_id, timeout=ABORT_TURN_SECONDS)


def _session_binding_syncer(
    provider: Provider,
    store: RunStore,
    run_id: str,
    recovery: PrimarySessionRecoverySpec | ReviewerSessionRecoverySpec,
) -> Callable[[str], str] | None:
    if isinstance(recovery, PrimarySessionRecoverySpec):
        role = recovery.role

        def sync_primary(session_id: str) -> str:
            return sync_persisted_session_id(
                provider,
                store,
                run_id,
                session_id,
                role=role,
            )

        return sync_primary

    loop_id = recovery.loop_id

    def sync_reviewer(session_id: str) -> str:
        return sync_reviewer_loop_session_id(
            provider,
            store,
            run_id,
            loop_id,
            session_id,
        )

    return sync_reviewer


BOUNDARY_POLL_JOIN_SECONDS = 2.0
ABORT_TURN_SECONDS = 2.0
PROVIDER_EVENT_PUMP_NAME = "tdp-provider-event-pump"
PROVIDER_ABORT_THREAD_NAME = "tdp-provider-abort"
PROVIDER_TERMINATE_THREAD_NAME = "tdp-provider-terminate"
BOUNDARY_POLL_THREAD_NAME = "tdp-boundary-poll"
BOUNDARY_WORKER_NAME = "tdp-boundary-worker"
_OWNED_BOUNDARY_PGIDS: set[int] = set()
_BOUNDARY_CANCEL: ContextVar[threading.Event | None] = ContextVar(
    "tdp_boundary_cancel",
    default=None,
)


def boundary_cancel_event() -> threading.Event | None:
    """Stop event for the in-flight store-driven boundary probe, if any."""

    return _BOUNDARY_CANCEL.get()


@dataclass
class _BoundaryPollState:
    stop: threading.Event
    done: threading.Event
    thread: threading.Thread | None = None
    pump_thread: threading.Thread | None = None
    worker: Any | None = None
    on_boundary: Callable[[], str | None] | None = None
    signal: str | None = None
    error: BaseException | None = None
    heartbeat: float = field(default_factory=time.monotonic)


def _boundary_worker_loop(conn: Any) -> None:
    while True:
        try:
            message = conn.recv()
        except EOFError:
            return
        if not message or message[0] == "stop":
            return
        callback = message[1]
        try:
            conn.send(("ok", callback()))
        except BaseException as exc:
            try:
                conn.send(("err", exc))
            except Exception:
                conn.send(("err", ProviderRunError(f"boundary probe failed: {exc!r}")))


class BoundaryWorker:
    """One spawn process reused for every store probe in a provider turn."""

    def __init__(self) -> None:
        self.proc: Any | None = None
        self.parent_conn: Any | None = None
        self._child_conn: Any | None = None
        self._pgid: int | None = None

    def start(self) -> None:
        if self.proc is not None and self.proc.is_alive():
            return
        ctx = multiprocessing.get_context("spawn")
        self.parent_conn, self._child_conn = ctx.Pipe(duplex=True)
        self.proc = ctx.Process(
            target=_boundary_worker_loop,
            args=(self._child_conn,),
            name=BOUNDARY_WORKER_NAME,
        )
        try:
            self.proc.start()
            self._child_conn.close()
            self._child_conn = None
            if self.proc.pid:
                try:
                    self._pgid = os.getpgid(self.proc.pid)
                    _OWNED_BOUNDARY_PGIDS.add(self._pgid)
                except OSError:
                    self._pgid = None
        except BaseException:
            self.close()
            raise

    def invoke(self, callback: Callable[[], str | None], *, timeout: float) -> str | None:
        if timeout <= 0:
            raise ValueError("boundary probe timeout must be positive")
        try:
            pickle.dumps(callback, protocol=pickle.HIGHEST_PROTOCOL)
        except Exception as exc:
            raise ProviderRunError("boundary probe must be serializable") from exc
        if self.proc is None or not self.proc.is_alive() or self.parent_conn is None:
            self.close()
            self.start()
        assert self.parent_conn is not None
        deadline = time.monotonic() + timeout
        self.parent_conn.send(("run", callback))
        remaining = max(0.0, deadline - time.monotonic())
        if remaining > 0 and self.parent_conn.poll(remaining):
            kind, value = self.parent_conn.recv()
            if kind == "err":
                if isinstance(value, BaseException):
                    raise value
                raise ProviderRunError(str(value))
            if value is None or isinstance(value, str):
                return value
            raise ProviderRunError("boundary probe returned a non-signal value")
        self.close(deadline=deadline)
        raise ProviderRunError("boundary probe exceeded timeout")

    def close(self, *, deadline: float | None = None) -> None:
        proc = self.proc
        parent = self.parent_conn
        child = self._child_conn
        pgid = self._pgid
        self.proc = None
        self.parent_conn = None
        self._child_conn = None
        self._pgid = None
        try:
            if parent is not None:
                try:
                    parent.send(("stop", None))
                except Exception:
                    pass
            if proc is not None and proc.is_alive():
                proc.kill()
            if proc is not None:
                join_budget = 0.2 if deadline is None else max(0.05, deadline - time.monotonic())
                proc.join(timeout=join_budget)
                if proc.is_alive():
                    proc.kill()
                    proc.join(timeout=0.2)
        finally:
            if parent is not None:
                try:
                    parent.close()
                except Exception:
                    pass
            if child is not None:
                try:
                    child.close()
                except Exception:
                    pass
            if pgid is not None:
                _OWNED_BOUNDARY_PGIDS.discard(pgid)


def _start_boundary_poll(
    on_boundary: Callable[[], str | None],
) -> _BoundaryPollState:
    """Track store-driven turn boundaries with one owned worker process."""

    state = _BoundaryPollState(
        stop=threading.Event(),
        done=threading.Event(),
        on_boundary=on_boundary,
        worker=BoundaryWorker(),
    )
    try:
        assert state.worker is not None
        state.worker.start()
    except BaseException:
        if state.worker is not None:
            state.worker.close()
            state.worker = None
        raise
    state.done.set()
    return state


def _boundary_poll_triggered(poll_state: _BoundaryPollState | None) -> bool:
    return poll_state is not None and poll_state.signal is not None


def _raise_poll_failure(poll_state: _BoundaryPollState | None) -> None:
    if poll_state is not None and poll_state.error is not None:
        raise poll_state.error


def _record_poll_error(poll_state: _BoundaryPollState, exc: BaseException) -> None:
    if poll_state.error is None:
        poll_state.error = exc
        return
    try:
        poll_state.error.add_note(f"cleanup: {exc!r}")
    except Exception:
        pass


def _finalize_boundary_poll(
    poll_state: _BoundaryPollState | None,
    provider: Provider,
    session_id: str,
) -> None:
    if poll_state is None:
        return
    poll_state.stop.set()
    pump = poll_state.pump_thread
    if pump is not None:
        try:
            _abort_provider_turn(provider, session_id)
        except BaseException as exc:
            _record_poll_error(poll_state, exc)
        pump.join(timeout=BOUNDARY_POLL_JOIN_SECONDS)
        if pump.is_alive():
            try:
                _terminate_provider_session(provider, session_id)
            except BaseException as exc:
                _record_poll_error(poll_state, exc)
            pump.join(timeout=BOUNDARY_POLL_JOIN_SECONDS)
        if pump.is_alive():
            _record_poll_error(
                poll_state,
                ProviderRunError("provider event pump failed to stop"),
            )
    worker = poll_state.worker
    poll_state.worker = None
    if worker is not None:
        worker.close()
    _raise_poll_failure(poll_state)


def _invoke_boundary_bounded(
    callback: Callable[[], str | None],
    stop: threading.Event,
    *,
    timeout: float,
    worker: BoundaryWorker | None = None,
) -> str | None:
    """Run a store-only boundary callback with a hard wall-clock bound.

    Drain owns one ``BoundaryWorker`` for the turn. Standalone callers get a
    one-shot worker that is killed and reaped before this function returns.
    """

    _BOUNDARY_CANCEL.set(stop)
    owned = False
    if worker is None:
        worker = BoundaryWorker()
        worker.start()
        owned = True
    try:
        return worker.invoke(callback, timeout=timeout)
    finally:
        if owned:
            worker.close()


def _probe_boundary(
    poll_state: _BoundaryPollState,
    provider: Provider,
    session_id: str,
) -> bool:
    callback = poll_state.on_boundary
    if callback is None or poll_state.signal is not None:
        return False
    try:
        signal = _invoke_boundary_bounded(
            callback,
            poll_state.stop,
            timeout=BOUNDARY_POLL_JOIN_SECONDS,
            worker=poll_state.worker,
        )
    except BaseException as exc:
        poll_state.error = exc
        try:
            _abort_provider_turn(provider, session_id)
        except BaseException as abort_exc:
            _record_poll_error(poll_state, abort_exc)
        return True
    if signal is not None:
        poll_state.signal = signal
        try:
            _abort_provider_turn(provider, session_id)
        except BaseException as exc:
            _record_poll_error(poll_state, exc)
        return True
    return False


def _iter_events_with_boundary_poll(
    provider: Provider,
    session_id: str,
    poll_state: _BoundaryPollState | None,
) -> Iterator[dict[str, Any]]:
    if poll_state is None:
        yield from provider.stream_events(session_id)
        return

    events: queue.Queue[tuple[str, Any]] = queue.Queue()

    def pump() -> None:
        try:
            for event in provider.stream_events(session_id):
                if poll_state.stop.is_set():
                    return
                events.put(("event", event))
        except BaseException as exc:
            events.put(("error", exc))
        else:
            events.put(("end", None))

    pump_thread = threading.Thread(
        target=pump,
        daemon=True,
        name=PROVIDER_EVENT_PUMP_NAME,
    )
    poll_state.pump_thread = pump_thread
    pump_thread.start()
    try:
        while True:
            _raise_poll_failure(poll_state)
            if poll_state.signal is not None:
                return
            poll_state.heartbeat = time.monotonic()
            try:
                kind, payload = events.get(timeout=0.05)
            except queue.Empty:
                if _probe_boundary(poll_state, provider, session_id):
                    return
                continue
            if kind == "event":
                yield payload
            elif kind == "error":
                raise payload
            else:
                return
    finally:
        poll_state.stop.set()


def _drain_provider_turn(
    provider: Provider,
    session_id: str,
    *,
    allowed_signals: frozenset[str],
    on_boundary: Callable[[], str | None] | None = None,
    sync_session_id: Callable[[str], str] | None = None,
) -> str | None:
    """Drain one provider turn.

    When ``sync_session_id`` is set, durable provider session ids are persisted
    on each streamed event. When ``on_boundary`` is set, the hook runs after each
    event and on a background poll so store-driven turn closure still works when
    the provider stream stalls after a mutation (for example production apply).
    The drain always waits for the provider session to settle before returning so
    follow-up turns are not queued while a collector thread is still running.
    """
    active_session_id = session_id
    session_id_holder = [session_id]
    accumulator = TurnTextAccumulator()
    poll_state: _BoundaryPollState | None = None

    if on_boundary is not None:
        poll_state = _start_boundary_poll(on_boundary)

    body_error: BaseException | None = None
    provider_failure: str | None = None
    try:
        for event in _iter_events_with_boundary_poll(
            provider,
            active_session_id,
            poll_state,
        ):
            _raise_poll_failure(poll_state)
            if _boundary_poll_triggered(poll_state):
                break

            event_type = str(event.get("type") or "")
            if event_type == "error":
                text = event.get("text") or "provider error"
                raise ProviderRunError(str(text))
            if event_type in {"assistant", "done"}:
                accumulator.ingest(event)
            if event_type == "done" and event.get("is_error"):
                provider_failure = str(event.get("text") or "provider turn failed")
            if sync_session_id is not None:
                active_session_id = sync_session_id(active_session_id)
                session_id_holder[0] = active_session_id
            if provider_failure is None and on_boundary is not None:
                implicit_signal = _invoke_boundary_bounded(
                    on_boundary,
                    poll_state.stop if poll_state is not None else threading.Event(),
                    timeout=BOUNDARY_POLL_JOIN_SECONDS,
                    worker=poll_state.worker if poll_state is not None else None,
                )
                if implicit_signal is not None:
                    _abort_provider_turn(provider, active_session_id)
                    session_id_holder[0] = active_session_id
                    if sync_session_id is not None:
                        active_session_id = sync_session_id(active_session_id)
                        session_id_holder[0] = active_session_id
                    if poll_state is not None:
                        poll_state.signal = implicit_signal
                    break
            if _boundary_poll_triggered(poll_state):
                _abort_provider_turn(provider, active_session_id)
                break
        if provider_failure is not None:
            raise ProviderRunError(provider_failure)
    except BaseException as exc:
        body_error = exc
        raise
    finally:
        cleanup_errors: list[BaseException] = []
        try:
            _finalize_boundary_poll(poll_state, provider, session_id_holder[0])
        except BaseException as exc:
            cleanup_errors.append(exc)
        try:
            if sync_session_id is not None:
                session_id_holder[0] = sync_session_id(session_id_holder[0])
        except BaseException as exc:
            cleanup_errors.append(exc)
        try:
            _wait_provider_turn_settled(provider, session_id_holder[0])
        except BaseException as exc:
            cleanup_errors.append(exc)
        if cleanup_errors:
            if body_error is not None:
                for extra in cleanup_errors:
                    try:
                        body_error.add_note(f"cleanup: {extra!r}")
                    except Exception:
                        pass
            else:
                raise cleanup_errors[0]

    if _boundary_poll_triggered(poll_state):
        if sync_session_id is not None:
            active_session_id = sync_session_id(session_id_holder[0])
        return poll_state.signal if poll_state is not None else None

    resolved = accumulator.resolve_signal(allowed_signals)
    if resolved is not None:
        return resolved
    return None


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
    recovery: PrimarySessionRecoverySpec,
) -> ProviderTurnOutcome:
    """Resume an existing session, replacing it once on missing or stalled provider sessions.

    Producer and reviewer turns must use their dedicated ``consume_*`` helpers so
    store-driven batch, completion-claim, owner record-actions, or ``review respond``
    boundaries can abort stalled provider subprocesses.
    """

    return _consume_provider_turn_with_session_recovery(
        store,
        run_id,
        provider,
        session_id,
        allowed_signals=allowed_signals,
        recovery=recovery,
        on_boundary=None,
    )


def _consume_provider_turn_with_session_recovery(
    store: RunStore,
    run_id: str,
    provider: Provider,
    session_id: str,
    *,
    allowed_signals: frozenset[str],
    recovery: PrimarySessionRecoverySpec | ReviewerSessionRecoverySpec,
    on_boundary: Callable[[], str | None] | None,
) -> ProviderTurnOutcome:
    """Internal session-recovery turn drain with optional store-driven boundary hooks."""

    ensure_phase_action_id(store, run_id)
    run = store.load_run(run_id)
    phase_action_id = str(run.get("phase_action_id") or generate_phase_action_id())
    role, phase, loop_id = _recovery_role_phase_loop(recovery)
    sync_session_id = _session_binding_syncer(provider, store, run_id, recovery)

    try:
        signal = _drain_provider_turn(
            provider,
            session_id,
            allowed_signals=allowed_signals,
            on_boundary=on_boundary,
            sync_session_id=sync_session_id,
        )
        domain_budget_committed = _finalize_phase_action_turn(store, run_id, phase_action_id)
        return ProviderTurnOutcome(
            signal=signal,
            session_id=provider.canonical_session_id(session_id),
            replaced=False,
            domain_budget_committed=domain_budget_committed,
        )
    except (ProviderSessionNotFoundError, ProviderTurnStalledError) as exc:
        recovery_reason = recovery_reason_for_session_loss(exc)
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
                    recovery_reason=recovery_reason,
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
                    recovery_reason=recovery_reason,
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
        bind_provider_capability(provider, capability_token, store=store, run_id=run_id)

        try:
            signal = _drain_provider_turn(
                provider,
                new_session_id,
                allowed_signals=allowed_signals,
                on_boundary=on_boundary,
                sync_session_id=sync_session_id,
            )
        except ProviderReplacementIdentityError as exc:
            _emit_replacement_blocked(
                store,
                run_id,
                recovery,
                phase_action_id,
                new_session_id,
                "replacement_identity_conflict",
            )
            cleanup_error: BaseException | None = None
            try:
                discard_unbound_provider_session(
                    provider,
                    new_session_id,
                    preexisting_ids={
                        session_id,
                        provider.canonical_session_id(session_id),
                    },
                    timeout=ABORT_TURN_SECONDS,
                )
            except BaseException as cleanup_exc:
                cleanup_error = cleanup_exc
            try:
                fail_session_recovery_exhausted(
                    store,
                    run_id,
                    phase=phase,
                    role=role,
                    phase_action_id=phase_action_id,
                    message=(
                        "replacement provider session identity failed for "
                        f"phase_action_id {phase_action_id}: {exc}"
                    ),
                    loop_id=loop_id,
                )
            except SessionRecoveryExhausted as exhausted:
                if cleanup_error is not None:
                    try:
                        exhausted.add_note(f"cleanup: {cleanup_error!r}")
                    except Exception:
                        pass
                raise exhausted from exc
        except (ProviderSessionNotFoundError, ProviderTurnStalledError) as exc:
            fail_session_recovery_exhausted(
                store,
                run_id,
                phase=phase,
                role=role,
                phase_action_id=phase_action_id,
                message=(
                    "replacement provider session failed for "
                    f"phase_action_id {phase_action_id}: {exc}"
                ),
                loop_id=loop_id,
            )
            raise SessionRecoveryExhausted(str(exc)) from exc

        domain_budget_committed = _finalize_phase_action_turn(store, run_id, phase_action_id)
        return ProviderTurnOutcome(
            signal=signal,
            session_id=provider.canonical_session_id(new_session_id),
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
    activity: str = "initial_plan",
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
            activity=activity,
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
    activity: str = "production",
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
            activity=activity,
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


def production_batch_count(store: RunStore, run_id: str) -> int:
    production = store.load_production(run_id)
    batches = production.get("batches")
    if not isinstance(batches, list):
        return 0
    return len(batches)


def production_completion_claim_count(store: RunStore, run_id: str) -> int:
    """Count durable ``production_completion_claimed`` audit events for a run."""

    return sum(
        1
        for event in store.load_events(run_id)
        if event.get("type") == "production_completion_claimed"
    )


_OWNER_FINDING_ACTION_EVENT_TYPES = frozenset(
    {
        "review_finding_action_recorded",
        "review_challenge_submitted",
    }
)


def owner_finding_action_count(store: RunStore, run_id: str, loop_id: str) -> int:
    """Count durable owner finding-action audit events for a review loop."""

    return sum(
        1
        for event in store.load_events(run_id)
        if event.get("type") in _OWNER_FINDING_ACTION_EVENT_TYPES
        and str(event.get("loop_id") or "") == loop_id
    )


def review_respond_count(store: RunStore, run_id: str, loop_id: str) -> int:
    """Count durable ``review_responded`` audit events for a review loop."""

    return sum(
        1
        for event in store.load_events(run_id)
        if event.get("type") == "review_responded"
        and str(event.get("loop_id") or "") == loop_id
    )


def orchestration_decision_from_store(
    store: RunStore,
    run_id: str,
    loop_id: str,
) -> str | None:
    """Return the persisted orchestration decision when the loop is no longer pending."""

    review = store.load_review(run_id, loop_id)
    review_type = str(review.get("type") or "")
    if review_type in {"whole_plan", "whole_output"}:
        from top_down_planning.domain.reviews import ReviewLoop
        from top_down_planning.orchestrator.mandatory_review_stages import (
            mandatory_orchestration_decision,
        )

        loop = ReviewLoop.from_dict(review)
        decision = mandatory_orchestration_decision(loop)
        if decision not in {"pending", "advisory_pending"}:
            return decision
        return review_decision_from_store(store, run_id, loop_id)
    return review_decision_from_store(store, run_id, loop_id)


def reviewer_turn_closure_ready(
    store: RunStore,
    run_id: str,
    loop_id: str,
    *,
    baseline_responds: int,
    baseline_decision: str | None,
) -> bool:
    """Return True when review respond persisted a new closure signal for this turn."""

    if review_respond_count(store, run_id, loop_id) > baseline_responds:
        return True
    decision = orchestration_decision_from_store(store, run_id, loop_id)
    if baseline_decision is None:
        return decision is not None
    return decision is not None and decision != baseline_decision


@dataclass(frozen=True)
class LiteralBoundarySignal:
    """Picklable drain-boundary result used by tests and static closures."""

    signal: str | None = None
    error: str | None = None

    def __call__(self) -> str | None:
        if self.error:
            raise RuntimeError(self.error)
        return self.signal


def _file_store_root(store: RunStore) -> str:
    root = getattr(store, "root", None)
    if root is None:
        raise ProviderRunError("boundary probe requires a file-backed run store")
    return str(Path(root))


@dataclass(frozen=True)
class StoreBoundaryProbe:
    """Picklable TDP-owned store probe reconstructed in a spawn worker.

    Orchestration boundary probing requires a file-backed ``RunStore.root`` so
    the per-turn worker can reconstruct ``FileRunStore`` out of process.
    """

    kind: str
    store_root: str
    run_id: str
    loop_id: str | None = None
    baseline_batches: int = 0
    baseline_claims: int = 0
    baseline_responds: int = 0
    baseline_decision: str | None = None
    baseline_actions: int = 0

    def __call__(self) -> str | None:
        from top_down_planning.persistence.file_store import FileRunStore

        store = FileRunStore(Path(self.store_root))
        if self.kind in {"producer", "producer_batch"}:
            if production_batch_count(store, self.run_id) > self.baseline_batches:
                return PRODUCER_BATCH_COMPLETE_SIGNAL
            if self.kind == "producer_batch":
                return None
            if production_completion_claim_count(store, self.run_id) > self.baseline_claims:
                return PRODUCER_COMPLETION_COMPLETE_SIGNAL
            return None
        if self.kind == "producer_completion":
            if production_completion_claim_count(store, self.run_id) > self.baseline_claims:
                return PRODUCER_COMPLETION_COMPLETE_SIGNAL
            return None
        if self.kind == "owner_finding":
            loop_id = str(self.loop_id or "")
            if owner_finding_action_count(store, self.run_id, loop_id) > self.baseline_actions:
                return OWNER_FINDING_ACTION_COMPLETE_SIGNAL
            return None
        if self.kind == "reviewer":
            loop_id = str(self.loop_id or "")
            if reviewer_turn_closure_ready(
                store,
                self.run_id,
                loop_id,
                baseline_responds=self.baseline_responds,
                baseline_decision=self.baseline_decision,
            ):
                return REVIEWER_DECISION_COMPLETE_SIGNAL
            return None
        raise ProviderRunError(f"unknown boundary probe kind {self.kind!r}")


def build_producer_batch_boundary_observer(
    store: RunStore,
    run_id: str,
) -> Callable[[], str | None]:
    """Return a hook that signals batch completion when production apply persists a batch."""

    return StoreBoundaryProbe(
        kind="producer_batch",
        store_root=_file_store_root(store),
        run_id=run_id,
        baseline_batches=production_batch_count(store, run_id),
    )


def build_owner_finding_action_boundary_observer(
    store: RunStore,
    run_id: str,
    loop_id: str,
) -> Callable[[], str | None]:
    """Return a hook that signals turn closure when owner record-actions persists."""

    return StoreBoundaryProbe(
        kind="owner_finding",
        store_root=_file_store_root(store),
        run_id=run_id,
        loop_id=loop_id,
        baseline_actions=owner_finding_action_count(store, run_id, loop_id),
    )


def build_producer_completion_boundary_observer(
    store: RunStore,
    run_id: str,
) -> Callable[[], str | None]:
    """Return a hook that signals turn closure when submit-completion persists."""

    return StoreBoundaryProbe(
        kind="producer_completion",
        store_root=_file_store_root(store),
        run_id=run_id,
        baseline_claims=production_completion_claim_count(store, run_id),
    )


def build_producer_turn_boundary_observer(
    store: RunStore,
    run_id: str,
) -> Callable[[], str | None]:
    """Return a hook that closes producer turns on batch apply or completion claim.

    Requires a file-backed run store (``store.root``) because the per-turn
    boundary worker reconstructs ``FileRunStore`` in a child process.
    """

    return StoreBoundaryProbe(
        kind="producer",
        store_root=_file_store_root(store),
        run_id=run_id,
        baseline_batches=production_batch_count(store, run_id),
        baseline_claims=production_completion_claim_count(store, run_id),
    )


def build_reviewer_decision_boundary_observer(
    store: RunStore,
    run_id: str,
    loop_id: str,
) -> Callable[[], str | None]:
    """Return a hook that signals turn closure when review respond persists."""

    return StoreBoundaryProbe(
        kind="reviewer",
        store_root=_file_store_root(store),
        run_id=run_id,
        loop_id=loop_id,
        baseline_responds=review_respond_count(store, run_id, loop_id),
        baseline_decision=orchestration_decision_from_store(store, run_id, loop_id),
    )


def consume_producer_provider_turn_with_session_recovery(
    store: RunStore,
    run_id: str,
    provider: Provider,
    session_id: str,
    *,
    recovery: PrimarySessionRecoverySpec,
) -> ProviderTurnOutcome:
    """Drain a producer turn; close it when a batch or completion claim persists."""

    return _consume_provider_turn_with_session_recovery(
        store,
        run_id,
        provider,
        session_id,
        allowed_signals=_NO_COMPLETION_SIGNALS,
        recovery=recovery,
        on_boundary=build_producer_turn_boundary_observer(store, run_id),
    )


def consume_producer_owner_provider_turn_with_session_recovery(
    store: RunStore,
    run_id: str,
    provider: Provider,
    session_id: str,
    *,
    recovery: PrimarySessionRecoverySpec,
) -> ProviderTurnOutcome:
    """Drain a whole-output owner revision turn; close on submit-completion."""

    return _consume_provider_turn_with_session_recovery(
        store,
        run_id,
        provider,
        session_id,
        allowed_signals=_NO_COMPLETION_SIGNALS,
        recovery=recovery,
        on_boundary=build_producer_completion_boundary_observer(store, run_id),
    )


def consume_owner_finding_action_turn_with_session_recovery(
    store: RunStore,
    run_id: str,
    provider: Provider,
    session_id: str,
    *,
    loop_id: str,
    recovery: PrimarySessionRecoverySpec,
) -> ProviderTurnOutcome:
    """Drain an owner advisory turn; close when record-actions persists."""

    return _consume_provider_turn_with_session_recovery(
        store,
        run_id,
        provider,
        session_id,
        allowed_signals=_NO_COMPLETION_SIGNALS,
        recovery=recovery,
        on_boundary=build_owner_finding_action_boundary_observer(
            store,
            run_id,
            loop_id,
        ),
    )


def consume_reviewer_provider_turn_with_session_recovery(
    store: RunStore,
    run_id: str,
    provider: Provider,
    session_id: str,
    *,
    loop_id: str,
    recovery: ReviewerSessionRecoverySpec,
) -> ProviderTurnOutcome:
    """Drain a reviewer turn; close it when review respond records a decision."""

    return _consume_provider_turn_with_session_recovery(
        store,
        run_id,
        provider,
        session_id,
        allowed_signals=_NO_COMPLETION_SIGNALS,
        recovery=recovery,
        on_boundary=build_reviewer_decision_boundary_observer(store, run_id, loop_id),
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
) -> bool:
    """Run a focused review loop when the store shows one is due.

    Returns True when a focused review loop ran to completion.
    """

    from top_down_planning.orchestrator.focused_review import FocusedReviewOrchestrator

    loop_id = find_pending_focused_review_loop_id(
        store,
        run_id,
        review_type=review_type,
    )
    if loop_id is None:
        return False

    result = FocusedReviewOrchestrator(store, run_id, provider).run(loop_id)
    if not result.ok:
        raise ProviderRunError(
            result.reason or f"{review_type} focused review did not complete successfully"
        )
    return True


def restore_primary_capability_after_focused_review(
    store: RunStore,
    run_id: str,
    provider: Provider,
    *,
    review_type: str,
    role: str,
    current_token: str | None,
) -> str | None:
    """Run a pending focused review and rebind the primary role capability when needed."""

    from top_down_planning.orchestrator.capability import rebind_primary_session_capability

    if not run_pending_focused_review(
        store,
        run_id,
        provider,
        review_type=review_type,
    ):
        return current_token

    rebound = rebind_primary_session_capability(
        store,
        run_id,
        provider,
        role=role,
    )
    return rebound if rebound is not None else current_token


def review_decision_from_store(
    store: RunStore,
    run_id: str,
    loop_id: str,
) -> str | None:
    """Return the persisted review loop status when it is no longer ``pending``."""

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
