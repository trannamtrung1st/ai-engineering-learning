"""Concurrency tests for journaled RunStore.commit()."""

from __future__ import annotations

import multiprocessing
import time
from pathlib import Path
from typing import Literal

from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.persistence import FileRunStore
from tests.fixtures.commit_concurrency_worker import (
    commit_plan_worker,
    hold_lock_with_prepared_txn_worker,
    load_plan_reader_worker,
)
from tests.helpers import create_run_kwargs, minimal_resolved_config

CommitResult = Literal["ok", "conflict"]


def _create_run(store: FileRunStore, run_id: str = "run-20260101T000701-000701") -> None:
    workspace = store.root
    config = minimal_resolved_config()
    plan = Plan(
        id="plan-run-20260101T000701-000701",
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


def test_concurrent_commit_with_same_revision_exactly_one_succeeds(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)

    ctx = multiprocessing.get_context("fork")
    queue: multiprocessing.Queue[CommitResult] = ctx.Queue()
    load_barrier = ctx.Barrier(3)
    commit_barrier = ctx.Barrier(3)
    processes = [
        ctx.Process(
            target=commit_plan_worker,
            args=(str(tmp_path), "run-20260101T000701-000701", queue, load_barrier, commit_barrier),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    load_barrier.wait()
    commit_barrier.wait()
    for process in processes:
        process.join()
        assert process.exitcode == 0

    results = [queue.get(timeout=30), queue.get(timeout=30)]
    assert sorted(results) == ["conflict", "ok"]
    assert store.load_plan("run-20260101T000701-000701")["revision"] == 1


def test_reader_waits_for_writer_lock_before_recovering_txn(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    run_id = "run-20260101T000701-000701"
    run_dir = store.run_dir(run_id)

    ctx = multiprocessing.get_context("fork")
    ready_queue: multiprocessing.Queue[str] = ctx.Queue()
    release_queue: multiprocessing.Queue[str] = ctx.Queue()
    result_queue: multiprocessing.Queue[int] = ctx.Queue()

    writer = ctx.Process(
        target=hold_lock_with_prepared_txn_worker,
        args=(str(tmp_path), run_id, ready_queue, release_queue),
    )
    reader = ctx.Process(
        target=load_plan_reader_worker,
        args=(str(tmp_path), run_id, result_queue),
    )

    writer.start()
    assert ready_queue.get(timeout=30) == "ready"
    assert list(run_dir.glob(".txn-*"))

    reader.start()
    time.sleep(0.5)
    assert result_queue.empty()
    assert list(run_dir.glob(".txn-*"))

    release_queue.put("release")
    writer.join(timeout=30)
    reader.join(timeout=30)
    assert writer.exitcode == 0
    assert reader.exitcode == 0

    assert result_queue.get(timeout=30) == 0
    assert not list(run_dir.glob(".txn-*"))
