"""Spawn-safe workers for persistence review regression tests."""

from __future__ import annotations


def concurrent_create_worker(store_root: str, run_id: str, result_queue, barrier) -> None:
    from pathlib import Path

    from core_tools.persistence import PersistenceError
    from top_down_planning.domain.models import Plan, PlanItem
    from top_down_planning.persistence import FileRunStore
    from tests.helpers import create_run_kwargs, minimal_resolved_config

    store = FileRunStore(Path(store_root))
    plan = Plan(
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
    barrier.wait()
    try:
        store.create_run(
            run_id,
            plan=plan,
            **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
        )
        result_queue.put("ok")
    except PersistenceError:
        result_queue.put("conflict")


def load_config_reader_worker(
    store_root: str,
    run_id: str,
    result_queue,
    ready_queue,
    release_queue,
) -> None:
    from pathlib import Path

    from core_tools.persistence import exclusive_file_lock
    from top_down_planning.persistence import FileRunStore

    store = FileRunStore(Path(store_root))
    run_dir = store.run_dir(run_id)
    lock_path = run_dir / ".commit.lock"
    with exclusive_file_lock(lock_path):
        ready_queue.put("loading")
        release_queue.get(timeout=30)

    config = store.load_resolved_config(run_id)
    run = store.load_run(run_id)
    result_queue.put(
        {
            "config": config,
            "run_revision": int(run["revision"]),
        }
    )
