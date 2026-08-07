"""Regression tests for Slice 3 round-7 review (TDP-PERSIST-016..022, TDP-CAP-001)."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.persistence import (
    PersistenceError,
    RunNotFoundError,
    TransactionRecoveryError,
    atomic_write_json,
    parse_revision_value,
)
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.capabilities import write_capability_token_file
from top_down_planning.persistence.commit import CommitSpec
from top_down_planning.persistence.review_commit import review_record_revision
from tests.helpers import create_run_kwargs, events_append_boundary, minimal_resolved_config
from tests.unit.test_commit_crash_recovery import _create_run, _find_txn_dir, _multi_file_commit
from tests.unit.test_persistence_correction_fixes import _find_txn_dir_local


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


def _crash_on_first_staged_run_write() -> object:
    original = atomic_write_json
    calls = 0

    def patched(path: Path, payload: dict[str, object]) -> None:
        nonlocal calls
        if path.name == "run.json" and any(part.startswith(".stage-") for part in path.parts):
            calls += 1
            if calls == 1:
                raise OSError("simulated crash during first staged file write")
        original(path, payload)

    return patched


def _crash_before_prepared_journal() -> object:
    original = atomic_write_json

    def patched(path: Path, payload: dict[str, object]) -> None:
        if path.name == "journal.json" and payload.get("status") == "prepared":
            raise OSError("simulated crash before prepared journal")
        original(path, payload)

    return patched


def _crash_before_txn_publication() -> object:
    original_rename = Path.rename
    calls = 0

    def patched(self: Path, target: Path) -> Path:
        nonlocal calls
        if self.name.startswith(".stage-") and target.name.startswith(".txn-"):
            calls += 1
            if calls == 1:
                raise OSError("simulated crash before transaction publication")
        return original_rename(self, target)

    return patched


def test_failure_during_first_staged_write_leaves_canonical_run_readable(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"
    _create_run(store, run_id)
    run_before = store.load_run(run_id)

    with patch(
        "top_down_planning.persistence.file_store.atomic_write_json",
        _crash_on_first_staged_run_write(),
    ):
        with pytest.raises(OSError, match="simulated crash"):
            _multi_file_commit(store, run_id)

    run_dir = store.run_dir(run_id)
    assert list(run_dir.glob(".txn-*")) == []
    assert list(run_dir.glob(".stage-*")) == []
    reopened = FileRunStore(tmp_path)
    assert reopened.load_run(run_id)["revision"] == run_before["revision"]


def test_failure_before_prepared_journal_leaves_canonical_run_readable(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"
    _create_run(store, run_id)
    run_before = store.load_run(run_id)

    with patch(
        "top_down_planning.persistence.file_store.atomic_write_json",
        _crash_before_prepared_journal(),
    ):
        with pytest.raises(OSError, match="simulated crash"):
            _multi_file_commit(store, run_id)

    run_dir = store.run_dir(run_id)
    assert list(run_dir.glob(".txn-*")) == []
    assert list(run_dir.glob(".stage-*")) == []
    reopened = FileRunStore(tmp_path)
    assert reopened.load_run(run_id)["revision"] == run_before["revision"]


def test_leftover_stage_dir_is_discarded_on_reopen(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"
    _create_run(store, run_id)
    stage_dir = store.run_dir(run_id) / ".stage-orphan"
    stage_dir.mkdir()
    (stage_dir / "journal.json").write_text("{}", encoding="utf-8")

    reopened = FileRunStore(tmp_path)
    assert reopened.load_run(run_id)["id"] == run_id
    assert not stage_dir.exists()


def test_failure_before_txn_publication_leaves_canonical_run_readable(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"
    _create_run(store, run_id)
    run_before = store.load_run(run_id)

    with patch.object(Path, "rename", _crash_before_txn_publication()):
        with pytest.raises(OSError, match="simulated crash"):
            _multi_file_commit(store, run_id)

    run_dir = store.run_dir(run_id)
    assert list(run_dir.glob(".txn-*")) == []
    reopened = FileRunStore(tmp_path)
    assert reopened.load_run(run_id)["revision"] == run_before["revision"]
    assert list(run_dir.glob(".stage-*")) == []


def test_interrupt_retired_cleanup_leaves_run_usable(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"
    _create_run(store, run_id)
    _multi_file_commit(store, run_id)

    run_dir = store.run_dir(run_id)
    retired_dir = run_dir / ".retired-txn-partial-abc123"
    retired_dir.mkdir()
    (retired_dir / "journal.json").write_text("{}", encoding="utf-8")

    reopened = FileRunStore(tmp_path)
    assert reopened.load_run(run_id)["revision"] == 1
    assert not retired_dir.exists()


def test_recovery_rejects_same_index_different_event_type(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"
    _create_run(store, run_id)
    txn_id = "wrong-type"
    events_path = store.run_dir(run_id) / "events.jsonl"
    boundary = events_append_boundary(events_path)
    expected = {
        "type": "expected_event",
        "run_id": run_id,
        "txn_id": txn_id,
        "event_index": 0,
        "event_count": 1,
        "ts": "2026-01-01T00:00:00Z",
    }
    wrong = dict(expected)
    wrong["type"] = "wrong_event"
    events_path.write_bytes(
        events_path.read_bytes() + (json.dumps(wrong, sort_keys=True) + "\n").encode("utf-8")
    )
    txn_dir = store.run_dir(run_id) / f".txn-{txn_id}"
    txn_dir.mkdir()
    atomic_write_json(
        txn_dir / "journal.json",
        {
            "txn_id": txn_id,
            "status": "appending_events",
            "files": [],
            "events": [expected],
            "backups": [],
            "replaced": [],
            **boundary,
        },
    )

    with pytest.raises(TransactionRecoveryError, match="suffix mismatch"):
        FileRunStore(tmp_path).load_events(run_id)


def test_recovery_rejects_unrelated_event_after_boundary(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"
    _create_run(store, run_id)
    txn_id = "unrelated-after"
    events_path = store.run_dir(run_id) / "events.jsonl"
    boundary = events_append_boundary(events_path)
    unrelated = {
        "type": "unrelated",
        "run_id": run_id,
        "txn_id": "other",
        "event_index": 0,
        "event_count": 1,
        "ts": "2026-01-01T00:00:00Z",
    }
    events_path.write_bytes(
        events_path.read_bytes() + (json.dumps(unrelated, sort_keys=True) + "\n").encode("utf-8")
    )
    expected = {
        "type": "expected_event",
        "run_id": run_id,
        "txn_id": txn_id,
        "event_index": 0,
        "event_count": 1,
        "ts": "2026-01-01T00:00:01Z",
    }
    txn_dir = store.run_dir(run_id) / f".txn-{txn_id}"
    txn_dir.mkdir()
    atomic_write_json(
        txn_dir / "journal.json",
        {
            "txn_id": txn_id,
            "status": "committed",
            "files": [],
            "events": [expected],
            "backups": [],
            "replaced": [],
            **boundary,
        },
    )

    with pytest.raises(TransactionRecoveryError, match="suffix mismatch"):
        FileRunStore(tmp_path).load_events(run_id)


@pytest.mark.parametrize(
    ("revision", "message"),
    [
        (True, "non-negative integer"),
        ("1", "non-negative integer"),
        (1.9, "non-negative integer"),
        (-1, "non-negative integer"),
    ],
)
def test_parse_revision_value_rejects_malformed(revision: object, message: str) -> None:
    with pytest.raises(PersistenceError, match=message):
        parse_revision_value(revision, "run")


def test_load_run_rejects_missing_sessions(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"
    _create_run(store, run_id)
    run_path = store.run_dir(run_id) / "run.json"
    payload = json.loads(run_path.read_text(encoding="utf-8"))
    payload.pop("sessions")
    run_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PersistenceError, match="sessions must be an object"):
        FileRunStore(tmp_path).load_run(run_id)


def test_load_run_rejects_missing_session_instance_id(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"
    _create_run(store, run_id)
    run_path = store.run_dir(run_id) / "run.json"
    payload = json.loads(run_path.read_text(encoding="utf-8"))
    payload["sessions"]["primary_planner"].pop("session_instance_id")
    run_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PersistenceError, match="session_instance_id"):
        FileRunStore(tmp_path).load_run(run_id)


def test_load_run_rejects_run_id_mismatch(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"
    _create_run(store, run_id)
    run_path = store.run_dir(run_id) / "run.json"
    payload = json.loads(run_path.read_text(encoding="utf-8"))
    payload["id"] = "run-20260101T999999-999999"
    run_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PersistenceError, match="run.id does not match"):
        FileRunStore(tmp_path).load_run(run_id)


def test_create_run_rejects_protected_run_extras_collision(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"
    with pytest.raises(PersistenceError, match="run_extras cannot overwrite protected"):
        store.create_run(
            run_id,
            plan=_sample_plan(run_id),
            **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
            run_extras={"revision": 99},
        )


def test_non_object_run_json_is_rejected(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"
    _create_run(store, run_id)
    (store.run_dir(run_id) / "run.json").write_text("[]", encoding="utf-8")

    with pytest.raises(PersistenceError, match="must contain a JSON object"):
        FileRunStore(tmp_path).load_run(run_id)


def test_side_writers_reject_nonexistent_run(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"

    with pytest.raises(RunNotFoundError):
        store.create_capability(
            run_id,
            role="planner",
            phase="planning",
            allowed_ops=frozenset({"plan_apply"}),
            session_id="stub-session",
        )
    with pytest.raises(RunNotFoundError):
        store.write_artifact_bytes(run_id, "snap-1", "artifact.txt", b"data")
    with pytest.raises(RunNotFoundError):
        write_capability_token_file(store, run_id, "cap-token.secret")

    assert not store.run_dir(run_id).exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX file mode checks")
def test_capability_token_file_is_secure_on_publication(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"
    _create_run(store, run_id)
    token_path = write_capability_token_file(store, run_id, "cap-id.secretvalue")
    mode = stat.S_IMODE(token_path.stat().st_mode)
    assert mode == 0o600


def test_multiple_active_transaction_dirs_fail_closed(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"
    _create_run(store, run_id)
    run_dir = store.run_dir(run_id)
    (run_dir / ".txn-one").mkdir()
    (run_dir / ".txn-two").mkdir()

    with pytest.raises(TransactionRecoveryError, match="multiple active transaction"):
        store.load_run(run_id)


def test_capability_reads_require_existing_run(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"

    with pytest.raises(RunNotFoundError):
        store.list_capabilities(run_id)
    with pytest.raises(RunNotFoundError):
        store.load_capability(run_id, "cap-missing")


def test_load_events_rejects_bool_event_index(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"
    _create_run(store, run_id)
    events_path = store.run_dir(run_id) / "events.jsonl"
    bad = {
        "type": "bad",
        "run_id": run_id,
        "txn_id": "bad-txn",
        "event_index": True,
        "event_count": 1,
        "ts": "2026-01-01T00:00:00Z",
    }
    events_path.write_text(
        events_path.read_text(encoding="utf-8") + json.dumps(bad, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(PersistenceError, match="event_index must be an integer"):
        store.load_events(run_id)


def test_save_run_without_sessions_preserves_persisted_sessions(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"
    _create_run(store, run_id)
    before = store.load_run(run_id)
    planner_id = before["sessions"]["primary_planner"]["session_instance_id"]

    run_update = dict(before)
    run_update.pop("sessions")
    run_update["revision"] = int(before["revision"]) + 1
    store.save_run(run_id, run_update, int(before["revision"]))

    after = store.load_run(run_id)
    assert after["sessions"]["primary_planner"]["session_instance_id"] == planner_id
    assert int(after["revision"]) == int(before["revision"]) + 1


def test_load_review_rejects_bool_revision(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"
    _create_run(store, run_id)
    reviews_dir = store.reviews_dir(run_id)
    reviews_dir.mkdir(parents=True, exist_ok=True)
    review_path = reviews_dir / "review-loop-1.json"
    atomic_write_json(
        review_path,
        {
            "id": "review-loop-1",
            "revision": True,
            "type": "focused_plan",
            "status": "requested",
        },
    )

    with pytest.raises(PersistenceError, match="non-negative integer"):
        store.load_review(run_id, "review-loop-1")


def test_review_record_revision_rejects_bool() -> None:
    with pytest.raises(PersistenceError, match="non-negative integer"):
        review_record_revision({"revision": True})


def test_save_run_rejects_bool_expected_revision(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"
    _create_run(store, run_id)
    run = store.load_run(run_id)
    run["revision"] = 1

    with pytest.raises(PersistenceError, match="non-negative integer"):
        store.save_run(run_id, run, True)  # type: ignore[arg-type]


def test_commit_rejects_bool_plan_expected_revision(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"
    _create_run(store, run_id)
    plan = store.load_plan(run_id)
    plan["revision"] = 1

    with pytest.raises(PersistenceError, match="non-negative integer"):
        store.commit(
            run_id,
            CommitSpec(plan=plan, plan_expected_revision=True),  # type: ignore[arg-type]
        )


def test_create_capability_rejects_bool_generation(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"
    _create_run(store, run_id)

    with pytest.raises(ValueError, match="generation must be a positive integer"):
        store.create_capability(
            run_id,
            role="planner",
            phase="planning",
            allowed_ops=frozenset({"plan_apply"}),
            session_id="stub-session",
            generation=True,  # type: ignore[arg-type]
        )
