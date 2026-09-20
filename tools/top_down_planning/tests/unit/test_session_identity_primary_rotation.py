"""Primary producer session identity rotation and post-commit safety."""

from __future__ import annotations

from pathlib import Path

import pytest

from core_tools.provider.errors import ProviderSessionMismatchError
from top_down_planning.orchestrator.phases import PRODUCTION
from top_down_planning.orchestrator.provider_turns import production_batch_count
from top_down_planning.domain.session_lineage import (
    SESSION_PROVIDER_IDENTITY_ROTATED,
    SESSION_PROVIDER_ID_BOUND,
)
from top_down_planning.orchestrator.session_events import (
    commit_primary_provider_session_binding,
    sync_persisted_session_id,
)
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.session_bindings import get_primary_binding
from tests.helpers import apply_production
from tests.support.focused_review import create_production_run_open_item_second
from tests.support.forced_id_stub import ForcedIdStub, create_minimal_planning_run


def test_legitimate_primary_session_alias_rotation_rebinds(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T010201-010201"
    create_minimal_planning_run(store, run_id)
    provider = ForcedIdStub()
    stored = "cursor-durable-stored-a"
    durable = "cursor-durable-producer-b"
    provider._ensure_durable_session(durable, role="producer", kind="primary")
    commit_primary_provider_session_binding(
        store,
        run_id,
        role="producer",
        provider_session_id=stored,
        provider="stub",
        session_provider=None,
    )
    provider.aliases[stored] = durable
    resolved = sync_persisted_session_id(
        provider, store, run_id, stored, role="producer"
    )
    assert resolved == durable
    binding = get_primary_binding(store.load_run(run_id), "producer")
    assert binding is not None
    assert binding.provider_session_id == durable
    events = [
        event
        for event in store.load_events(run_id)
        if event.get("type") == SESSION_PROVIDER_IDENTITY_ROTATED
    ]
    assert len(events) == 1
    assert events[0]["old_provider_session_id"] == stored
    assert events[0]["new_provider_session_id"] == durable


def test_transient_pending_alias_promotion_emits_bound_not_rotation(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T010204-010204"
    create_minimal_planning_run(store, run_id)
    provider = ForcedIdStub()
    pending = "cursor-pending-producer"
    durable = "cursor-durable-producer-b"
    provider._ensure_durable_session(durable, role="producer", kind="primary")
    commit_primary_provider_session_binding(
        store,
        run_id,
        role="producer",
        provider_session_id=pending,
        provider="stub",
        session_provider=None,
    )
    provider.aliases[pending] = durable
    sync_persisted_session_id(provider, store, run_id, pending, role="producer")
    rotated = [
        event
        for event in store.load_events(run_id)
        if event.get("type") == SESSION_PROVIDER_IDENTITY_ROTATED
    ]
    bound = [
        event
        for event in store.load_events(run_id)
        if event.get("type") == SESSION_PROVIDER_ID_BOUND
    ]
    assert rotated == []
    assert bound
    assert bound[-1]["provider_session_id"] == durable


def test_unsafe_unrelated_primary_session_identity_rejected(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T010202-010202"
    create_minimal_planning_run(store, run_id)
    provider = ForcedIdStub()
    stored = "cursor-durable-a"
    foreign = "cursor-durable-b"
    provider._ensure_durable_session(stored, role="producer", kind="primary")
    provider._ensure_durable_session(foreign, role="producer", kind="primary")
    commit_primary_provider_session_binding(
        store,
        run_id,
        role="producer",
        provider_session_id=stored,
        provider="stub",
        session_provider=provider,
    )
    with pytest.raises(ProviderSessionMismatchError):
        sync_persisted_session_id(provider, store, run_id, foreign, role="producer")
    binding = get_primary_binding(store.load_run(run_id), "producer")
    assert binding is not None
    assert binding.provider_session_id == stored


def test_committed_production_batch_survives_subsequent_session_identity_rotation(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T010203-010203"
    provider = ForcedIdStub()
    create_production_run_open_item_second(store, provider, run_id=run_id)
    run = store.load_run(run_id)
    binding = get_primary_binding(run, "producer")
    assert binding is not None
    stored_id = binding.provider_session_id
    rotated = "cursor-durable-rotated-producer"
    provider._ensure_durable_session(rotated, role="producer", kind="primary")

    output_revision_before = int(store.load_production(run_id)["output_revision"])
    batches_before = production_batch_count(store, run_id)
    apply_production(
        store,
        run_id,
        {
            "production_revision": int(store.load_production(run_id)["revision"]),
            "plan_items": ["item-second"],
            "dispositions": {
                "item-second": {
                    "disposition": "completed",
                    "evidence": "batch",
                }
            },
            "outputs": [
                {
                    "id": "output-second-batch",
                    "type": "artifact",
                    "ref": "artifacts/second.txt",
                }
            ],
            "contributions": [
                {
                    "item_id": "item-second",
                    "output_refs": ["output-second-batch"],
                    "summary": "batch",
                }
            ],
            "summary": "batch",
        },
        handler="apply",
    )()
    output_revision_after = int(store.load_production(run_id)["output_revision"])
    batches_after = production_batch_count(store, run_id)
    assert batches_after == batches_before + 1
    assert output_revision_after == output_revision_before + 1

    provider.aliases[stored_id] = rotated
    resolved = sync_persisted_session_id(
        provider, store, run_id, stored_id, role="producer"
    )
    assert resolved == rotated
    binding_after = get_primary_binding(store.load_run(run_id), "producer")
    assert binding_after is not None
    assert binding_after.provider_session_id == rotated
    assert production_batch_count(store, run_id) == batches_after
    assert int(store.load_production(run_id)["output_revision"]) == output_revision_after
