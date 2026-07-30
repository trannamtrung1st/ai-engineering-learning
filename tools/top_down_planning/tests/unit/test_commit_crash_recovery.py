"""Crash recovery tests for journaled RunStore.commit()."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.commit import CommitSpec
from tests.helpers import create_run_kwargs, minimal_resolved_config


def _create_run(store: FileRunStore, run_id: str = "run-crash") -> None:
    workspace = store.root
    config = minimal_resolved_config()
    plan = Plan(
        id="plan-run-crash",
        revision=0,
        output_goal="Goal.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="Root",
            )
        },
    )
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(workspace, resolved_config=config),
    )


def _multi_file_commit(store: FileRunStore, run_id: str) -> None:
    run = store.load_run(run_id)
    plan = store.load_plan(run_id)
    run_expected = int(run["revision"])
    plan_expected = int(plan["revision"])
    run = dict(run)
    run["revision"] = run_expected + 1
    plan = dict(plan)
    plan["revision"] = plan_expected + 1
    store.commit(
        run_id,
        CommitSpec(
            run=run,
            run_expected_revision=run_expected,
            plan=plan,
            plan_expected_revision=plan_expected,
            events=[{"type": "test_commit", "run_id": run_id}],
        ),
    )


def _find_txn_dir(store: FileRunStore, run_id: str) -> Path | None:
    run_dir = store.run_dir(run_id)
    txn_dirs = sorted(run_dir.glob(".txn-*"))
    return txn_dirs[0] if txn_dirs else None


def _crash_after_dest_replace_count(replace_count: int) -> Any:
    original_replace = Path.replace
    calls = 0

    def patched_replace(self: Path, target: Path) -> Path:
        nonlocal calls
        result = original_replace(self, target)
        self_parts = self.parts
        target_parts = target.parts
        if any(part.startswith(".txn-") for part in self_parts) and not any(
            part.startswith(".txn-") for part in target_parts
        ):
            calls += 1
            if calls == replace_count:
                raise OSError("simulated crash")
        return result

    return patched_replace


def test_crash_during_replace_restores_prior_state(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    run_before = store.load_run("run-crash")
    plan_before = store.load_plan("run-crash")

    with patch.object(Path, "replace", _crash_after_dest_replace_count(1)):
        with pytest.raises(OSError, match="simulated crash"):
            _multi_file_commit(store, "run-crash")

    txn_dir = _find_txn_dir(store, "run-crash")
    assert txn_dir is not None
    journal = json.loads((txn_dir / "journal.json").read_text(encoding="utf-8"))
    assert journal["status"] == "replacing"
    assert journal["replaced"]

    recovered = FileRunStore(tmp_path)
    run_after = recovered.load_run("run-crash")
    plan_after = recovered.load_plan("run-crash")
    assert run_after["revision"] == run_before["revision"]
    assert plan_after["revision"] == plan_before["revision"]
    assert not _find_txn_dir(recovered, "run-crash")


def test_crash_after_all_replaces_finishes_events_on_recovery(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    events_before = store.load_events("run-crash")

    with patch.object(Path, "replace", _crash_after_dest_replace_count(2)):
        with pytest.raises(OSError, match="simulated crash"):
            _multi_file_commit(store, "run-crash")

    txn_dir = _find_txn_dir(store, "run-crash")
    assert txn_dir is not None
    journal = json.loads((txn_dir / "journal.json").read_text(encoding="utf-8"))
    assert journal["status"] == "replacing"

    recovered = FileRunStore(tmp_path)
    run_after = recovered.load_run("run-crash")
    plan_after = recovered.load_plan("run-crash")
    assert run_after["revision"] == 1
    assert plan_after["revision"] == 1
    events_after = recovered.load_events("run-crash")
    assert len(events_after) == len(events_before) + 1
    assert events_after[-1]["type"] == "test_commit"
    assert events_after[-1]["txn_id"] == journal["txn_id"]
    assert not _find_txn_dir(recovered, "run-crash")


def test_prepared_journal_discarded_without_mutating_destinations(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    run_before = store.load_run("run-crash")
    plan_before = store.load_plan("run-crash")

    txn_dir = store.run_dir("run-crash") / ".txn-manual"
    txn_dir.mkdir()
    staging = txn_dir
    atomic_payload = dict(plan_before)
    atomic_payload["revision"] = int(plan_before["revision"]) + 1
    (staging / "plan.json").write_text(
        json.dumps(atomic_payload, sort_keys=True),
        encoding="utf-8",
    )
    journal = {
        "txn_id": "manual",
        "status": "prepared",
        "files": [{"kind": "plan", "name": "plan.json"}],
        "events": [],
        "backups": [],
        "replaced": [],
    }
    (staging / "journal.json").write_text(json.dumps(journal), encoding="utf-8")

    recovered = FileRunStore(tmp_path)
    assert recovered.load_plan("run-crash")["revision"] == plan_before["revision"]
    assert recovered.load_run("run-crash")["revision"] == run_before["revision"]
    assert not _find_txn_dir(recovered, "run-crash")
