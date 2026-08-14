"""Session binding domain and persistence tests (§21 test 40)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.session_bindings import (
    SessionBinding,
    SessionBindingError,
    is_transient_provider_session_id,
    new_session_binding,
    resumable_binding_provider_session_id,
)
from top_down_planning.orchestrator.reviewer_session import reviewer_loop_provider_session_id
from top_down_planning.orchestrator.session_events import sync_persisted_session_id
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.session_bindings import (
    LegacySessionFieldError,
    coerce_structured_sessions,
    primary_provider_session_id,
    sessions_for_persistence,
)
from tests.helpers import create_run_kwargs, make_review_loop


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


def test_binding_accepts_transient_provider_session_id_in_starting_state() -> None:
    binding = new_session_binding(role="planner", kind="primary", state="unbound")
    updated = binding.with_provider_session_id("cursor-pending-1")
    assert updated.provider_session_id == "cursor-pending-1"
    assert updated.state == "starting"


def test_bound_binding_rejects_transient_provider_session_id_on_load() -> None:
    with pytest.raises(SessionBindingError, match="not allowed when binding state is bound"):
        SessionBinding.from_dict(
            {
                "session_instance_id": "tdp-session-test",
                "generation": 1,
                "role": "planner",
                "kind": "primary",
                "state": "bound",
                "provider_session_id": "cursor-pending-1",
            }
        )


def test_review_loop_accepts_transient_reviewer_provider_session_id() -> None:
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id=None,
        target_revision=1,
        scope={"kind": "whole_plan"},
        revise_at="major",
    )
    updated = loop.with_reviewer_provider_session_id("cursor-pending-1")
    assert updated.reviewer_session_id == "cursor-pending-1"
    assert updated.reviewer_binding is not None
    assert updated.reviewer_binding.state == "starting"
    assert updated.reviewer_binding.provider_session_id == "cursor-pending-1"


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
    reviewer_binding = new_session_binding(
        role="reviewer",
        kind="reviewer",
    ).with_provider_session_id("reviewer-sess")
    loop = make_review_loop(
        id="loop-1",
        type="focused_plan",
        reviewer_session_id="reviewer-sess",
        reviewer_binding=reviewer_binding,
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
                "review_record_schema_version": 2,
                "review_contract_version": 2,
            }
        )


def test_sync_persisted_session_id_skips_transient_cursor_pending(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T004002-004002"
    _create_run(store, run_id)

    class _PendingProvider:
        def canonical_session_id(self, session_id: str) -> str:
            return session_id

        def get_session_reference(self, session_id: str) -> dict:
            return {
                "role": "planner",
                "kind": "primary",
                "session_id": session_id,
            }

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


def test_primary_provider_session_id_ignores_starting_pending_binding(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T004004-004004"
    _create_run(store, run_id)
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    binding = new_session_binding(role="planner", kind="primary", state="starting")
    binding = binding.with_provider_session_id("cursor-pending-1")
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["sessions"] = {
        **dict(run.get("sessions") or {}),
        "primary_planner": binding.to_dict(),
    }
    store.save_run(run_id, run, expected_revision)

    persisted = store.load_run(run_id)
    assert persisted["sessions"]["primary_planner"]["provider_session_id"] == "cursor-pending-1"
    assert primary_provider_session_id(persisted, "planner") is None
    assert resumable_binding_provider_session_id(binding) is None


def test_reviewer_loop_provider_session_id_ignores_starting_pending_binding() -> None:
    loop = make_review_loop(
        id="review-focused-plan-01",
        type="focused_plan",
        reviewer_session_id=None,
        target_revision=1,
        scope={"kind": "focused_plan", "item_ids": ["item-root"]},
        revise_at="blocker",
    )
    updated = loop.with_reviewer_provider_session_id("cursor-pending-1")
    assert updated.reviewer_binding is not None
    assert updated.reviewer_binding.provider_session_id == "cursor-pending-1"
    assert reviewer_loop_provider_session_id(updated) is None


def test_with_provider_session_id_rejects_bound_to_transient_downgrade() -> None:
    binding = (
        new_session_binding(role="planner", kind="primary", state="starting")
        .with_provider_session_id("cursor-durable-1")
    )
    assert binding.state == "bound"
    with pytest.raises(SessionBindingError, match="cannot downgrade bound durable"):
        binding.with_provider_session_id("cursor-pending-1")


def test_commit_primary_provider_session_binding_idempotent_for_starting_pending(
    tmp_path: Path,
) -> None:
    from top_down_planning.orchestrator.session_events import (
        commit_primary_provider_session_binding,
    )

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T004005-004005"
    _create_run(store, run_id)
    commit_primary_provider_session_binding(
        store,
        run_id,
        role="planner",
        provider_session_id="cursor-pending-1",
        provider="cursor",
    )
    after_first = store.load_run(run_id)
    commit_primary_provider_session_binding(
        store,
        run_id,
        role="planner",
        provider_session_id="cursor-pending-1",
        provider="cursor",
    )
    after_second = store.load_run(run_id)
    assert after_second["revision"] == after_first["revision"]


def test_with_reviewer_session_released_preserves_unbound_binding() -> None:
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id=None,
        target_revision=0,
        scope={"kind": "whole_plan"},
        revise_at="blocker",
    )
    released_binding = (
        new_session_binding(role="reviewer", kind="reviewer", state="unbound")
        .released_for_reallocation()
    )
    loop = replace(loop, reviewer_binding=released_binding)
    updated = loop.with_reviewer_session_released()
    assert updated.reviewer_binding is not None
    assert updated.reviewer_binding.state == "unbound"
    assert updated.reviewer_binding.provider_session_id is None
    assert updated.reviewer_session_id is None


def test_with_reviewer_session_released_clears_bound_provider_session() -> None:
    reviewer_binding = new_session_binding(
        role="reviewer",
        kind="reviewer",
    ).with_provider_session_id("reviewer-sess")
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="reviewer-sess",
        reviewer_binding=reviewer_binding,
        target_revision=0,
        scope={"kind": "whole_plan"},
        revise_at="blocker",
    )
    updated = loop.with_reviewer_session_released()
    assert updated.reviewer_binding is not None
    assert updated.reviewer_binding.state == "unbound"
    assert updated.reviewer_binding.provider_session_id is None
    assert updated.reviewer_session_id is None
