"""Spawn-safe worker for commit concurrency tests."""

from __future__ import annotations


def commit_plan_worker(
    store_root: str,
    run_id: str,
    result_queue,
    load_barrier,
    commit_barrier,
) -> None:
    from pathlib import Path

    from core_tools.persistence import StoreRevisionConflictError
    from top_down_planning.persistence import FileRunStore
    from top_down_planning.persistence.commit import CommitSpec

    store = FileRunStore(Path(store_root))
    plan = store.load_plan(run_id)
    expected = int(plan["revision"])
    payload = dict(plan)
    payload["revision"] = expected + 1
    load_barrier.wait()
    commit_barrier.wait()
    try:
        store.commit(
            run_id,
            CommitSpec(plan=payload, plan_expected_revision=expected),
        )
        result_queue.put("ok")
    except StoreRevisionConflictError:
        result_queue.put("conflict")


def hold_lock_with_prepared_txn_worker(
    store_root: str,
    run_id: str,
    ready_queue,
    release_queue,
) -> None:
    from pathlib import Path

    from core_tools.persistence import atomic_write_json, exclusive_file_lock
    from top_down_planning.persistence import FileRunStore

    store = FileRunStore(Path(store_root))
    run_dir = store.run_dir(run_id)
    staging_dir = run_dir / ".txn-test"
    staging_dir.mkdir()
    atomic_write_json(
        staging_dir / "journal.json",
        {
            "txn_id": "test",
            "status": "prepared",
            "files": [],
            "events": [],
            "backups": [],
            "replaced": [],
        },
    )

    lock_path = run_dir / ".commit.lock"
    with exclusive_file_lock(lock_path):
        ready_queue.put("ready")
        release_queue.get(timeout=30)


def load_plan_reader_worker(
    store_root: str,
    run_id: str,
    result_queue,
    attempt_queue=None,
) -> None:
    from pathlib import Path

    from top_down_planning.persistence import FileRunStore

    store = FileRunStore(Path(store_root))
    if attempt_queue is not None:
        attempt_queue.put("loading")
    plan = store.load_plan(run_id)
    result_queue.put(int(plan["revision"]))


def pause_after_run_json_replace_worker(
    store_root: str,
    run_id: str,
    ready_queue,
    release_queue,
) -> None:
    """Hold the commit lock after publishing a new run.json and before plan.json."""

    from pathlib import Path

    from top_down_planning.persistence import FileRunStore
    from top_down_planning.persistence.commit import CommitSpec
    from top_down_planning.persistence.snapshot_bindings import (
        bind_run_digests_for_plan_update,
    )

    original_replace = Path.replace

    def patched_replace(self: Path, target: Path) -> Path:
        result = original_replace(self, target)
        self_parts = self.parts
        target_parts = target.parts
        if (
            any(part.startswith(".txn-") for part in self_parts)
            and not any(part.startswith(".txn-") for part in target_parts)
            and target.name == "run.json"
        ):
            ready_queue.put("ready")
            release_queue.get(timeout=30)
        return result

    Path.replace = patched_replace
    store = FileRunStore(Path(store_root))
    run = store.load_run(run_id)
    plan = store.load_plan(run_id)
    run_expected = int(run["revision"])
    plan_expected = int(plan["revision"])
    plan = dict(plan)
    plan["revision"] = plan_expected + 1
    run = bind_run_digests_for_plan_update(
        {**dict(run), "revision": run_expected + 1},
        plan,
    )
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
