"""Regression tests for Slice 3 round-3 review (TDP-PERSIST-003/010/012/013)."""

from __future__ import annotations

import json
import multiprocessing
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from core_tools.persistence import TransactionRecoveryError, atomic_write_json, digest_bytes, digest_file
from top_down_planning.persistence import FileRunStore, PersistenceError
from tests.helpers import events_append_boundary, recovery_journal_events
from tests.support.persistence import _find_txn_dir_local
from tests.unit.test_persistence_correction_fixes import _create_run


def _file_entry(
    *,
    kind: str,
    name: str,
    digest: str,
    had_destination: bool,
) -> dict[str, object]:
    return {
        "kind": kind,
        "name": name,
        "digest": digest,
        "had_destination": had_destination,
    }


def _write_journal_txn(
    store: FileRunStore,
    run_id: str,
    txn_id: str,
    journal: dict[str, Any],
    *,
    setup_backup: bool = False,
    corrupted_run: dict[str, Any] | None = None,
) -> Path:
    txn_dir = store.run_dir(run_id) / f".txn-{txn_id}"
    txn_dir.mkdir()
    if setup_backup:
        backups_dir = txn_dir / "backups"
        backups_dir.mkdir()
        run_path = store.run_dir(run_id) / "run.json"
        (backups_dir / "run.json").write_bytes(run_path.read_bytes())
    if corrupted_run is not None:
        atomic_write_json(store.run_dir(run_id) / "run.json", corrupted_run)
    atomic_write_json(txn_dir / "journal.json", journal)
    return txn_dir


def test_journal_replaced_without_files_entry_fails_closed_and_retains_evidence(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)
    run_before = store.load_run(run_id)
    corrupted = dict(run_before)
    corrupted["status"] = "corrupted-marker"
    txn_dir = _write_journal_txn(
        store,
        run_id,
        "orphan-replaced",
        {
            "txn_id": "orphan-replaced",
            "status": "replacing",
            "files": [],
            "events": [],
            "backups": ["run.json"],
            "replaced": ["run.json"],
        },
        setup_backup=True,
        corrupted_run=corrupted,
    )

    with pytest.raises(TransactionRecoveryError, match="unknown file"):
        FileRunStore(tmp_path).load_run(run_id)

    assert txn_dir.is_dir()
    assert (txn_dir / "backups" / "run.json").is_file()
    on_disk = json.loads((store.run_dir(run_id) / "run.json").read_text(encoding="utf-8"))
    assert on_disk["status"] == "corrupted-marker"


def test_journal_missing_physical_backup_fails_closed(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)
    run_before = store.load_run(run_id)
    staged_run = dict(run_before)
    staged_run["revision"] = int(run_before["revision"]) + 1
    txn_dir = store.run_dir(run_id) / ".txn-missing-backup"
    txn_dir.mkdir()
    atomic_write_json(txn_dir / "run.json", staged_run)
    atomic_write_json(store.run_dir(run_id) / "run.json", staged_run)
    atomic_write_json(
        txn_dir / "journal.json",
        {
            "txn_id": "missing-backup",
            "status": "replacing",
            "files": [
                {
                    "kind": "run",
                    "name": "run.json",
                    "digest": digest_file(txn_dir / "run.json"),
                    "had_destination": True,
                }
            ],
            "events": [],
            "backups": ["run.json"],
            "replaced": ["run.json"],
        },
    )

    with pytest.raises(TransactionRecoveryError, match="backup missing"):
        FileRunStore(tmp_path).load_run(run_id)

    assert txn_dir.is_dir()
    assert json.loads((store.run_dir(run_id) / "run.json").read_text(encoding="utf-8")) == staged_run


def test_journal_duplicate_file_names_fail_closed(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)
    txn_dir = _write_journal_txn(
        store,
        run_id,
        "dup-files",
        {
            "txn_id": "dup-files",
            "status": "prepared",
            "files": [
                _file_entry(kind="run", name="run.json", digest="aaa", had_destination=False),
                _file_entry(kind="plan", name="run.json", digest="bbb", had_destination=False),
            ],
            "events": [],
            "backups": [],
            "replaced": [],
        },
    )

    with pytest.raises(TransactionRecoveryError, match="duplicate file name"):
        FileRunStore(tmp_path).load_run(run_id)

    assert txn_dir.is_dir()


