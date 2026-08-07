"""Regression tests for Slice 3 correction review (TDP-PERSIST-003..011)."""

from __future__ import annotations

import copy
import json
import multiprocessing
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from core_tools.persistence import TransactionRecoveryError, atomic_write_json, digest_file
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.run_lifecycle import StopRecord
from top_down_planning.orchestrator.run_transitions import (
    complete_run_with_outcome,
    fail_run,
    pause_run,
)
from top_down_planning.persistence import FileRunStore, PersistenceError
from tests.fixtures.persistence_review_worker import (
    commit_lock_writer_worker,
    load_config_reader_worker,
)
from tests.helpers import create_run_kwargs, events_append_boundary, minimal_resolved_config
from tests.unit.test_commit_crash_recovery import (
    _crash_before_appending_events,
    _find_txn_dir,
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


def _find_txn_dir_local(store: FileRunStore, run_id: str) -> Path | None:
    txn_dirs = sorted(store.run_dir(run_id).glob(".txn-*"))
    return txn_dirs[0] if txn_dirs else None


def _pause_stop_record() -> StopRecord:
    return StopRecord(
        code="limit_exhausted",
        category="operational",
        phase="planning",
        message="test stop",
        details={"limit": "limits.planning.max_agent_turns", "consumed": 1, "configured": 1},
    )


def _fail_stop_record() -> StopRecord:
    return StopRecord(
        code="orchestrator_invariant_failure",
        category="invariant",
        phase="planning",
        message="test failure",
    )


def test_replacing_journal_missing_files_retains_evidence(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)
    run_before = store.load_run(run_id)

    txn_dir = store.run_dir(run_id) / ".txn-missing-files"
    txn_dir.mkdir()
    backups_dir = txn_dir / "backups"
    backups_dir.mkdir()
    staged_run = dict(run_before)
    staged_run["revision"] = int(run_before["revision"]) + 1
    atomic_write_json(txn_dir / "run.json", staged_run)
    (backups_dir / "run.json").write_bytes((store.run_dir(run_id) / "run.json").read_bytes())
    corrupted_run = dict(staged_run)
    corrupted_run["status"] = "corrupted-marker"
    atomic_write_json(store.run_dir(run_id) / "run.json", corrupted_run)
    atomic_write_json(
        txn_dir / "journal.json",
        {
            "txn_id": "missing-files",
            "status": "replacing",
            "events": [],
            "backups": ["run.json"],
            "replaced": ["run.json"],
        },
    )

    recovered = FileRunStore(tmp_path)
    with pytest.raises(TransactionRecoveryError, match="missing files"):
        recovered.load_run(run_id)

    assert txn_dir.is_dir()
    assert (backups_dir / "run.json").is_file()
    on_disk = json.loads((store.run_dir(run_id) / "run.json").read_text(encoding="utf-8"))
    assert on_disk["status"] == "corrupted-marker"


def test_appending_events_journal_missing_events_retains_evidence(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)

    txn_dir = store.run_dir(run_id) / ".txn-missing-events"
    txn_dir.mkdir()
    atomic_write_json(
        txn_dir / "journal.json",
        {
            "txn_id": "missing-events",
            "status": "appending_events",
            "files": [],
            "backups": [],
            "replaced": [],
        },
    )
    events_before = (store.run_dir(run_id) / "events.jsonl").read_bytes()

    recovered = FileRunStore(tmp_path)
    with pytest.raises(TransactionRecoveryError, match="missing events"):
        recovered.load_events(run_id)

    assert txn_dir.is_dir()
    assert (store.run_dir(run_id) / "events.jsonl").read_bytes() == events_before


def test_journal_missing_status_fails_closed(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)

    txn_dir = store.run_dir(run_id) / ".txn-missing-status"
    txn_dir.mkdir()
    atomic_write_json(
        txn_dir / "journal.json",
        {
            "txn_id": "missing-status",
            "files": [],
            "events": [],
            "backups": [],
            "replaced": [],
        },
    )

    with pytest.raises(TransactionRecoveryError, match="missing status"):
        FileRunStore(tmp_path).load_run(run_id)

    assert txn_dir.is_dir()


def test_journal_malformed_file_entry_fails_closed(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)

    txn_dir = store.run_dir(run_id) / ".txn-bad-file"
    txn_dir.mkdir()
    atomic_write_json(
        txn_dir / "journal.json",
        {
            "txn_id": "bad-file",
            "status": "prepared",
            "files": [{"kind": "unknown_kind", "name": "run.json", "digest": "abc", "had_destination": False}],
            "events": [],
            "backups": [],
            "replaced": [],
        },
    )

    with pytest.raises(TransactionRecoveryError, match="unknown kind"):
        FileRunStore(tmp_path).load_run(run_id)

    assert txn_dir.is_dir()


def test_load_events_preserves_valid_single_event_without_terminal_newline(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)
    events_path = store.run_dir(run_id) / "events.jsonl"
    payload = json.loads(events_path.read_text(encoding="utf-8").strip())
    events_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    raw_before = events_path.read_bytes()

    loaded = FileRunStore(tmp_path).load_events(run_id)
    assert loaded[0]["type"] == "run_created"
    assert events_path.read_bytes() == raw_before


def test_load_events_preserves_valid_final_event_without_terminal_newline(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)
    events_path = store.run_dir(run_id) / "events.jsonl"
    extra = {
        "type": "phase_changed",
        "run_id": run_id,
        "txn_id": "plain-txn",
        "event_index": 0,
        "event_count": 1,
        "ts": "2026-01-01T00:00:00Z",
    }
    events_path.write_text(
        events_path.read_text(encoding="utf-8").rstrip("\n")
        + "\n"
        + json.dumps(extra, sort_keys=True),
        encoding="utf-8",
    )
    raw_before = events_path.read_bytes()

    loaded = FileRunStore(tmp_path).load_events(run_id)
    assert [event["type"] for event in loaded] == ["run_created", "phase_changed"]
    assert events_path.read_bytes() == raw_before


def test_load_events_rejects_invalid_trailing_fragment_without_journal(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)
    events_path = store.run_dir(run_id) / "events.jsonl"
    events_path.write_text(
        events_path.read_text(encoding="utf-8") + '{"type": "broken", "txn_id": "orphan"',
        encoding="utf-8",
    )
    raw_before = events_path.read_bytes()

    with pytest.raises(PersistenceError, match="malformed events.jsonl"):
        FileRunStore(tmp_path).load_events(run_id)

    assert events_path.read_bytes() == raw_before


def test_recovery_rejects_out_of_order_transaction_event_indices(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)
    events_path = store.run_dir(run_id) / "events.jsonl"
    second_only = json.dumps(
        {
            "type": "event_b",
            "run_id": run_id,
            "txn_id": "out-of-order",
            "event_index": 1,
            "event_count": 2,
            "ts": "2026-01-01T00:00:00Z",
        },
        sort_keys=True,
    )
    boundary = events_append_boundary(events_path)
    events_path.write_text(events_path.read_text(encoding="utf-8") + second_only + "\n", encoding="utf-8")
    raw_before = events_path.read_bytes()

    txn_dir = store.run_dir(run_id) / ".txn-out-of-order"
    txn_dir.mkdir()
    atomic_write_json(
        txn_dir / "journal.json",
        {
            "txn_id": "out-of-order",
            "status": "appending_events",
            "files": [],
            "events": [
                {
                    "type": "event_a",
                    "run_id": run_id,
                    "txn_id": "out-of-order",
                    "event_index": 0,
                    "event_count": 2,
                },
                {
                    "type": "event_b",
                    "run_id": run_id,
                    "txn_id": "out-of-order",
                    "event_index": 1,
                    "event_count": 2,
                },
            ],
            "backups": [],
            "replaced": [],
            **boundary,
        },
    )

    with pytest.raises(TransactionRecoveryError, match="suffix mismatch"):
        FileRunStore(tmp_path).load_events(run_id)

    assert txn_dir.is_dir()
    assert events_path.read_bytes() == raw_before


def test_save_invocation_recovers_before_write_and_preserves_new_metadata(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)
    invocation_path = store.run_dir(run_id) / "invocation.json"
    original = store.load_invocation(run_id)

    txn_dir = store.run_dir(run_id) / ".txn-invocation"
    txn_dir.mkdir()
    backups_dir = txn_dir / "backups"
    backups_dir.mkdir()
    staged_invocation = dict(original)
    staged_invocation["marker"] = "staged"
    atomic_write_json(txn_dir / "invocation.json", staged_invocation)
    (backups_dir / "invocation.json").write_bytes(invocation_path.read_bytes())
    atomic_write_json(invocation_path, staged_invocation)
    atomic_write_json(
        txn_dir / "journal.json",
        {
            "txn_id": "invocation",
            "status": "replacing",
            "files": [
                {
                    "kind": "invocation",
                    "name": "invocation.json",
                    "digest": "deadbeef",
                    "had_destination": True,
                }
            ],
            "events": [],
            "backups": ["invocation.json"],
            "replaced": ["invocation.json"],
        },
    )

    saved = {"command": "resume", "marker": "saved-after-recovery"}
    store.save_invocation(run_id, saved)

    assert store.load_invocation(run_id) == saved
    reopened = FileRunStore(tmp_path)
    assert reopened.load_invocation(run_id) == saved
    assert not _find_txn_dir_local(reopened, run_id)


@pytest.mark.parametrize(
    ("transition", "expected_status", "expected_event"),
    [
        (lambda store, run_id: pause_run(store, run_id, stop=_pause_stop_record()), "paused", "run_paused"),
        (lambda store, run_id: fail_run(store, run_id, stop=_fail_stop_record()), "failed", "run_failed"),
        (
            lambda store, run_id: complete_run_with_outcome(store, run_id, "success"),
            "completed",
            "run_completed",
        ),
    ],
)
def test_lifecycle_transition_crash_after_run_replace_recovers_run_and_event(
    tmp_path: Path,
    transition,
    expected_status: str,
    expected_event: str,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)
    events_before = store.load_events(run_id)

    with patch("top_down_planning.persistence.file_store.atomic_write_json", _crash_before_appending_events()):
        with pytest.raises(OSError, match="simulated crash"):
            transition(store, run_id)

    txn_dir = _find_txn_dir(store, run_id)
    assert txn_dir is not None
    journal = json.loads((txn_dir / "journal.json").read_text(encoding="utf-8"))
    assert journal["status"] == "appending_events"

    recovered = FileRunStore(tmp_path)
    run_after = recovered.load_run(run_id)
    assert run_after["status"] == expected_status
    events_after = recovered.load_events(run_id)
    lifecycle_events = [
        event for event in events_after if event.get("type") == expected_event
    ]
    assert len(lifecycle_events) == 1
    assert lifecycle_events[0]["txn_id"] == journal["txn_id"]
    assert len(events_after) == len(events_before) + 1
    assert not _find_txn_dir(recovered, run_id)


def test_load_resolved_config_blocks_behind_active_commit_lock(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)
    run_dir = store.run_dir(run_id)
    config_before = store.load_resolved_config(run_id)
    run_before = store.load_run(run_id)
    expected_max_depth = config_before["planning"]["max_depth"]

    txn_dir = run_dir / ".txn-config"
    txn_dir.mkdir()
    backups_dir = txn_dir / "backups"
    backups_dir.mkdir()
    staged_run = dict(run_before)
    staged_run["revision"] = 1
    atomic_write_json(txn_dir / "run.json", staged_run)
    (backups_dir / "run.json").write_bytes((run_dir / "run.json").read_bytes())
    new_config = copy.deepcopy(config_before)
    new_config["planning"]["max_depth"] = 99
    from core_tools.persistence import dump_yaml

    (txn_dir / "resolved-config.yaml").write_text(
        dump_yaml(new_config) + "\n",
        encoding="utf-8",
    )
    atomic_write_json(run_dir / "run.json", staged_run)
    atomic_write_json(
        txn_dir / "journal.json",
        {
            "txn_id": "config",
            "status": "replacing",
            "files": [
                {
                    "kind": "run",
                    "name": "run.json",
                    "digest": digest_file(txn_dir / "run.json"),
                    "had_destination": True,
                },
                {
                    "kind": "resolved_config",
                    "name": "resolved-config.yaml",
                    "digest": digest_file(txn_dir / "resolved-config.yaml"),
                    "had_destination": True,
                },
            ],
            "events": [],
            "backups": ["run.json"],
            "replaced": ["run.json"],
        },
    )

    ctx = multiprocessing.get_context("fork")
    result_queue: multiprocessing.Queue[dict[str, Any]] = ctx.Queue()
    writer_ready: multiprocessing.Queue[str] = ctx.Queue()
    reader_started: multiprocessing.Queue[str] = ctx.Queue()
    release_writer: multiprocessing.Queue[str] = ctx.Queue()

    writer = ctx.Process(
        target=commit_lock_writer_worker,
        args=(str(tmp_path), run_id, writer_ready, release_writer),
    )
    reader = ctx.Process(
        target=load_config_reader_worker,
        args=(str(tmp_path), run_id, result_queue, reader_started),
    )
    writer.start()
    assert writer_ready.get(timeout=30) == "writer_locked"
    reader.start()
    assert reader_started.get(timeout=30) == "reader_started"
    assert result_queue.empty()

    release_writer.put("release")
    writer.join(timeout=30)
    reader.join(timeout=30)
    assert writer.exitcode == 0
    assert reader.exitcode == 0

    loaded = result_queue.get(timeout=30)
    assert loaded["run_revision"] == 0
    assert loaded["config"]["planning"]["max_depth"] == expected_max_depth
    assert not list(run_dir.glob(".txn-*"))
