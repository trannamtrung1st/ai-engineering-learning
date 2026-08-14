"""Slice 5 rereview ee5de8e: ownership, identity sync, and drain cleanup."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core_tools.provider import StubProvider
from core_tools.provider.errors import ProviderSessionError
from top_down_planning.config import EffectiveActivityContext
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.session_lineage import SESSION_REPLACED
from top_down_planning.orchestrator.errors import ProviderRunError, SessionRecoveryPaused
from top_down_planning.orchestrator.provider_turns import (
    BOUNDARY_POLL_THREAD_NAME,
    PROVIDER_ABORT_THREAD_NAME,
    PROVIDER_EVENT_PUMP_NAME,
    _drain_provider_turn,
)
from top_down_planning.orchestrator.reviewer_session import begin_reviewer_review
from top_down_planning.orchestrator.session_context import ensure_primary_session
from top_down_planning.orchestrator.session_events import (
    end_reviewer_session_with_audit,
    sync_persisted_session_id,
    sync_reviewer_loop_session_id,
)
from top_down_planning.orchestrator.session_recovery import (
    replace_primary_session,
    replace_reviewer_session,
)
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.session_bindings import get_primary_binding
from tests.helpers import create_run_kwargs, done_events, make_review_loop, save_review_payload


def _sample_plan() -> Plan:
    return Plan(
        id="plan-slice5-ee5de8e",
        revision=0,
        output_goal="Goal.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="Root",
                kind="aggregate",
            )
        },
    )


def _create_run(store: FileRunStore, run_id: str) -> dict:
    return store.create_run(
        run_id,
        plan=_sample_plan(),
        **create_run_kwargs(store.root),
    )


def _save_reviewer_loop(
    store: FileRunStore,
    run_id: str,
    *,
    loop_id: str,
    session_id: str | None,
) -> None:
    loop = make_review_loop(
        id=loop_id,
        type="whole_plan",
        reviewer_session_id=session_id,
        target_revision=0,
        scope={"kind": "whole_plan"},
        revise_at="blocker",
    )
    save_review_payload(store, run_id, loop.to_dict())


def _scripted(provider: StubProvider, n: int = 8) -> StubProvider:
    for _ in range(n):
        provider.script_turn(done_events(text="session registered"))
    return provider


def _requested(role: str) -> EffectiveActivityContext:
    return EffectiveActivityContext(
        role=role,
        activity="plan",
        model="test-model",
        input_refs=(),
        output_goal="Goal.",
        guidance=(),
        resources=(),
        skills=(),
        context_digest="digest-ee5de8e",
    )


class _ForcedIdStub(StubProvider):
    def __init__(
        self,
        *,
        forced_primary_id: str | None = None,
        forced_reviewer_id: str | None = None,
    ) -> None:
        super().__init__()
        self.forced_primary_id = forced_primary_id
        self.forced_reviewer_id = forced_reviewer_id
        self.aliases: dict[str, str] = {}

    def canonical_session_id(self, session_id: str) -> str:
        current = session_id
        seen: set[str] = set()
        while current in self.aliases and current not in seen:
            seen.add(current)
            current = self.aliases[current]
        return current

    def start_primary_session(self, role, request, *, model=None):
        if self.forced_primary_id is not None:
            return self.forced_primary_id
        return super().start_primary_session(role, request, model=model)

    def get_session_reference(self, session_id: str):
        canonical = self.canonical_session_id(session_id)
        key = session_id
        if canonical in self._sessions:
            key = canonical
        elif session_id in self._sessions:
            key = session_id
        else:
            for alias, target in self.aliases.items():
                if self.canonical_session_id(target) == canonical and alias in self._sessions:
                    key = alias
                    break
        session = self._sessions.get(key)
        if session is None:
            raise ProviderSessionError(
                f"unknown provider session: {session_id}",
                session_id=session_id,
            )
        return {
            "provider": "stub",
            "session_id": canonical,
            "role": session.role,
            "kind": session.kind,
            "model": session.model,
            "turn_count": len(session.history),
        }

    def start_reviewer_session(self, request, *, model=None):
        if self.forced_reviewer_id is not None:
            return self.forced_reviewer_id
        return super().start_reviewer_session(request, model=model)


class _RecordingDrainProvider:
    def __init__(
        self,
        *,
        abort_error: BaseException | None = None,
        hang_abort: bool = False,
        hang_terminate: bool = False,
        yield_event: dict | None = None,
        unblock_on_abort: bool = True,
        unblock_on_terminate: bool = True,
    ) -> None:
        self.released = threading.Event()
        self.woken = threading.Event()
        self.abort_gate = threading.Event()
        self.aborted: list[str] = []
        self.settled: list[str] = []
        self.terminated: list[str] = []
        self.abort_error = abort_error
        self.hang_abort = hang_abort
        self.hang_terminate = hang_terminate
        self.yield_event = yield_event
        self.unblock_on_abort = unblock_on_abort
        self.unblock_on_terminate = unblock_on_terminate

    def stream_events(self, session_id: str):
        if self.yield_event is not None:
            yield self.yield_event
        while not self.released.is_set() and not self.woken.is_set():
            if self.released.wait(timeout=0.05):
                break
            if self.woken.is_set():
                break
        return
        yield

    def abort_turn(self, session_id: str, *, timeout: float = 2.0) -> None:
        self.aborted.append(session_id)
        self.woken.set()
        wait = 30.0 if timeout is None else timeout
        if self.hang_abort:
            self.abort_gate.wait(timeout=wait)
        if self.unblock_on_abort:
            self.released.set()
        if self.abort_error is not None:
            raise self.abort_error

    def wait_turn_settled(self, session_id: str, *, timeout: float = 30.0) -> None:
        self.settled.append(session_id)

    def terminate_session(self, session_id: str, *, timeout: float = 2.0) -> None:
        self.terminated.append(session_id)
        self.woken.set()
        self.abort_gate.set()
        wait = 30.0 if timeout is None else timeout
        if self.hang_terminate:
            self.released.wait(timeout=wait)
        if self.unblock_on_terminate:
            self.released.set()

    def canonical_session_id(self, session_id: str) -> str:
        return session_id


def _active_ids(provider: StubProvider) -> set[str]:
    return {str(session["session_id"]) for session in provider.list_active_sessions()}


def _lineage_types(store: FileRunStore, run_id: str) -> list[str]:
    return [str(event.get("type")) for event in store.load_events(run_id)]


def test_reviewer_start_rejects_planner_durable_id(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T015101-015101"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    ensure_primary_session(
        store,
        run_id,
        provider,
        role="planner",
        phase="planning",
        requested=_requested("planner"),
        manifest={"goal": "x"},
        append_event=lambda *_a, **_k: None,
        resume_request={"goal": "x"},
    )
    planner_id = get_primary_binding(store.load_run(run_id), "planner").provider_session_id
    provider.forced_reviewer_id = planner_id
    _save_reviewer_loop(store, run_id, loop_id="review-whole-plan-01", session_id=None)
    before = store.load_run(run_id)
    before_caps = store.list_capabilities(run_id)
    with pytest.raises(ProviderSessionError):
        begin_reviewer_review(
            provider,
            store,
            run_id,
            loop_id="review-whole-plan-01",
            review_package={"loop_id": "review-whole-plan-01"},
            phase="whole_plan_review",
        )
    after = store.load_run(run_id)
    loop = store.load_review(run_id, "review-whole-plan-01")
    assert after["sessions"] == before["sessions"]
    assert after["revision"] == before["revision"]
    assert (loop.get("reviewer_binding") or {}).get("provider_session_id") in {None, ""}
    assert store.list_capabilities(run_id) == before_caps
    assert planner_id in _active_ids(provider)


def test_reviewer_start_rejects_producer_durable_id(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T015102-015102"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    ensure_primary_session(
        store,
        run_id,
        provider,
        role="producer",
        phase="production",
        requested=_requested("producer"),
        manifest={"goal": "x"},
        append_event=lambda *_a, **_k: None,
        resume_request={"goal": "x"},
    )
    producer_id = get_primary_binding(store.load_run(run_id), "producer").provider_session_id
    provider.forced_reviewer_id = producer_id
    _save_reviewer_loop(store, run_id, loop_id="review-whole-plan-01", session_id=None)
    with pytest.raises(ProviderSessionError):
        begin_reviewer_review(
            provider,
            store,
            run_id,
            loop_id="review-whole-plan-01",
            review_package={"loop_id": "review-whole-plan-01"},
            phase="whole_plan_review",
        )
    assert producer_id in _active_ids(provider)


def test_primary_start_rejects_reviewer_durable_id(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T015103-015103"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    reviewer_id = provider.start_reviewer_session({"loop_id": "review-whole-plan-01"})
    _save_reviewer_loop(
        store, run_id, loop_id="review-whole-plan-01", session_id=reviewer_id
    )
    provider.forced_primary_id = reviewer_id
    before = store.load_run(run_id)
    with pytest.raises(ProviderSessionError):
        ensure_primary_session(
            store,
            run_id,
            provider,
            role="planner",
            phase="planning",
            requested=_requested("planner"),
            manifest={"goal": "x"},
            append_event=lambda *_a, **_k: None,
            resume_request={"goal": "x"},
        )
    after = store.load_run(run_id)
    assert get_primary_binding(after, "planner") is None or (
        get_primary_binding(after, "planner") is not None
        and get_primary_binding(after, "planner").provider_session_id != reviewer_id
    )
    assert after["revision"] == before["revision"] or get_primary_binding(
        after, "planner"
    ) is None
    assert reviewer_id in _active_ids(provider)


def test_reviewer_start_rejects_other_reviewer_loop_id(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T015104-015104"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    first_id = provider.start_reviewer_session({"loop_id": "loop-a"})
    _save_reviewer_loop(store, run_id, loop_id="loop-a", session_id=first_id)
    _save_reviewer_loop(store, run_id, loop_id="loop-b", session_id=None)
    provider.forced_reviewer_id = first_id
    with pytest.raises(ProviderSessionError):
        begin_reviewer_review(
            provider,
            store,
            run_id,
            loop_id="loop-b",
            review_package={"loop_id": "loop-b"},
            phase="whole_plan_review",
        )
    loop_a = store.load_review(run_id, "loop-a")
    loop_b = store.load_review(run_id, "loop-b")
    assert loop_a["reviewer_binding"]["provider_session_id"] == first_id
    assert (loop_b.get("reviewer_binding") or {}).get("provider_session_id") in {
        None,
        "",
    }
    assert first_id in _active_ids(provider)


def test_primary_replacement_rejects_other_owner_id(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T015105-015105"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    planner_id = ensure_primary_session(
        store,
        run_id,
        provider,
        role="planner",
        phase="planning",
        requested=_requested("planner"),
        manifest={"goal": "x"},
        append_event=lambda *_a, **_k: None,
        resume_request={"goal": "x"},
    )
    reviewer_id = provider.start_reviewer_session({"loop_id": "review-whole-plan-01"})
    _save_reviewer_loop(
        store, run_id, loop_id="review-whole-plan-01", session_id=reviewer_id
    )
    provider.forced_primary_id = reviewer_id
    with pytest.raises(SessionRecoveryPaused):
        replace_primary_session(
            store,
            run_id,
            provider,
            role="planner",
            phase="planning",
            old_provider_session_id=planner_id,
            phase_action_id="action-replace-01",
            append_event=lambda *_a, **_k: None,
            model=None,
            manifest={"goal": "x"},
        )
    assert reviewer_id in _active_ids(provider)
    assert SESSION_REPLACED not in _lineage_types(store, run_id)


def test_reviewer_replacement_rejects_other_owner_id(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T015106-015106"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    planner_id = provider.start_primary_session("planner", {"goal": "x"})
    ensure_primary_session(
        store,
        run_id,
        provider,
        role="planner",
        phase="planning",
        requested=_requested("planner"),
        manifest={"goal": "x"},
        append_event=lambda *_a, **_k: None,
        resume_request={"goal": "x"},
    )
    reviewer_id = provider.start_reviewer_session({"loop_id": "review-whole-plan-01"})
    _save_reviewer_loop(
        store, run_id, loop_id="review-whole-plan-01", session_id=reviewer_id
    )
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id=reviewer_id,
        target_revision=0,
        scope={"kind": "whole_plan"},
        revise_at="blocker",
    )
    provider.forced_reviewer_id = planner_id
    with pytest.raises(SessionRecoveryPaused):
        replace_reviewer_session(
            store,
            run_id,
            provider,
            loop=loop,
            phase="whole_plan_review",
            old_provider_session_id=reviewer_id,
            phase_action_id="action-replace-01",
            append_event=lambda *_a, **_k: None,
            model=None,
            manifest={"loop_id": "review-whole-plan-01"},
        )
    assert planner_id in _active_ids(provider)
    assert SESSION_REPLACED not in _lineage_types(store, run_id)


def test_uniqueness_canonicalizes_planner_pending_alias(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T015107-015107"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    pending = "cursor-pending-planner"
    durable = "cursor-durable-d"
    provider._ensure_durable_session(pending, role="planner", kind="primary")
    provider.aliases[pending] = durable
    from top_down_planning.orchestrator.session_events import (
        commit_primary_provider_session_binding,
    )

    commit_primary_provider_session_binding(
        store,
        run_id,
        role="planner",
        provider_session_id=pending,
        provider="stub",
        session_provider=provider,
    )
    _save_reviewer_loop(store, run_id, loop_id="review-whole-plan-01", session_id=durable)
    before = store.load_review(run_id, "review-whole-plan-01")
    with pytest.raises(ProviderSessionError):
        sync_reviewer_loop_session_id(
            provider, store, run_id, "review-whole-plan-01", durable
        )
    after = store.load_review(run_id, "review-whole-plan-01")
    assert after["revision"] == before["revision"]


def test_uniqueness_canonicalizes_reviewer_pending_alias(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T015108-015108"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    pending = "cursor-pending-reviewer"
    durable = "cursor-durable-d"
    provider._ensure_durable_session(pending, role="reviewer", kind="reviewer")
    provider.aliases[pending] = durable
    _save_reviewer_loop(store, run_id, loop_id="review-whole-plan-01", session_id=pending)
    from top_down_planning.orchestrator.session_events import (
        commit_primary_provider_session_binding,
    )

    before = store.load_run(run_id)
    with pytest.raises(ProviderSessionError):
        commit_primary_provider_session_binding(
            store,
            run_id,
            role="planner",
            provider_session_id=durable,
            provider="stub",
            session_provider=provider,
        )
    after = store.load_run(run_id)
    assert after["revision"] == before["revision"]
    planner = get_primary_binding(after, "planner")
    assert planner is None or planner.provider_session_id is None


def test_canonical_still_pending_is_not_a_durable_collision(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T015109-015109"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    from top_down_planning.orchestrator.session_events import (
        commit_primary_provider_session_binding,
    )

    provider._ensure_durable_session("cursor-pending-a", role="planner", kind="primary")
    provider._ensure_durable_session("cursor-pending-b", role="producer", kind="primary")
    commit_primary_provider_session_binding(
        store,
        run_id,
        role="planner",
        provider_session_id="cursor-pending-a",
        provider="stub",
        session_provider=provider,
    )
    commit_primary_provider_session_binding(
        store,
        run_id,
        role="producer",
        provider_session_id="cursor-pending-b",
        provider="stub",
        session_provider=provider,
    )
    planner = get_primary_binding(store.load_run(run_id), "planner")
    producer = get_primary_binding(store.load_run(run_id), "producer")
    assert planner is not None and planner.provider_session_id == "cursor-pending-a"
    assert producer is not None and producer.provider_session_id == "cursor-pending-b"


def test_primary_replacement_rejects_reviewer_id(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T015110-015110"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    planner_id = provider.start_primary_session("planner", {"goal": "x"})
    ensure_primary_session(
        store,
        run_id,
        provider,
        role="planner",
        phase="planning",
        requested=_requested("planner"),
        manifest={"goal": "x"},
        append_event=lambda *_a, **_k: None,
        resume_request={"goal": "x"},
    )
    reviewer_id = provider.start_reviewer_session({"loop_id": "review-01"})
    _save_reviewer_loop(store, run_id, loop_id="review-01", session_id=reviewer_id)
    before_gen = get_primary_binding(store.load_run(run_id), "planner").generation
    with pytest.raises(ProviderSessionError):
        replace_primary_session(
            store,
            run_id,
            provider,
            role="planner",
            phase="planning",
            old_provider_session_id=reviewer_id,
            phase_action_id="action-replace-01",
            append_event=lambda *_a, **_k: None,
            model=None,
            manifest={"goal": "x"},
        )
    assert reviewer_id in _active_ids(provider)
    assert planner_id in _active_ids(provider)
    assert get_primary_binding(store.load_run(run_id), "planner").generation == before_gen


def test_planner_replacement_rejects_producer_id(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T015111-015111"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    planner_id = provider.start_primary_session("planner", {"goal": "x"})
    producer_id = provider.start_primary_session("producer", {"goal": "x"})
    ensure_primary_session(
        store,
        run_id,
        provider,
        role="planner",
        phase="planning",
        requested=_requested("planner"),
        manifest={"goal": "x"},
        append_event=lambda *_a, **_k: None,
        resume_request={"goal": "x"},
    )
    ensure_primary_session(
        store,
        run_id,
        provider,
        role="producer",
        phase="production",
        requested=_requested("producer"),
        manifest={"goal": "x"},
        append_event=lambda *_a, **_k: None,
        resume_request={"goal": "x"},
    )
    with pytest.raises(ProviderSessionError):
        replace_primary_session(
            store,
            run_id,
            provider,
            role="planner",
            phase="planning",
            old_provider_session_id=producer_id,
            phase_action_id="action-replace-01",
            append_event=lambda *_a, **_k: None,
            model=None,
            manifest={"goal": "x"},
        )
    assert planner_id in _active_ids(provider)
    assert producer_id in _active_ids(provider)


def test_reviewer_replacement_rejects_primary_id(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T015112-015112"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    planner_id = provider.start_primary_session("planner", {"goal": "x"})
    ensure_primary_session(
        store,
        run_id,
        provider,
        role="planner",
        phase="planning",
        requested=_requested("planner"),
        manifest={"goal": "x"},
        append_event=lambda *_a, **_k: None,
        resume_request={"goal": "x"},
    )
    reviewer_id = provider.start_reviewer_session({"loop_id": "review-01"})
    _save_reviewer_loop(store, run_id, loop_id="review-01", session_id=reviewer_id)
    loop = make_review_loop(
        id="review-01",
        type="whole_plan",
        reviewer_session_id=reviewer_id,
        target_revision=0,
        scope={"kind": "whole_plan"},
        revise_at="blocker",
    )
    with pytest.raises(ProviderSessionError):
        replace_reviewer_session(
            store,
            run_id,
            provider,
            loop=loop,
            phase="whole_plan_review",
            old_provider_session_id=planner_id,
            phase_action_id="action-replace-01",
            append_event=lambda *_a, **_k: None,
            model=None,
            manifest={"loop_id": "review-01"},
        )
    assert planner_id in _active_ids(provider)
    assert reviewer_id in _active_ids(provider)


def test_reviewer_replacement_rejects_other_loop_id(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T015113-015113"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    ra = provider.start_reviewer_session({"loop_id": "loop-a"})
    rb = provider.start_reviewer_session({"loop_id": "loop-b"})
    _save_reviewer_loop(store, run_id, loop_id="loop-a", session_id=ra)
    _save_reviewer_loop(store, run_id, loop_id="loop-b", session_id=rb)
    loop_a = make_review_loop(
        id="loop-a",
        type="whole_plan",
        reviewer_session_id=ra,
        target_revision=0,
        scope={"kind": "whole_plan"},
        revise_at="blocker",
    )
    with pytest.raises(ProviderSessionError):
        replace_reviewer_session(
            store,
            run_id,
            provider,
            loop=loop_a,
            phase="whole_plan_review",
            old_provider_session_id=rb,
            phase_action_id="action-replace-01",
            append_event=lambda *_a, **_k: None,
            model=None,
            manifest={"loop_id": "loop-a"},
        )
    assert ra in _active_ids(provider)
    assert rb in _active_ids(provider)


def test_reviewer_release_rejects_other_loop_session(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T015114-015114"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    ra = provider.start_reviewer_session({"loop_id": "loop-a"})
    rb = provider.start_reviewer_session({"loop_id": "loop-b"})
    _save_reviewer_loop(store, run_id, loop_id="loop-a", session_id=ra)
    _save_reviewer_loop(store, run_id, loop_id="loop-b", session_id=rb)
    append_event = MagicMock()
    with pytest.raises(ProviderSessionError):
        end_reviewer_session_with_audit(
            append_event,
            provider,
            phase="whole_plan_review",
            session_id=rb,
            store=store,
            run_id=run_id,
            loop_id="loop-a",
        )
    assert ra in _active_ids(provider)
    assert rb in _active_ids(provider)
    assert append_event.call_count == 0

    with pytest.raises(ProviderSessionError):
        end_reviewer_session_with_audit(
            append_event,
            provider,
            phase="whole_plan_review",
            session_id=ra,
            store=store,
            run_id=run_id,
            loop_id="loop-b",
        )
    assert ra in _active_ids(provider)
    assert rb in _active_ids(provider)


def test_primary_sync_rejects_durable_identity_change(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T015115-015115"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    d1 = provider.start_primary_session("planner", {"goal": "x"})
    from top_down_planning.orchestrator.session_events import (
        commit_primary_provider_session_binding,
    )

    commit_primary_provider_session_binding(
        store,
        run_id,
        role="planner",
        provider_session_id=d1,
        provider="stub",
        session_provider=provider,
    )
    provider.aliases[d1] = "cursor-durable-d2"
    before = store.load_run(run_id)
    before_caps = store.list_capabilities(run_id)
    before_events = list(store.load_events(run_id))
    with pytest.raises(ProviderSessionError):
        sync_persisted_session_id(provider, store, run_id, d1, role="planner")
    after = store.load_run(run_id)
    assert after["sessions"] == before["sessions"]
    assert after["revision"] == before["revision"]
    assert store.list_capabilities(run_id) == before_caps
    assert list(store.load_events(run_id)) == before_events


def test_producer_sync_rejects_durable_identity_change(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T015116-015116"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    d1 = provider.start_primary_session("producer", {"goal": "x"})
    from top_down_planning.orchestrator.session_events import (
        commit_primary_provider_session_binding,
    )

    commit_primary_provider_session_binding(
        store,
        run_id,
        role="producer",
        provider_session_id=d1,
        provider="stub",
        session_provider=provider,
    )
    provider.aliases[d1] = "cursor-durable-d2"
    with pytest.raises(ProviderSessionError):
        sync_persisted_session_id(provider, store, run_id, d1, role="producer")
    binding = get_primary_binding(store.load_run(run_id), "producer")
    assert binding is not None
    assert binding.provider_session_id == d1


def test_primary_sync_allows_pending_promotion_and_same_durable(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T015117-015117"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    pending = "cursor-pending-planner"
    durable = "cursor-durable-d1"
    provider._ensure_durable_session(durable, role="planner", kind="primary")
    provider.aliases[pending] = durable
    from top_down_planning.orchestrator.session_events import (
        commit_primary_provider_session_binding,
    )

    commit_primary_provider_session_binding(
        store,
        run_id,
        role="planner",
        provider_session_id=pending,
        provider="stub",
        session_provider=provider,
    )
    promoted = sync_persisted_session_id(
        provider, store, run_id, pending, role="planner"
    )
    assert promoted == durable
    again = sync_persisted_session_id(provider, store, run_id, durable, role="planner")
    assert again == durable
    binding = get_primary_binding(store.load_run(run_id), "planner")
    assert binding is not None
    assert binding.provider_session_id == durable


def test_poll_finalizer_error_still_syncs_and_settles() -> None:
    provider = _RecordingDrainProvider(abort_error=RuntimeError("abort failed"))
    synced: list[str] = []

    def sync(session_id: str) -> str:
        synced.append(session_id)
        return session_id

    with pytest.raises(RuntimeError, match="abort failed"):
        _drain_provider_turn(
            provider,
            "sess-1",
            allowed_signals=frozenset(),
            on_boundary=lambda: "paused",
            sync_session_id=sync,
        )
    assert synced
    assert provider.settled == ["sess-1"]


def test_stream_error_and_poll_finalizer_error_retain_context() -> None:
    provider = _RecordingDrainProvider(
        abort_error=RuntimeError("abort failed"),
        yield_event={"type": "error", "text": "stream boom"},
    )
    synced: list[str] = []

    def sync(session_id: str) -> str:
        synced.append(session_id)
        return session_id

    with pytest.raises((ProviderRunError, RuntimeError)) as caught:
        _drain_provider_turn(
            provider,
            "sess-1",
            allowed_signals=frozenset(),
            on_boundary=lambda: None,
            sync_session_id=sync,
        )
    assert synced
    assert provider.settled
    err = caught.value
    combined = f"{err} {err.__cause__} {err.__context__} {getattr(err, '__notes__', [])}"
    assert "stream boom" in combined or "abort failed" in combined


def _live_named(name: str) -> list[threading.Thread]:
    return [
        thread
        for thread in threading.enumerate()
        if thread.name == name and thread.is_alive()
    ]


def test_hanging_abort_is_bounded_on_event_idle_and_finalize() -> None:
    def run_case(*, yield_event, on_boundary):
        provider = _RecordingDrainProvider(
            hang_abort=True,
            yield_event=yield_event,
        )
        with patch(
            "top_down_planning.orchestrator.provider_turns.ABORT_TURN_SECONDS",
            0.1,
        ), patch(
            "top_down_planning.orchestrator.provider_turns.BOUNDARY_POLL_JOIN_SECONDS",
            0.1,
        ):
            started = time.monotonic()
            try:
                _drain_provider_turn(
                    provider,
                    "sess-1",
                    allowed_signals=frozenset(),
                    on_boundary=on_boundary,
                    sync_session_id=lambda sid: sid,
                )
            except (ProviderRunError, RuntimeError):
                pass
            assert time.monotonic() - started < 2.0
        assert provider.settled
        assert _live_named(PROVIDER_ABORT_THREAD_NAME) == []
        assert _live_named(BOUNDARY_POLL_THREAD_NAME) == []
        assert _live_named(PROVIDER_EVENT_PUMP_NAME) == []
        provider.released.set()
        return provider

    run_case(
        yield_event={"type": "assistant", "text": "hi"},
        on_boundary=lambda: "paused",
    )
    run_case(yield_event=None, on_boundary=lambda: "paused")


def test_event_pump_is_joined_and_does_not_accumulate() -> None:
    for _ in range(4):
        provider = _RecordingDrainProvider(hang_abort=True)
        with patch(
            "top_down_planning.orchestrator.provider_turns.ABORT_TURN_SECONDS",
            0.1,
        ), patch(
            "top_down_planning.orchestrator.provider_turns.BOUNDARY_POLL_JOIN_SECONDS",
            0.1,
        ):
            try:
                _drain_provider_turn(
                    provider,
                    "sess-1",
                    allowed_signals=frozenset(),
                    on_boundary=lambda: "paused",
                )
            except (ProviderRunError, RuntimeError):
                pass
        assert _live_named(PROVIDER_EVENT_PUMP_NAME) == []
        assert _live_named(PROVIDER_ABORT_THREAD_NAME) == []
        provider.released.set()
