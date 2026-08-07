"""Regression tests for Slice 3 round-5 review (TDP-PERSIST-014)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.persistence import TransactionRecoveryError, atomic_write_json
from top_down_planning.persistence import FileRunStore, PersistenceError
from top_down_planning.persistence.commit import CommitSpec
from tests.helpers import events_append_boundary
from tests.unit.test_persistence_correction_fixes import _create_run, _find_txn_dir_local


def _append_event_line_without_newline(events_path: Path, event: dict[str, object]) -> None:
    events_path.write_text(
        events_path.read_text(encoding="utf-8") + json.dumps(event, sort_keys=True),
        encoding="utf-8",
    )


def test_append_event_after_valid_no_newline_final_event_loads_both(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)
    events_path = store.run_dir(run_id) / "events.jsonl"
    extra = {
        "type": "phase_changed",
        "run_id": run_id,
        "txn_id": "plain",
        "event_index": 0,
        "event_count": 1,
        "ts": "2026-01-01T00:00:00Z",
    }
    _append_event_line_without_newline(events_path, extra)

    store.append_event(run_id, {"type": "follow_up", "run_id": run_id})

    loaded = FileRunStore(tmp_path).load_events(run_id)
    assert [event["type"] for event in loaded] == ["run_created", "phase_changed", "follow_up"]
    assert events_path.read_text(encoding="utf-8").endswith("\n")


def test_commit_with_snapshot_and_event_normalizes_no_newline_boundary(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)
    events_path = store.run_dir(run_id) / "events.jsonl"
    _append_event_line_without_newline(
        events_path,
        {
            "type": "phase_changed",
            "run_id": run_id,
            "txn_id": "plain",
            "event_index": 0,
            "event_count": 1,
            "ts": "2026-01-01T00:00:00Z",
        },
    )
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    updated = dict(run)
    updated["revision"] = expected_revision + 1

    store.commit(
        run_id,
        CommitSpec(
            run=updated,
            run_expected_revision=expected_revision,
            events=[{"type": "run_updated", "run_id": run_id}],
        ),
    )

    reopened = FileRunStore(tmp_path)
    assert int(reopened.load_run(run_id)["revision"]) == expected_revision + 1
    types = [event["type"] for event in reopened.load_events(run_id)]
    assert types == ["run_created", "phase_changed", "run_updated"]


def test_recovery_after_full_json_without_newline_produces_two_valid_events(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)
    txn_id = "newline-boundary"
    events_path = store.run_dir(run_id) / "events.jsonl"
    event_a = {
        "type": "event_a",
        "run_id": run_id,
        "txn_id": txn_id,
        "event_index": 0,
        "event_count": 2,
        "ts": "2026-01-01T00:00:00Z",
    }
    event_b = {
        "type": "event_b",
        "run_id": run_id,
        "txn_id": txn_id,
        "event_index": 1,
        "event_count": 2,
        "ts": "2026-01-01T00:00:01Z",
    }
    boundary = events_append_boundary(events_path)
    events_path.write_text(
        events_path.read_text(encoding="utf-8") + json.dumps(event_a, sort_keys=True),
        encoding="utf-8",
    )

    txn_dir = store.run_dir(run_id) / f".txn-{txn_id}"
    txn_dir.mkdir()
    atomic_write_json(
        txn_dir / "journal.json",
        {
            "txn_id": txn_id,
            "status": "appending_events",
            "files": [],
            "events": [event_a, event_b],
            "backups": [],
            "replaced": [],
            **boundary,
        },
    )

    loaded = FileRunStore(tmp_path).load_events(run_id)
    txn_events = [event for event in loaded if event.get("txn_id") == txn_id]
    assert [event["type"] for event in txn_events] == ["event_a", "event_b"]
    assert events_path.read_text(encoding="utf-8").endswith("\n")
    assert not _find_txn_dir_local(FileRunStore(tmp_path), run_id)


def test_event_bearing_commit_fails_before_snapshot_when_trailing_content_malformed(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)
    run_before = store.load_run(run_id)
    events_path = store.run_dir(run_id) / "events.jsonl"
    events_path.write_text(
        events_path.read_text(encoding="utf-8") + '{"type": "broken"',
        encoding="utf-8",
    )
    expected_revision = int(run_before["revision"])
    updated = dict(run_before)
    updated["revision"] = expected_revision + 1

    with pytest.raises(PersistenceError, match="malformed trailing content"):
        store.commit(
            run_id,
            CommitSpec(
                run=updated,
                run_expected_revision=expected_revision,
                events=[{"type": "should_not_append", "run_id": run_id}],
            ),
        )

    assert int(store.load_run(run_id)["revision"]) == expected_revision
    assert not list(store.run_dir(run_id).glob(".txn-*"))


def test_recovery_fails_when_bytes_before_append_boundary_are_corrupted(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)
    txn_id = "boundary-corrupt"
    events_path = store.run_dir(run_id) / "events.jsonl"
    boundary = events_append_boundary(events_path)
    txn_dir = store.run_dir(run_id) / f".txn-{txn_id}"
    txn_dir.mkdir()
    atomic_write_json(
        txn_dir / "journal.json",
        {
            "txn_id": txn_id,
            "status": "appending_events",
            "files": [],
            "events": [
                {
                    "type": "late_event",
                    "run_id": run_id,
                    "txn_id": txn_id,
                    "event_index": 0,
                    "event_count": 1,
                    "ts": "2026-01-01T00:00:00Z",
                }
            ],
            "backups": [],
            "replaced": [],
            **boundary,
        },
    )
    raw = bytearray(events_path.read_bytes())
    raw[0] = ord("X") if raw[0] != ord("X") else ord("Y")
    events_path.write_bytes(bytes(raw))

    with pytest.raises(TransactionRecoveryError, match="append boundary"):
        FileRunStore(tmp_path).load_events(run_id)

    assert txn_dir.is_dir()
