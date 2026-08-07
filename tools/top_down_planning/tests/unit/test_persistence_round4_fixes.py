"""Regression tests for Slice 3 round-4 review (TDP-PERSIST-003/013)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core_tools.persistence import TransactionRecoveryError, atomic_write_json, digest_file
from top_down_planning.persistence import FileRunStore, PersistenceError
from tests.helpers import events_append_boundary
from tests.unit.test_persistence_correction_fixes import _create_run, _find_txn_dir_local


def _file_entry(
    *,
    kind: str,
    name: str,
    digest: str,
    had_destination: bool,
    review_id: str | None = None,
) -> dict[str, object]:
    entry: dict[str, object] = {
        "kind": kind,
        "name": name,
        "digest": digest,
        "had_destination": had_destination,
    }
    if review_id is not None:
        entry["review_id"] = review_id
    return entry


def _write_appending_journal(
    store: FileRunStore,
    run_id: str,
    txn_id: str,
    *,
    files: list[dict[str, object]],
    replaced: list[str],
    backups: list[str],
    events: list[dict[str, object]],
    boundary: dict[str, object] | None = None,
) -> Path:
    txn_dir = store.run_dir(run_id) / f".txn-{txn_id}"
    txn_dir.mkdir()
    events_path = store.run_dir(run_id) / "events.jsonl"
    resolved_boundary = boundary if boundary is not None else (
        events_append_boundary(events_path) if events else {}
    )
    atomic_write_json(
        txn_dir / "journal.json",
        {
            "txn_id": txn_id,
            "status": "appending_events",
            "files": files,
            "events": events,
            "backups": backups,
            "replaced": replaced,
            **resolved_boundary,
        },
    )
    return txn_dir


def test_appending_events_with_partial_replaced_fails_closed(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)
    run_before = store.load_run(run_id)
    plan = store.load_plan(run_id)
    events_before = store.load_events(run_id)
    events_before_bytes = (store.run_dir(run_id) / "events.jsonl").read_bytes()
    staged_run = dict(run_before)
    staged_run["revision"] = int(run_before["revision"]) + 1
    staged_plan = dict(plan)
    staged_plan["revision"] = int(plan["revision"]) + 1
    txn_dir = store.run_dir(run_id) / ".txn-partial-replaced"
    txn_dir.mkdir()
    atomic_write_json(txn_dir / "run.json", staged_run)
    atomic_write_json(txn_dir / "plan.json", staged_plan)
    backups_dir = txn_dir / "backups"
    backups_dir.mkdir()
    (backups_dir / "run.json").write_bytes((store.run_dir(run_id) / "run.json").read_bytes())
    atomic_write_json(store.run_dir(run_id) / "run.json", staged_run)
    events_path = store.run_dir(run_id) / "events.jsonl"
    atomic_write_json(
        txn_dir / "journal.json",
        {
            "txn_id": "partial-replaced",
            "status": "appending_events",
            "files": [
                _file_entry(
                    kind="run",
                    name="run.json",
                    digest=digest_file(txn_dir / "run.json"),
                    had_destination=True,
                ),
                _file_entry(
                    kind="plan",
                    name="plan.json",
                    digest=digest_file(txn_dir / "plan.json"),
                    had_destination=False,
                ),
            ],
            "events": [{"type": "transition", "run_id": run_id}],
            "backups": ["run.json"],
            "replaced": ["run.json"],
            **events_append_boundary(events_path),
        },
    )

    with pytest.raises(TransactionRecoveryError, match="replaced must include every staged file"):
        FileRunStore(tmp_path).load_run(run_id)

    assert txn_dir.is_dir()
    assert (store.run_dir(run_id) / "events.jsonl").read_bytes() == events_before_bytes


def test_committed_with_digest_mismatch_fails_closed(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)
    run_before = store.load_run(run_id)
    events_before = store.load_events(run_id)
    events_before_bytes = (store.run_dir(run_id) / "events.jsonl").read_bytes()
    staged_run = dict(run_before)
    staged_run["revision"] = int(run_before["revision"]) + 1
    txn_dir = store.run_dir(run_id) / ".txn-digest-mismatch"
    txn_dir.mkdir()
    atomic_write_json(txn_dir / "run.json", staged_run)
    backups_dir = txn_dir / "backups"
    backups_dir.mkdir()
    (backups_dir / "run.json").write_bytes((store.run_dir(run_id) / "run.json").read_bytes())
    atomic_write_json(store.run_dir(run_id) / "run.json", run_before)
    events_path = store.run_dir(run_id) / "events.jsonl"
    atomic_write_json(
        txn_dir / "journal.json",
        {
            "txn_id": "digest-mismatch",
            "status": "committed",
            "files": [
                _file_entry(
                    kind="run",
                    name="run.json",
                    digest=digest_file(txn_dir / "run.json"),
                    had_destination=True,
                ),
            ],
            "events": [{"type": "transition", "run_id": run_id}],
            "backups": ["run.json"],
            "replaced": ["run.json"],
            **events_append_boundary(events_path),
        },
    )

    with pytest.raises(TransactionRecoveryError, match="digest mismatch"):
        FileRunStore(tmp_path).load_run(run_id)

    assert txn_dir.is_dir()
    assert json.loads((store.run_dir(run_id) / "run.json").read_text(encoding="utf-8")) == run_before
    assert (store.run_dir(run_id) / "events.jsonl").read_bytes() == events_before_bytes


def test_journal_had_destination_requires_backup_listing(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)
    txn_dir = _write_appending_journal(
        store,
        run_id,
        "missing-backup-listing",
        files=[
            _file_entry(
                kind="run",
                name="run.json",
                digest="abc",
                had_destination=True,
            ),
        ],
        replaced=["run.json"],
        backups=[],
        events=[],
    )

    with pytest.raises(TransactionRecoveryError, match="had_destination requires backup"):
        FileRunStore(tmp_path).load_run(run_id)

    assert txn_dir.is_dir()


def _normalized_journal_event(
    *,
    run_id: str,
    txn_id: str,
    event_type: str,
    event_index: int,
    event_count: int,
    ts: str = "2026-01-01T00:00:00Z",
) -> dict[str, object]:
    return {
        "type": event_type,
        "run_id": run_id,
        "txn_id": txn_id,
        "event_index": event_index,
        "event_count": event_count,
        "ts": ts,
    }


def _serialized_event_line(event: dict[str, object]) -> str:
    return json.dumps(event, sort_keys=True)


@pytest.mark.parametrize(
    "truncate_at",
    [
        1,
        lambda line: line.index('"txn_id"') - 1,
        lambda line: line.index('"txn_id"') + len('"txn_id": "') + 2,
        lambda line: len(line) - 1,
    ],
    ids=["first-byte", "before-txn-id", "mid-txn-id", "before-line-end"],
)
def test_recovery_repairs_arbitrary_partial_event_prefix(
    tmp_path: Path,
    truncate_at: int | object,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)
    txn_id = "partial-prefix"
    event = _normalized_journal_event(
        run_id=run_id,
        txn_id=txn_id,
        event_type="event_b",
        event_index=1,
        event_count=2,
    )
    line = _serialized_event_line(event)
    cut = truncate_at(line) if callable(truncate_at) else truncate_at
    fragment = line[:cut]

    events_path = store.run_dir(run_id) / "events.jsonl"
    first_event = _normalized_journal_event(
        run_id=run_id,
        txn_id=txn_id,
        event_type="event_a",
        event_index=0,
        event_count=2,
        ts="2026-01-01T00:00:00Z",
    )
    boundary = events_append_boundary(events_path)
    events_path.write_text(
        events_path.read_text(encoding="utf-8")
        + _serialized_event_line(first_event)
        + "\n"
        + fragment,
        encoding="utf-8",
    )

    txn_dir = _write_appending_journal(
        store,
        run_id,
        txn_id,
        files=[],
        replaced=[],
        backups=[],
        events=[
            first_event,
            event,
        ],
        boundary=boundary,
    )

    recovered = FileRunStore(tmp_path)
    loaded = recovered.load_events(run_id)
    txn_events = [item for item in loaded if item.get("txn_id") == txn_id]
    assert [item["type"] for item in txn_events] == ["event_a", "event_b"]
    assert txn_events[1]["ts"] == "2026-01-01T00:00:00Z"
    assert not _find_txn_dir_local(recovered, run_id)
    assert txn_dir  # referenced to silence lint if recovery removed it


def test_recovery_rejects_coincidental_txn_id_substring_in_unrelated_fragment(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    _create_run(store)
    txn_id = "coincidental"
    events_path = store.run_dir(run_id) / "events.jsonl"
    boundary = events_append_boundary(events_path)
    events_path.write_text(
        events_path.read_text(encoding="utf-8")
        + json.dumps({"note": f"mentions {txn_id} but unrelated"}, sort_keys=True)[:-1],
        encoding="utf-8",
    )
    raw_before = events_path.read_bytes()

    txn_dir = _write_appending_journal(
        store,
        run_id,
        txn_id,
        files=[],
        replaced=[],
        backups=[],
        events=[
            _normalized_journal_event(
                run_id=run_id,
                txn_id=txn_id,
                event_type="late_event",
                event_index=0,
                event_count=1,
            ),
        ],
        boundary=boundary,
    )

    with pytest.raises(TransactionRecoveryError, match="suffix mismatch"):
        FileRunStore(tmp_path).load_events(run_id)

    assert txn_dir.is_dir()
    assert events_path.read_bytes() == raw_before
