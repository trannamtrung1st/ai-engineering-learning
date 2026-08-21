"""Regression tests for Slice 3 round-8 review (TDP-PERSIST-023..031, CORE-PERSIST-002)."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.persistence import (
    PersistenceError,
    RunNotFoundError,
    StoreRevisionConflictError,
    TransactionRecoveryError,
    atomic_write_bytes,
    atomic_write_json,
)
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.persistence import FileRunStore
from top_down_planning.domain.review_loop_factory import new_focused_review_loop
from top_down_planning.persistence.commit import CommitSpec
from tests.helpers import create_run_kwargs, events_append_boundary, minimal_resolved_config
from tests.support.persistence import _create_run, _multi_file_commit
from tests.support.persistence import _find_txn_dir_local


def _sample_plan(run_id: str = "run-20260101T000901-000901") -> Plan:
    return Plan(
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
    )


def _crash_before_appending_events_status() -> object:
    original = atomic_write_json
    calls = 0

    def patched(path: Path, payload: dict[str, object]) -> None:
        nonlocal calls
        if path.name == "journal.json" and payload.get("status") == "appending_events":
            calls += 1
            if calls == 1:
                raise OSError("simulated crash before appending_events publication")
        original(path, payload)

    return patched


def test_recovery_rejects_traversal_review_id(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_a = "run-20260101T000901-000901"
    run_b = "run-20260101T000902-000902"
    _create_run(store, run_a)
    _create_run(store, run_b)
    run_b_before = (store.run_dir(run_b) / "run.json").read_bytes()

    txn_id = "evil-review"
    txn_dir = store.run_dir(run_a) / f".txn-{txn_id}"
    txn_dir.mkdir()
    atomic_write_json(
        txn_dir / "journal.json",
        {
            "txn_id": txn_id,
            "status": "replacing",
            "files": [
                {
                    "kind": "review",
                    "name": "review__../../run-20260101T000902-000902/run.json",
                    "review_id": "../../run-20260101T000902-000902/run",
                    "digest": "deadbeef",
                    "had_destination": False,
                }
            ],
            "events": [],
            "backups": [],
            "replaced": ["review__../../run-20260101T000902-000902/run.json"],
        },
    )

    with pytest.raises(TransactionRecoveryError):
        FileRunStore(tmp_path).load_run(run_a)

    assert (store.run_dir(run_b) / "run.json").read_bytes() == run_b_before


def test_event_only_replacing_crash_recovers_event(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"
    _create_run(store, run_id)
    event = {"type": "audit_only", "run_id": run_id, "detail": "round8"}

    with patch(
        "top_down_planning.persistence.file_store.atomic_write_json",
        _crash_before_appending_events_status(),
    ):
        with pytest.raises(OSError, match="simulated crash"):
            store.append_event(run_id, event)

    txn_dir = _find_txn_dir_local(store, run_id)
    assert txn_dir is not None
    journal = json.loads((txn_dir / "journal.json").read_text(encoding="utf-8"))
    assert journal["status"] == "replacing"
    assert journal["files"] == []

    for _ in range(2):
        reopened = FileRunStore(tmp_path)
        events = reopened.load_events(run_id)
        matches = [item for item in events if item.get("type") == "audit_only"]
        assert len(matches) == 1
        assert matches[0]["detail"] == "round8"
        assert not list(reopened.run_dir(run_id).glob(".txn-*"))


def test_save_plan_updates_run_plan_digest(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"
    _create_run(store, run_id)
    before_run = store.load_run(run_id)
    plan = store.load_plan(run_id)
    plan["revision"] = 1
    for item in plan["items"]:
        if item.get("id") == "item-root":
            item["title"] = "Changed"
            break
    store.save_plan(run_id, plan, 0)

    after_run = store.load_run(run_id)
    after_plan = store.load_plan(run_id)
    from top_down_planning.persistence.digests import compute_plan_digest

    assert int(after_run["revision"]) == int(before_run["revision"]) + 1
    assert after_run["digests"]["plan"] == compute_plan_digest(after_plan)


def test_review_update_without_expected_revision_conflicts(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"
    _create_run(store, run_id)
    loop = new_focused_review_loop(
        loop_id="review-loop-1",
        review_type="focused_plan",
        target_revision=0,
        scope={"kind": "plan"},
        config=minimal_resolved_config(),
    )
    store.commit(run_id, CommitSpec(reviews=[loop.to_dict()]))
    stale = dict(loop.to_dict())
    stale["status"] = "stale"

    with pytest.raises(PersistenceError, match="store revision conflict"):
        store.commit(run_id, CommitSpec(reviews=[stale]))


def test_incomplete_run_rejects_append_event(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"
    run_dir = store.run_dir(run_id)
    run_dir.mkdir(parents=True)

    with pytest.raises(RunNotFoundError):
        store.append_event(run_id, {"type": "orphan", "run_id": run_id})


def test_non_contiguous_txn_events_fail_integrity(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"
    _create_run(store, run_id)
    events_path = store.run_dir(run_id) / "events.jsonl"
    base = events_path.read_text(encoding="utf-8")
    interleaved = base
    interleaved += json.dumps(
        {
            "type": "a0",
            "run_id": run_id,
            "txn_id": "txn-a",
            "event_index": 0,
            "event_count": 2,
            "ts": "2026-01-01T00:00:00Z",
        },
        sort_keys=True,
    ) + "\n"
    interleaved += json.dumps(
        {
            "type": "between",
            "run_id": run_id,
            "txn_id": "txn-b",
            "event_index": 0,
            "event_count": 1,
            "ts": "2026-01-01T00:00:01Z",
        },
        sort_keys=True,
    ) + "\n"
    interleaved += json.dumps(
        {
            "type": "a1",
            "run_id": run_id,
            "txn_id": "txn-a",
            "event_index": 1,
            "event_count": 2,
            "ts": "2026-01-01T00:00:02Z",
        },
        sort_keys=True,
    ) + "\n"
    events_path.write_text(interleaved, encoding="utf-8")

    with pytest.raises(PersistenceError, match="not contiguous"):
        store.load_events(run_id)


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink checks")
def test_symlinked_reviews_dir_is_rejected(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_a = "run-20260101T000901-000901"
    run_b = "run-20260101T000902-000902"
    _create_run(store, run_a)
    _create_run(store, run_b)
    reviews_b = store.reviews_dir(run_b)
    reviews_b.mkdir(parents=True, exist_ok=True)
    reviews_a = store.run_dir(run_a) / "reviews"
    if reviews_a.is_dir():
        reviews_a.rmdir()
    reviews_a.symlink_to(reviews_b)

    with pytest.raises(PersistenceError, match="must not be a symlink"):
        store.load_run(run_a)


def test_atomic_write_bytes_concurrent_writes_leave_one_complete_payload(
    tmp_path: Path,
) -> None:
    target = tmp_path / "payload.bin"
    barrier = threading.Barrier(2)
    payloads = [b"payload-a-bytes", b"payload-b-bytes-longer"]

    def writer(data: bytes) -> None:
        barrier.wait()
        atomic_write_bytes(target, data)

    threads = [threading.Thread(target=writer, args=(payload,)) for payload in payloads]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert target.read_bytes() in payloads
    assert not list(tmp_path.glob(".*.tmp-*"))
