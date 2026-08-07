"""Regression tests for Slice 3 round-6 review (TDP-PERSIST-015)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from top_down_planning.persistence import FileRunStore
from tests.unit.test_commit_crash_recovery import (
    _crash_on_appending_events_journal_write,
    _create_run,
    _find_txn_dir,
    _multi_file_commit,
)


def test_crash_after_final_replaced_before_appending_events_recovers(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000601-000601"
    _create_run(store)
    events_before = store.load_events(run_id)

    with patch(
        "top_down_planning.persistence.file_store.atomic_write_json",
        _crash_on_appending_events_journal_write(),
    ):
        with pytest.raises(OSError, match="simulated crash"):
            _multi_file_commit(store, run_id)

    txn_dir = _find_txn_dir(store, run_id)
    assert txn_dir is not None
    journal = json.loads((txn_dir / "journal.json").read_text(encoding="utf-8"))
    assert journal["status"] == "replacing"
    assert set(journal["replaced"]) == {"run.json", "plan.json"}
    assert "events_base_size" in journal
    assert "events_base_digest" in journal
    assert journal["events_base_size"] > 0

    recovered = FileRunStore(tmp_path)
    run_after = recovered.load_run(run_id)
    plan_after = recovered.load_plan(run_id)
    assert run_after["revision"] == 1
    assert plan_after["revision"] == 1
    events_after = recovered.load_events(run_id)
    assert len(events_after) == len(events_before) + 1
    assert events_after[-1]["type"] == "test_commit"
    assert events_after[-1]["txn_id"] == journal["txn_id"]
    assert not _find_txn_dir(recovered, run_id)
