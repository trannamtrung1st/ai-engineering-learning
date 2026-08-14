"""Slice 5 rereview 4dae4f6: bounded store probes, replacement identity fail-closed."""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import pytest

from core_tools.provider.errors import ProviderReplacementIdentityError
from top_down_planning.domain.session_bindings import PRIMARY_PLANNER_SLOT, SessionBinding
from top_down_planning.domain.session_lineage import (
    SESSION_REPLACED,
    SESSION_REPLACEMENT_FAILED,
    SESSION_REPLACEMENT_STARTED,
)
from top_down_planning.orchestrator.errors import ProviderRunError, SessionRecoveryPaused
from top_down_planning.orchestrator.provider_turns import (
    _invoke_boundary_bounded,
    build_producer_turn_boundary_observer,
    build_reviewer_decision_boundary_observer,
)
from top_down_planning.orchestrator.session_context import ensure_primary_session
from top_down_planning.orchestrator.session_events import (
    _pending_replacement_success_payload,
    commit_primary_provider_session_binding,
)
from top_down_planning.orchestrator.session_recovery import (
    replace_primary_session,
    replace_reviewer_session,
)
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.commit import CommitSpec
from top_down_planning.persistence.session_bindings import (
    bump_primary_binding_generation,
    get_primary_binding,
    update_primary_binding,
)
from tests.helpers import make_review_loop
from tests.unit.test_slice5_rereview_2af6712b_fixes import _lineage
from tests.unit.test_slice5_rereview_ee5de8e_fixes import (
    _ForcedIdStub,
    _create_run,
    _requested,
    _save_reviewer_loop,
    _scripted,
)


def _replace_primary(store, run_id, provider, old_id: str, action: str) -> str:
    return replace_primary_session(
        store,
        run_id,
        provider,
        role="planner",
        phase="planning",
        old_provider_session_id=old_id,
        phase_action_id=action,
        append_event=lambda *_a, **_k: None,
        model="test-model",
        manifest={"goal": "x"},
    )


def _install_fifo(path: Path) -> None:
    path.unlink()
    os.mkfifo(path)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX FIFO blocks spawn child")
def test_real_producer_observer_is_bounded_when_store_io_blocks(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T070101-070101"
    _create_run(store, run_id)
    observer = build_producer_turn_boundary_observer(store, run_id)
    production = store.run_dir(run_id) / "production.json"
    _install_fifo(production)
    started = time.monotonic()
    try:
        with pytest.raises(ProviderRunError, match="exceeded timeout"):
            _invoke_boundary_bounded(observer, threading.Event(), timeout=0.4)
        assert time.monotonic() - started <= 1.5
    finally:
        if production.exists():
            production.unlink()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX FIFO blocks spawn child")
def test_real_reviewer_observer_is_bounded_when_store_io_blocks(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T070102-070102"
    _create_run(store, run_id)
    loop_id = "review-whole-plan-01"
    _save_reviewer_loop(store, run_id, loop_id=loop_id, session_id="rev-1")
    observer = build_reviewer_decision_boundary_observer(store, run_id, loop_id)
    review_path = store._review_record_path(run_id, loop_id)
    _install_fifo(review_path)
    started = time.monotonic()
    try:
        with pytest.raises(ProviderRunError, match="exceeded timeout"):
            _invoke_boundary_bounded(observer, threading.Event(), timeout=0.4)
        assert time.monotonic() - started <= 1.5
    finally:
        if review_path.exists():
            review_path.unlink()


def test_unserializable_boundary_is_rejected_without_inline_hang() -> None:
    def nested() -> str | None:
        threading.Event().wait()
        return "paused"

    started = time.monotonic()
    with pytest.raises(ProviderRunError, match="serializable"):
        _invoke_boundary_bounded(nested, threading.Event(), timeout=0.4)
    assert time.monotonic() - started < 0.3


def test_immediate_durable_primary_replace_rejects_old_id(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T070103-070103"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    old_id = ensure_primary_session(
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
    provider.forced_primary_id = old_id
    with pytest.raises(
        (ProviderReplacementIdentityError, SessionRecoveryPaused, ProviderRunError)
    ):
        _replace_primary(store, run_id, provider, old_id, "action-reuse-p")
    generation = get_primary_binding(store.load_run(run_id), "planner").generation
    replaced = [
        event
        for event in _lineage(store, run_id, SESSION_REPLACED)
        if event.get("generation") == generation
    ]
    assert replaced == []


def test_immediate_durable_reviewer_replace_rejects_old_id(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T070104-070104"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    old_id = provider.start_reviewer_session({"loop_id": "review-whole-plan-01"})
    _save_reviewer_loop(store, run_id, loop_id="review-whole-plan-01", session_id=old_id)
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id=old_id,
        target_revision=0,
        scope={"kind": "whole_plan"},
        revise_at="blocker",
    )
    provider.forced_reviewer_id = old_id
    with pytest.raises(
        (ProviderReplacementIdentityError, SessionRecoveryPaused, ProviderRunError)
    ):
        replace_reviewer_session(
            store,
            run_id,
            provider,
            loop=loop,
            phase="whole_plan_review",
            old_provider_session_id=old_id,
            phase_action_id="action-reuse-r",
            append_event=lambda *_a, **_k: None,
            model="test-model",
            manifest={"loop_id": "review-whole-plan-01"},
        )
    assert _lineage(store, run_id, SESSION_REPLACED) == []


def test_unrecoverable_old_format_replacement_cannot_bind_without_terminal(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T070105-070105"
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
    run = store.load_run(run_id)
    expected = int(run["revision"])
    sessions = bump_primary_binding_generation(run["sessions"], role="planner")
    pending_id = "cursor-pending-unrecoverable"
    sessions = update_primary_binding(
        sessions,
        role="planner",
        provider_session_id=pending_id,
        provider="stub",
    )
    new_binding = SessionBinding.from_dict(sessions[PRIMARY_PLANNER_SLOT])
    updated = dict(run)
    updated["revision"] = expected + 1
    updated["sessions"] = sessions
    store.commit(
        run_id,
        CommitSpec(
            run=updated,
            run_expected_revision=expected,
            events=[
                {
                    "type": SESSION_REPLACEMENT_STARTED,
                    "run_id": run_id,
                    "phase": "planning",
                    "role": "planner",
                    "session_instance_id": new_binding.session_instance_id,
                    "generation": new_binding.generation,
                    "reason": "provider_turn_stalled",
                }
            ],
        ),
    )
    events_path = store.run_dir(run_id) / "events.jsonl"
    kept = [
        line
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if "run_created" in line or SESSION_REPLACEMENT_STARTED in line
    ]
    events_path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    payload = _pending_replacement_success_payload(
        store,
        run_id,
        role="planner",
        generation=new_binding.generation,
        provider_session_id="cursor-durable-unrecoverable",
        new_session_instance_id=new_binding.session_instance_id,
    )
    assert payload is None
    durable = "cursor-durable-unrecoverable"
    provider._ensure_durable_session(durable, role="planner", kind="primary")
    with pytest.raises(ProviderRunError, match="recoverable old session identity"):
        commit_primary_provider_session_binding(
            store,
            run_id,
            role="planner",
            provider_session_id=durable,
            provider="stub",
            session_provider=provider,
        )
    assert _lineage(store, run_id, SESSION_REPLACED) == []
    assert _lineage(store, run_id, SESSION_REPLACEMENT_FAILED) == []
    binding = get_primary_binding(store.load_run(run_id), "planner")
    assert binding is not None
    assert binding.provider_session_id == pending_id
