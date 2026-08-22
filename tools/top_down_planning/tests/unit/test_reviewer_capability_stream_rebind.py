"""Reviewer capability tokens must not be minted once per streamed event."""

from __future__ import annotations

from pathlib import Path

from core_tools.provider import StubProvider
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator.provider_turns import _drain_provider_turn
from top_down_planning.orchestrator.session_events import sync_reviewer_loop_session_id
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.capabilities import (
    capability_token_file_path,
    clear_capability_token_file,
)
from tests.helpers import create_run_kwargs, make_review_loop, save_review_payload


def _create_run(store: FileRunStore, run_id: str) -> None:
    store.create_run(
        run_id,
        plan=Plan(
            id=f"plan-{run_id}",
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
        ),
        **create_run_kwargs(store.root),
    )


def _save_reviewer_loop(
    store: FileRunStore,
    run_id: str,
    *,
    loop_id: str,
    session_id: str,
) -> None:
    save_review_payload(
        store,
        run_id,
        make_review_loop(
            id=loop_id,
            type="whole_plan",
            reviewer_session_id=session_id,
            target_revision=0,
            scope={"kind": "whole_plan"},
            revise_at="blocker",
        ).to_dict(),
    )


def _live_reviewer_caps(store: FileRunStore, run_id: str) -> list[dict]:
    return [
        record
        for record in store.list_capabilities(run_id)
        if record.get("role") == "reviewer" and record.get("revoked") is not True
    ]


def test_reviewer_sync_keeps_one_capability_when_already_bound(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T090001-090001"
    loop_id = "review-whole-plan-01"
    _create_run(store, run_id)
    provider = StubProvider()
    session_id = "durable-reviewer-01"
    provider._ensure_durable_session(session_id, role="reviewer", kind="reviewer")
    _save_reviewer_loop(store, run_id, loop_id=loop_id, session_id=session_id)

    first = sync_reviewer_loop_session_id(provider, store, run_id, loop_id, session_id)
    second = sync_reviewer_loop_session_id(provider, store, run_id, loop_id, session_id)

    assert first == session_id
    assert second == session_id
    records = store.list_capabilities(run_id)
    assert len(records) == 1
    assert _live_reviewer_caps(store, run_id) == records


def test_reviewer_turn_drain_does_not_mint_capability_per_stream_event(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T090002-090002"
    loop_id = "review-whole-plan-01"
    _create_run(store, run_id)
    stream_chunks = 40
    events = [{"type": "assistant", "text": f"chunk {index}"} for index in range(stream_chunks)]
    events.append({"type": "done", "subtype": "success", "text": "ok", "is_error": False})
    provider = StubProvider()
    provider.script_turn(events)
    session_id = provider.start_reviewer_session({"loop_id": loop_id})
    _save_reviewer_loop(store, run_id, loop_id=loop_id, session_id=session_id)

    def sync_session_id(active_id: str) -> str:
        return sync_reviewer_loop_session_id(
            provider, store, run_id, loop_id, active_id
        )

    _drain_provider_turn(
        provider,
        session_id,
        allowed_signals=frozenset(),
        sync_session_id=sync_session_id,
    )

    records = store.list_capabilities(run_id)
    assert len(records) == 1
    assert len(_live_reviewer_caps(store, run_id)) == 1
    assert records[0]["session_id"] == session_id
    assert records[0]["loop_id"] == loop_id


def test_reviewer_sync_reissues_capability_when_exported_token_is_gone(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T090003-090003"
    loop_id = "review-whole-plan-01"
    _create_run(store, run_id)
    provider = StubProvider()
    session_id = "durable-reviewer-03"
    provider._ensure_durable_session(session_id, role="reviewer", kind="reviewer")
    _save_reviewer_loop(store, run_id, loop_id=loop_id, session_id=session_id)

    sync_reviewer_loop_session_id(provider, store, run_id, loop_id, session_id)
    original = _live_reviewer_caps(store, run_id)
    assert len(original) == 1
    store.revoke_capability(run_id, str(original[0]["id"]))
    clear_capability_token_file(store, run_id)
    assert not capability_token_file_path(store, run_id).exists()

    sync_reviewer_loop_session_id(provider, store, run_id, loop_id, session_id)

    live = _live_reviewer_caps(store, run_id)
    assert len(live) == 1
    assert live[0]["id"] != original[0]["id"]
    assert capability_token_file_path(store, run_id).exists()
