"""Session binding domain and persistence tests (§21 test 40)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.session_bindings import (
    SessionBinding,
    SessionBindingError,
    is_transient_provider_session_id,
    new_session_binding,
)
from top_down_planning.orchestrator.session_events import sync_persisted_session_id
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.session_bindings import (
    LegacySessionFieldError,
    coerce_structured_sessions,
    primary_provider_session_id,
    sessions_for_persistence,
)
from tests.helpers import create_run_kwargs


def _sample_plan() -> Plan:
    return Plan(
        id="plan-session-bindings",
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


def test_new_session_binding_emits_structured_fields() -> None:
    binding = new_session_binding(role="planner", kind="primary")
    payload = binding.to_dict()
    assert payload["session_instance_id"].startswith("tdp-session-")
    assert payload["generation"] == 1
    assert payload["role"] == "planner"
    assert payload["kind"] == "primary"
    assert payload["state"] == "unbound"


def test_with_next_generation_allocates_new_session_instance_id() -> None:
    binding = new_session_binding(role="planner", kind="primary", state="starting")
    binding = binding.with_provider_session_id("provider-1")
    next_binding = binding.with_next_generation()
    assert next_binding.generation == binding.generation + 1
    assert next_binding.session_instance_id != binding.session_instance_id
    assert next_binding.session_instance_id.startswith("tdp-session-")
    assert next_binding.provider_session_id is None
    assert next_binding.state == "starting"


def test_transient_provider_session_id_detection() -> None:
    assert is_transient_provider_session_id("cursor-pending-1")
    assert not is_transient_provider_session_id("cursor-abc123")


def test_bound_binding_rejects_transient_provider_session_id() -> None:
    binding = new_session_binding(role="planner", kind="primary", state="starting")
    with pytest.raises(SessionBindingError, match="transient"):
        binding.with_provider_session_id("cursor-pending-1")


def test_coerce_structured_sessions_rejects_legacy_primary_fields() -> None:
    with pytest.raises(LegacySessionFieldError, match="primary_.*_session_id"):
        coerce_structured_sessions(
            {
                "primary_planner_session_id": "planner-sess-1",
                "primary_producer_session_id": "producer-sess-1",
            }
        )


def test_sessions_for_persistence_rejects_legacy_fields() -> None:
    with pytest.raises(LegacySessionFieldError, match="primary_planner_session_id"):
        sessions_for_persistence(
            {
                "primary_planner": new_session_binding(
                    role="planner",
                    kind="primary",
                    state="starting",
                )
                .with_provider_session_id("planner-sess")
                .to_dict(),
                "primary_planner_session_id": "legacy-should-drop",
            }
        )


def test_new_run_record_uses_structured_sessions(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T004001-004001"
    _create_run(store, run_id)
    run = store.load_run(run_id)
    assert "primary_planner" in run["sessions"]
    assert primary_provider_session_id(run, "planner") is None
    persisted = json.loads((store.run_dir(run_id) / "run.json").read_text(encoding="utf-8"))
    assert "primary_planner_session_id" not in persisted["sessions"]
    assert persisted["sessions"]["primary_planner"]["state"] == "unbound"


def test_review_loop_serializes_reviewer_binding() -> None:
    loop = ReviewLoop(
        id="loop-1",
        type="focused_plan",
        reviewer_session_id="reviewer-sess",
        target_revision=1,
        scope={},
        revise_at="blocker",
    )
    payload = loop.to_dict()
    assert "reviewer_session_id" not in payload
    assert payload["reviewer_binding"]["provider_session_id"] == "reviewer-sess"
    roundtrip = ReviewLoop.from_dict(payload)
    assert roundtrip.reviewer_session_id == "reviewer-sess"
    assert roundtrip.reviewer_binding is not None


def test_review_loop_from_dict_rejects_legacy_reviewer_session_id() -> None:
    with pytest.raises(ValueError, match="reviewer_session_id"):
        ReviewLoop.from_dict(
            {
                "id": "loop-legacy",
                "type": "focused_plan",
                "reviewer_session_id": "reviewer-sess",
                "target_revision": 1,
                "scope": {},
                "revise_at": "blocker",
            }
        )


def test_sync_persisted_session_id_skips_transient_cursor_pending(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T004002-004002"
    _create_run(store, run_id)

    class _PendingProvider:
        def canonical_session_id(self, session_id: str) -> str:
            return session_id

    provider = _PendingProvider()
    resolved = sync_persisted_session_id(
        provider,
        store,
        run_id,
        "cursor-pending-1",
        role="planner",
    )
    assert resolved == "cursor-pending-1"
    persisted = json.loads((store.run_dir(run_id) / "run.json").read_text(encoding="utf-8"))
    planner = persisted["sessions"]["primary_planner"]
    assert planner.get("provider_session_id") is None
    assert planner["state"] in {"unbound", "starting"}

    sync_persisted_session_id(
        provider,
        store,
        run_id,
        "cursor-durable-abc",
        role="planner",
    )
    persisted = json.loads((store.run_dir(run_id) / "run.json").read_text(encoding="utf-8"))
    assert persisted["sessions"]["primary_planner"]["provider_session_id"] == "cursor-durable-abc"
    assert persisted["sessions"]["primary_planner"]["state"] == "bound"


def test_grant_capability_emits_structured_binding_fields(tmp_path: Path) -> None:
    from tests.helpers import grant_capability

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T004003-004003"
    _create_run(store, run_id)
    grant_capability(store, run_id, role="planner", session_id="planner-cap-sess")
    run = store.load_run(run_id)
    binding = run["sessions"]["primary_planner"]
    assert binding["provider_session_id"] == "planner-cap-sess"
    assert binding["session_instance_id"].startswith("tdp-session-")
    assert primary_provider_session_id(run, "planner") == "planner-cap-sess"
