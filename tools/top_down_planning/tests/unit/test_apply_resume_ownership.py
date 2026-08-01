"""Resume apply ownership and revision CAS tests (§21 test 24; §10.1 interim)."""

from __future__ import annotations

import multiprocessing
from pathlib import Path

import pytest

from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.run_ownership import acquire_run_ownership, run_ownership
from top_down_planning.orchestrator.resume import (
    assert_resume_apply_preconditions,
    assert_running_continuation_preconditions,
)
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.config_commit import (
    ResumeConfigCommitError,
    apply_resume_config_atomic,
)
from tests.helpers import create_run_kwargs, minimal_resolved_config


def _sample_plan() -> Plan:
    return Plan(
        id="plan-run-test",
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


def _create_running_run(store: FileRunStore) -> str:
    run_id = "run-20260101T001201-001201"
    config = minimal_resolved_config()
    store.create_run(
        run_id,
        plan=_sample_plan(),
        phase="production",
        **create_run_kwargs(store.root, resolved_config=config),
    )
    run = store.load_run(run_id)
    run["status"] = "running"
    run["revision"] = 1
    store.save_run(run_id, run, expected_revision=0)
    return run_id


def test_concurrent_resume_apply_blocked_while_engine_owns_run(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    run_dir = store.run_dir(run_id)
    candidate_config = dict(store.load_resolved_config(run_id))
    candidate_config["limits"] = dict(candidate_config["limits"])
    candidate_config["limits"]["production"] = dict(
        candidate_config["limits"]["production"]
    )
    candidate_config["limits"]["production"]["max_batches"] = 99
    invocation = store.load_invocation(run_id)

    ctx = multiprocessing.get_context("fork")
    queue: multiprocessing.Queue[str] = ctx.Queue()
    ready = ctx.Barrier(2)

    def worker() -> None:
        worker_store = FileRunStore(tmp_path)
        ready.wait()
        try:
            apply_resume_config_atomic(
                worker_store,
                run_id,
                resolved_config=candidate_config,
                invocation=invocation,
                run_expected_revision=1,
            )
            queue.put("ok")
        except ResumeConfigCommitError:
            queue.put("blocked")

    token = acquire_run_ownership(run_id, run_dir=run_dir)
    process = ctx.Process(target=worker)
    process.start()
    ready.wait()
    process.join(timeout=10)
    assert process.exitcode == 0
    assert queue.get(timeout=5) == "blocked"

    from top_down_planning.domain.run_ownership import release_run_ownership

    release_run_ownership(run_id, run_dir=run_dir, owner_token=token)
    apply_resume_config_atomic(
        store,
        run_id,
        resolved_config=candidate_config,
        invocation=invocation,
        run_expected_revision=1,
    )


def test_running_continuation_preconditions_without_config_mutation(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    run = store.load_run(run_id)
    stored_config = store.load_resolved_config(run_id)

    snapshot = assert_running_continuation_preconditions(
        store,
        run_id,
        expected_run_revision=int(run["revision"]),
    )
    assert snapshot.status == "running"
    assert store.load_resolved_config(run_id) == stored_config


def test_resume_apply_preconditions_reject_stale_revision(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    with pytest.raises(Exception, match="revision is stale"):
        assert_resume_apply_preconditions(store, run_id, expected_run_revision=99)


def test_resume_apply_blocked_when_continue_run_holds_ownership(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    run_dir = store.run_dir(run_id)
    candidate_config = store.load_resolved_config(run_id)
    invocation = store.load_invocation(run_id)

    with run_ownership(run_id, run_dir=run_dir):
        with pytest.raises(ResumeConfigCommitError, match="owned"):
            apply_resume_config_atomic(
                store,
                run_id,
                resolved_config=candidate_config,
                invocation=invocation,
                run_expected_revision=1,
            )
