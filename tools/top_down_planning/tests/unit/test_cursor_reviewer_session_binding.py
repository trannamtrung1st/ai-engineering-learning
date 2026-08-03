"""Cursor reviewer session binding through whole-plan review recheck."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core_tools.provider.cursor import CursorProvider
from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.domain.session_bindings import (
    binding_provider_session_id,
    new_session_binding,
)
from top_down_planning.domain.session_lineage import SESSION_PROVIDER_ID_BOUND
from top_down_planning.orchestrator import ProviderRunError, WholePlanReviewOrchestrator
from top_down_planning.orchestrator.phases import WHOLE_PLAN_REVIEW
from top_down_planning.orchestrator.provider_turns import (
    build_reviewer_turn_recovery,
    consume_reviewer_provider_turn_with_session_recovery,
)
from top_down_planning.orchestrator.reviewer_session import (
    ReviewerRecheckRequiresNewSession,
    resolve_reviewer_session_for_recheck,
)
from top_down_planning.orchestrator.session_events import sync_reviewer_loop_session_id
from top_down_planning.persistence import FileRunStore
from tests.helpers import (
    make_review_loop,
    mandatory_initial_respond_request,
    respond_review,
)
from tests.unit.test_whole_plan_review import _create_run_at_whole_plan_review


def _cursor_stream(*, session_id: str, text: str) -> list[str]:
    return [
        json.dumps(
            {
                "type": "system",
                "subtype": "init",
                "session_id": session_id,
            }
        ),
        json.dumps(
            {
                "type": "assistant",
                "session_id": session_id,
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": text}],
                },
            }
        ),
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "session_id": session_id,
                "is_error": False,
                "result": text,
            }
        ),
    ]


def _cursor_provider(
    tmp_path: Path,
    streams: list[list[str]],
    *,
    on_turn_start: list[Callable[[], None] | None] | None = None,
) -> CursorProvider:
    call_index = {"value": 0}
    hooks = on_turn_start or []

    def fake_runner(argv: list[str], cwd: Path):
        index = call_index["value"]
        call_index["value"] = index + 1
        hook = hooks[index] if index < len(hooks) else None
        stream = streams[index]
        for line_index, line in enumerate(stream):
            yield line
            if line_index == 0 and hook is not None:
                threading.Thread(target=hook, daemon=True).start()

    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    return CursorProvider(
        {"provider": {"name": "cursor"}},
        workspace=tmp_path,
        runner=fake_runner,
        binary=str(agent_path),
        skip_probe=True,
    )


def test_sync_reviewer_loop_session_id_promotes_starting_binding_to_bound(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T010001-010001"
    _create_run_at_whole_plan_review(store, run_id=run_id)
    binding = (
        new_session_binding(role="reviewer", kind="reviewer", state="starting")
        .with_provider_session_id("chat-reviewer-1")
    )
    store.save_review(
        run_id,
        {
            "id": "review-whole-plan-01",
            "type": "whole_plan",
            "revise_at": "major",
            "target_revision": 0,
            "scope": {"kind": "whole_plan"},
            "status": "changes_requested",
            "findings": [],
            "revision_cycles": 1,
            "lifecycle_status": "revision_in_progress",
            "reviewer_binding": binding.to_dict(),
        },
    )

    class _CanonicalProvider:
        def canonical_session_id(self, session_id: str) -> str:
            return session_id

    sync_reviewer_loop_session_id(
        _CanonicalProvider(),
        store,
        run_id,
        "review-whole-plan-01",
        "chat-reviewer-1",
    )

    review = store.load_review(run_id, "review-whole-plan-01")
    persisted = review["reviewer_binding"]
    assert persisted["provider_session_id"] == "chat-reviewer-1"
    assert persisted["state"] == "bound"


def test_whole_plan_recheck_binds_cursor_reviewer_session_after_initial_review(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T010002-010002"
    _create_run_at_whole_plan_review(store, run_id=run_id)
    respond = respond_review(
        store,
        run_id,
        mandatory_initial_respond_request(
            store,
            run_id,
            loop_id="review-whole-plan-01",
            target_revision=0,
            review_type="whole_plan",
            findings=[
                {
                    "id": "finding-01",
                    "severity": "major",
                    "category": "correctness",
                    "target_refs": ["item-root"],
                    "issue": "Scope is empty.",
                    "recommended_change": "Populate scope.",
                    "status": "unresolved",
                }
            ],
        ),
        phase=WHOLE_PLAN_REVIEW,
        loop_id="review-whole-plan-01",
    )
    provider = _cursor_provider(
        tmp_path,
        streams=[
            _cursor_stream(session_id="chat-reviewer-1", text="initial review"),
            _cursor_stream(session_id="chat-planner-1", text="planner revises"),
            _cursor_stream(session_id="chat-reviewer-1", text="verification recheck"),
        ],
        on_turn_start=[respond, None, None],
    )

    orchestrator = WholePlanReviewOrchestrator(store, run_id, provider)
    orchestrator._append_event = MagicMock()  # type: ignore[method-assign]

    with pytest.raises(ProviderRunError) as exc_info:
        orchestrator.run()

    assert "reviewer session is missing for recheck" not in str(exc_info.value)

    review = store.load_review(run_id, "review-whole-plan-01")
    binding = review["reviewer_binding"]
    assert binding["state"] == "bound"
    assert binding_provider_session_id(binding) == "chat-reviewer-1"
    bound_events = [
        event
        for event in store.load_events(run_id)
        if event.get("type") == SESSION_PROVIDER_ID_BOUND
    ]
    assert any(
        event.get("role") == "reviewer"
        and event.get("provider_session_id") == "chat-reviewer-1"
        for event in bound_events
    )


def test_resolve_reviewer_session_for_recheck_raises_when_replacement_required() -> None:
    binding = (
        new_session_binding(role="reviewer", kind="reviewer", state="starting")
        .with_provider_session_id("cursor-pending-1")
    )
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_binding=binding,
        target_revision=1,
        scope={"kind": "whole_plan"},
        revise_at="major",
        status="changes_requested",
    )
    loop = ReviewLoop.from_dict(
        {
            **loop.to_dict(),
            "finding_actions": [
                {
                    "finding_id": "finding-001",
                    "finding_set_id": "review-whole-plan-01-fs-01",
                    "action": "fix",
                    "actor_role": "planner",
                    "artifact_revision": 2,
                    "rationale": "fixed",
                }
            ],
            "revision_cycles": 1,
            "lifecycle_status": "revision_in_progress",
        }
    )

    with pytest.raises(ReviewerRecheckRequiresNewSession):
        resolve_reviewer_session_for_recheck(
            loop,
            target_revision=1,
            current_revision=2,
        )


def test_consume_provider_turn_returns_canonical_reviewer_session_id(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T010003-010003"
    _create_run_at_whole_plan_review(store, run_id=run_id)
    provider = _cursor_provider(
        tmp_path,
        streams=[_cursor_stream(session_id="chat-reviewer-1", text="reviewed")],
    )
    session_id = provider.start_reviewer_session({"loop_id": "review-whole-plan-01"})

    outcome = consume_reviewer_provider_turn_with_session_recovery(
        store,
        run_id,
        provider,
        session_id,
        loop_id="review-whole-plan-01",
        recovery=build_reviewer_turn_recovery(
            store,
            run_id,
            loop_id="review-whole-plan-01",
            phase=WHOLE_PLAN_REVIEW,
            expected_next_action="continue review",
            append_event=lambda *_args, **_kwargs: None,
            model=None,
            review_package={"loop_id": "review-whole-plan-01"},
        ),
    )

    assert outcome.session_id == "chat-reviewer-1"
    assert provider.canonical_session_id(session_id) == "chat-reviewer-1"