def test_journal_kind_name_mismatch_fails_closed(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)
    txn_dir = _write_journal_txn(
        store,
        run_id,
        "kind-mismatch",
        {
            "txn_id": "kind-mismatch",
            "status": "prepared",
            "files": [_file_entry(kind="run", name="plan.json", digest="abc", had_destination=False)],
            "events": [],
            "backups": [],
            "replaced": [],
        },
    )

    with pytest.raises(TransactionRecoveryError, match="kind/name mismatch"):
        FileRunStore(tmp_path).load_run(run_id)

    assert txn_dir.is_dir()


def test_load_events_rejects_complete_out_of_order_transaction(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)
    events_path = store.run_dir(run_id) / "events.jsonl"
    base = events_path.read_text(encoding="utf-8")
    txn_id = "reordered"
    second = json.dumps(
        {
            "type": "event_b",
            "run_id": run_id,
            "txn_id": txn_id,
            "event_index": 1,
            "event_count": 2,
            "ts": "2026-01-01T00:00:00Z",
        },
        sort_keys=True,
    )
    first = json.dumps(
        {
            "type": "event_a",
            "run_id": run_id,
            "txn_id": txn_id,
            "event_index": 0,
            "event_count": 2,
            "ts": "2026-01-01T00:00:01Z",
        },
        sort_keys=True,
    )
    events_path.write_text(base + second + "\n" + first + "\n", encoding="utf-8")
    raw_before = events_path.read_bytes()

    with pytest.raises(PersistenceError, match="out of physical order"):
        FileRunStore(tmp_path).load_events(run_id)

    assert events_path.read_bytes() == raw_before


def test_recovery_rejects_unrelated_malformed_trailing_fragment(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)
    events_path = store.run_dir(run_id) / "events.jsonl"
    boundary = events_append_boundary(events_path)
    events_path.write_text(
        events_path.read_text(encoding="utf-8") + '{"type": "orphan", "txn_id": "other-txn"',
        encoding="utf-8",
    )
    raw_before = events_path.read_bytes()

    txn_dir = store.run_dir(run_id) / ".txn-unrelated-fragment"
    txn_dir.mkdir()
    atomic_write_json(
        txn_dir / "journal.json",
        {
            "txn_id": "unrelated-fragment",
            "status": "appending_events",
            "files": [],
            "events": recovery_journal_events(
                "unrelated-fragment",
                [
                    {
                        "type": "late_event",
                        "run_id": run_id,
                    }
                ],
            ),
            "backups": [],
            "replaced": [],
            **boundary,
        },
    )

    with pytest.raises(TransactionRecoveryError, match="suffix mismatch"):
        FileRunStore(tmp_path).load_events(run_id)

    assert txn_dir.is_dir()
    assert events_path.read_bytes() == raw_before


def test_event_fragment_repair_publish_failure_leaves_original_bytes(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)
    events_path = store.run_dir(run_id) / "events.jsonl"
    txn_id = "repair-fail"
    event_b = {
        "type": "event_b",
        "run_id": run_id,
        "txn_id": txn_id,
        "event_index": 1,
        "event_count": 2,
        "ts": "2026-01-01T00:00:01Z",
    }
    event_b_line = json.dumps(event_b, sort_keys=True)
    first_event = json.dumps(
        {
            "type": "event_a",
            "run_id": run_id,
            "txn_id": txn_id,
            "event_index": 0,
            "event_count": 2,
            "ts": "2026-01-01T00:00:00Z",
        },
        sort_keys=True,
    )
    boundary = events_append_boundary(events_path)
    events_path.write_text(
        events_path.read_text(encoding="utf-8") + first_event + "\n" + event_b_line[:40],
        encoding="utf-8",
    )
    raw_before = events_path.read_bytes()

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
                    "type": "event_a",
                    "run_id": run_id,
                    "txn_id": txn_id,
                    "event_index": 0,
                    "event_count": 2,
                    "ts": "2026-01-01T00:00:00Z",
                },
                event_b,
            ],
            "backups": [],
            "replaced": [],
            **events_append_boundary(events_path),
        },
    )

    original_replace = Path.replace

    def crash_on_events_repair_replace(self: Path, target: Path) -> Path:
        if target.name == "events.jsonl" and self.name.startswith(".events.jsonl.repair-"):
            raise OSError("simulated crash during event repair publish")
        return original_replace(self, target)

    with patch.object(Path, "replace", crash_on_events_repair_replace):
        with pytest.raises(OSError, match="simulated crash"):
            FileRunStore(tmp_path).load_events(run_id)

    assert events_path.read_bytes() == raw_before
    assert txn_dir.is_dir()
