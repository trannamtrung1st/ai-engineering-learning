"""Spawn-safe worker for commit concurrency tests."""

from __future__ import annotations


def commit_plan_worker(store_root: str, run_id: str, result_queue) -> None:
    from pathlib import Path

    from core_tools.persistence import StoreRevisionConflictError
    from top_down_planning.persistence import FileRunStore
    from top_down_planning.persistence.commit import CommitSpec

    store = FileRunStore(Path(store_root))
    plan = store.load_plan(run_id)
    expected = int(plan["revision"])
    payload = dict(plan)
    payload["revision"] = expected + 1
    try:
        store.commit(
            run_id,
            CommitSpec(plan=payload, plan_expected_revision=expected),
        )
        result_queue.put("ok")
    except StoreRevisionConflictError:
        result_queue.put("conflict")
