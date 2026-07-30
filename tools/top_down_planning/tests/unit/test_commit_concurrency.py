"""Concurrency tests for journaled RunStore.commit()."""

from __future__ import annotations

import multiprocessing
from pathlib import Path
from typing import Literal

from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.persistence import FileRunStore
from tests.fixtures.commit_concurrency_worker import commit_plan_worker
from tests.helpers import create_run_kwargs, minimal_resolved_config

CommitResult = Literal["ok", "conflict"]


def _create_run(store: FileRunStore, run_id: str = "run-concurrent") -> None:
    workspace = store.root
    config = minimal_resolved_config()
    plan = Plan(
        id="plan-run-concurrent",
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
    processes = [
        ctx.Process(target=commit_plan_worker, args=(str(tmp_path), "run-concurrent", queue))
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join()
        assert process.exitcode == 0

    results = [queue.get(timeout=30), queue.get(timeout=30)]
    assert sorted(results) == ["conflict", "ok"]
    assert store.load_plan("run-concurrent")["revision"] == 1
