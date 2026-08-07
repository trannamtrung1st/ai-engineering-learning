"""Regression tests for Slice 3 persistence review findings (TDP-PERSIST-001..006)."""

from __future__ import annotations

import json
import multiprocessing
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from core_tools.persistence import TransactionRecoveryError, atomic_write_json, digest_file
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.persistence import FileRunStore, PersistenceError
from top_down_planning.persistence.commit import CommitSpec
from tests.fixtures.persistence_review_worker import concurrent_create_worker
from tests.helpers import create_run_kwargs, minimal_resolved_config
from tests.unit.test_persistence_correction_fixes import (
    test_load_resolved_config_blocks_behind_active_commit_lock,
)


def _sample_plan(run_id: str = "run-20260101T000801-000801") -> Plan:
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


def _create_run(store: FileRunStore, run_id: str = "run-20260101T000801-000801") -> None:
    store.create_run(
        run_id,
        plan=_sample_plan(run_id),
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
    )


def _find_txn_dir(store: FileRunStore, run_id: str) -> Path | None:
    txn_dirs = sorted(store.run_dir(run_id).glob(".txn-*"))
    return txn_dirs[0] if txn_dirs else None


def test_create_run_publishes_run_created_event_with_directory_rename(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    captured: list[str] = []
    original_rename = Path.rename

    def capture_rename(self: Path, target: Path) -> Path:
        result = original_rename(self, target)
        events_path = target / "events.jsonl"
        if events_path.is_file():
            captured.append(events_path.read_text(encoding="utf-8"))
        return result

    with patch.object(Path, "rename", capture_rename):
        store.create_run(
            run_id,
            plan=_sample_plan(run_id),
            **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
        )

    assert len(captured) == 1
    payload = json.loads(captured[0].strip())
    assert payload["type"] == "run_created"
    assert payload["run_id"] == run_id


def test_create_run_after_rename_has_run_created_without_followup_commit(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    original_rename = Path.rename

    def crash_after_rename(self: Path, target: Path) -> Path:
        result = original_rename(self, target)
        raise OSError("simulated crash after rename")

    with patch.object(Path, "rename", crash_after_rename):
        with pytest.raises(OSError, match="simulated crash after rename"):
            store.create_run(
                run_id,
                plan=_sample_plan(run_id),
                **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
            )

    recovered = FileRunStore(tmp_path)
    events = recovered.load_events(run_id)
    assert len(events) == 1
    assert events[0]["type"] == "run_created"
    assert events[0]["run_id"] == run_id


def _crash_after_nth_event_write(line_number: int) -> Any:
    original_open = Path.open
    writes = 0

    def patched_open(self: Path, *args: Any, **kwargs: Any):
        handle = original_open(self, *args, **kwargs)
        if self.name != "events.jsonl" or "a" not in args and kwargs.get("mode") != "a":
            return handle
        original_write = handle.write

        def patched_write(data: str) -> int:
            nonlocal writes
            if data.endswith("\n"):
                writes += 1
                if writes == line_number:
                    raise OSError("simulated crash during event append")
            return original_write(data)

        handle.write = patched_write  # type: ignore[method-assign]
        return handle

    return patched_open


def test_partial_multi_event_append_recovered_on_reopen(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)

    events = [
        {"type": "event_a", "run_id": run_id},
        {"type": "event_b", "run_id": run_id},
        {"type": "event_c", "run_id": run_id},
    ]
    with patch.object(Path, "open", _crash_after_nth_event_write(1)):
        with pytest.raises(OSError, match="simulated crash"):
            store.commit(run_id, CommitSpec(events=events))

    txn_dir = _find_txn_dir(store, run_id)
    assert txn_dir is not None
    journal = json.loads((txn_dir / "journal.json").read_text(encoding="utf-8"))
    assert journal["status"] == "appending_events"

    recovered = FileRunStore(tmp_path)
    loaded = recovered.load_events(run_id)
    event_types = [event["type"] for event in loaded if event["type"] != "run_created"]
    assert event_types == ["event_a", "event_b", "event_c"]
    txn_ids = {event["txn_id"] for event in loaded if event["type"] != "run_created"}
    assert txn_ids == {journal["txn_id"]}
    assert not _find_txn_dir(recovered, run_id)


def test_partial_event_json_line_truncated_and_recovered(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)
    events_path = store.run_dir(run_id) / "events.jsonl"
    first_event = json.dumps(
        {
            "type": "event_a",
            "run_id": run_id,
            "txn_id": "partial",
            "event_index": 0,
            "event_count": 2,
            "ts": "2026-01-01T00:00:00Z",
        },
        sort_keys=True,
    )
    events_path.write_text(
        events_path.read_text(encoding="utf-8") + first_event + "\n" + '{"type": "event_b", "txn_id": "partial',
        encoding="utf-8",
    )

    txn_dir = store.run_dir(run_id) / ".txn-partial"
    txn_dir.mkdir()
    atomic_write_json(
        txn_dir / "journal.json",
        {
            "txn_id": "partial",
            "status": "appending_events",
            "files": [],
            "events": [
                {
                    "type": "event_a",
                    "run_id": run_id,
                    "txn_id": "partial",
                    "event_index": 0,
                    "event_count": 2,
                },
                {
                    "type": "event_b",
                    "run_id": run_id,
                    "txn_id": "partial",
                    "event_index": 1,
                    "event_count": 2,
                },
            ],
            "backups": [],
            "replaced": [],
        },
    )

    recovered = FileRunStore(tmp_path)
    loaded = recovered.load_events(run_id)
    recovered_types = [
        event["type"] for event in loaded if event.get("txn_id") == "partial"
    ]
    assert recovered_types == ["event_a", "event_b"]
    trailing = events_path.read_text(encoding="utf-8")
    assert trailing.endswith("\n")
    assert not trailing.rstrip("\n").endswith('{"type": "event_b", "txn_id": "partial')
    assert not _find_txn_dir(recovered, run_id)


def test_unknown_transaction_status_fails_closed_and_retains_evidence(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)
    run_before = store.load_run(run_id)

    txn_dir = store.run_dir(run_id) / ".txn-unknown"
    txn_dir.mkdir()
    backups_dir = txn_dir / "backups"
    backups_dir.mkdir()
    staged_run = dict(run_before)
    staged_run["revision"] = int(run_before["revision"]) + 1
    atomic_write_json(txn_dir / "run.json", staged_run)
    shutil_copy = store.run_dir(run_id) / "run.json"
    shutil_copy_path = backups_dir / "run.json"
    shutil_copy_path.write_bytes(shutil_copy.read_bytes())
    replaced_run = dict(staged_run)
    replaced_run["status"] = "corrupted-marker"
    atomic_write_json(store.run_dir(run_id) / "run.json", replaced_run)
    atomic_write_json(
        txn_dir / "journal.json",
        {
            "txn_id": "unknown",
            "status": "unknown_state",
            "files": [
                {
                    "kind": "run",
                    "name": "run.json",
                    "digest": digest_file(txn_dir / "run.json"),
                }
            ],
            "events": [],
            "backups": ["run.json"],
            "replaced": ["run.json"],
        },
    )

    recovered = FileRunStore(tmp_path)
    with pytest.raises(TransactionRecoveryError, match="unknown transaction status"):
        recovered.load_run(run_id)

    assert txn_dir.is_dir()
    assert (backups_dir / "run.json").is_file()
    corrupted_run = json.loads((store.run_dir(run_id) / "run.json").read_text(encoding="utf-8"))
    assert corrupted_run["status"] == "corrupted-marker"


def test_load_resolved_config_waits_for_pending_transaction(tmp_path: Path) -> None:
    test_load_resolved_config_blocks_behind_active_commit_lock(tmp_path)


def test_concurrent_create_same_run_id_exactly_one_succeeds(tmp_path: Path) -> None:
    run_id = "run-20260101T000801-000801"
    ctx = multiprocessing.get_context("fork")
    result_queue: multiprocessing.Queue[str] = ctx.Queue()
    barrier = ctx.Barrier(3)
    processes = [
        ctx.Process(
            target=concurrent_create_worker,
            args=(str(tmp_path), run_id, result_queue, barrier),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    barrier.wait()
    for process in processes:
        process.join()
        assert process.exitcode == 0

    results = sorted(result_queue.get(timeout=30) for _ in range(2))
    assert results == ["conflict", "ok"]

    store = FileRunStore(tmp_path)
    events = store.load_events(run_id)
    assert len(events) == 1
    assert events[0]["type"] == "run_created"
    assert not (store.root / f".creating-{run_id}").exists()


def test_missing_transaction_journal_fails_closed(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)
    txn_dir = store.run_dir(run_id) / ".txn-missing-journal"
    txn_dir.mkdir()

    with pytest.raises(TransactionRecoveryError, match="transaction journal missing"):
        store.load_run(run_id)

    assert txn_dir.is_dir()


def test_load_events_rejects_journaled_event_missing_index_fields(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)
    events_path = store.run_dir(run_id) / "events.jsonl"
    events_path.write_text(
        events_path.read_text(encoding="utf-8")
        + json.dumps({"type": "bad", "txn_id": "orphan-txn"}, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(PersistenceError, match="missing required fields"):
        store.load_events(run_id)


def test_load_events_rejects_duplicate_journaled_event_index(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)
    duplicate = {
        "type": "dup",
        "txn_id": "dup-txn",
        "event_index": 0,
        "event_count": 1,
        "ts": "2026-01-01T00:00:00Z",
    }
    line = json.dumps(duplicate, sort_keys=True) + "\n"
    events_path = store.run_dir(run_id) / "events.jsonl"
    events_path.write_text(events_path.read_text(encoding="utf-8") + line + line, encoding="utf-8")

    with pytest.raises(PersistenceError, match="duplicate journaled event"):
        store.load_events(run_id)


def test_load_events_rejects_incomplete_journaled_event_set(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)
    events_path = store.run_dir(run_id) / "events.jsonl"
    events_path.write_text(
        events_path.read_text(encoding="utf-8")
        + json.dumps(
            {
                "type": "only_first",
                "txn_id": "incomplete-txn",
                "event_index": 0,
                "event_count": 2,
                "ts": "2026-01-01T00:00:00Z",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(PersistenceError, match="incomplete journaled event set"):
        store.load_events(run_id)


def test_transaction_journal_txn_id_must_match_staging_directory(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)
    txn_dir = store.run_dir(run_id) / ".txn-mismatch"
    txn_dir.mkdir()
    atomic_write_json(
        txn_dir / "journal.json",
        {
            "txn_id": "different",
            "status": "prepared",
            "files": [],
            "events": [],
            "backups": [],
            "replaced": [],
        },
    )

    with pytest.raises(TransactionRecoveryError, match="txn_id mismatch"):
        store.load_run(run_id)


def test_cleanup_staging_dirs_skips_in_progress_creation_lock(tmp_path: Path) -> None:
    from core_tools.persistence import exclusive_file_lock
    from top_down_planning.orchestrator.run_lifecycle_reconciliation import cleanup_staging_dirs

    store = FileRunStore(tmp_path)
    staging = tmp_path / ".creating-run-20260101T000801-000801"
    staging.mkdir()
    lock_path = tmp_path / ".creating-run-20260101T000801-000801.lock"
    with exclusive_file_lock(lock_path):
        removed = cleanup_staging_dirs(store)
    assert removed == []
    assert staging.is_dir()

    removed_after = cleanup_staging_dirs(store)
    assert removed_after == [".creating-run-20260101T000801-000801"]
    assert not staging.exists()


def test_load_events_requires_run_created_anchor(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)
    events_path = store.run_dir(run_id) / "events.jsonl"
    events_path.write_text(
        json.dumps({"type": "phase_changed", "phase": "production"}, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(PersistenceError, match="must begin with run_created"):
        store.load_events(run_id)


def test_committed_journal_still_reconciles_missing_events(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)

    txn_id = "committed-missing-events"
    txn_dir = store.run_dir(run_id) / f".txn-{txn_id}"
    txn_dir.mkdir()
    atomic_write_json(
        txn_dir / "journal.json",
        {
            "txn_id": txn_id,
            "status": "committed",
            "files": [],
            "events": [
                {"type": "late_event", "run_id": run_id},
                {"type": "late_event_b", "run_id": run_id},
            ],
            "backups": [],
            "replaced": [],
        },
    )

    recovered = FileRunStore(tmp_path)
    events = recovered.load_events(run_id)
    late_types = [event["type"] for event in events if event.get("txn_id") == txn_id]
    assert late_types == ["late_event", "late_event_b"]
    assert not _find_txn_dir(recovered, run_id)


def test_artifact_snapshot_rejects_overwrite(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)
    ref = store.write_artifact_bytes(run_id, "snap-1", "artifact.txt", b"original")
    assert ref == "artifacts/snap-1/artifact.txt"
    with pytest.raises(PersistenceError, match="already exists"):
        store.write_artifact_bytes(run_id, "snap-1", "artifact.txt", b"replacement")
    assert store.artifact_path(run_id, "snap-1", "artifact.txt").read_bytes() == b"original"
