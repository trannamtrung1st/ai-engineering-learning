"""Resume apply ownership and revision CAS tests (§21 test 24; §10.1)."""

from __future__ import annotations

import copy
import multiprocessing
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.resume_plan import ResumePlan, ResumePlanValidation, ResumeStateTransition
from top_down_planning.domain.run_lifecycle import StopRecord
from top_down_planning.domain.run_ownership import (
    RunOwnershipError,
    acquire_run_ownership,
    run_ownership,
)
from top_down_planning.orchestrator.apply_resume import ApplyResumeError, apply_resume_plan_atomically
from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.orchestrator.resume import (
    assert_resume_apply_preconditions,
    assert_running_continuation_preconditions,
)
from top_down_planning.orchestrator.run_transitions import pause_run, reconcile_pending_capability_revocation
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


def _pause_stop() -> StopRecord:
    return StopRecord(
        code="user_cancelled",
        category="operational",
        phase=PLANNING,
        message="cancelled",
    )


def _create_paused_planning_run(store: FileRunStore) -> str:
    run_id = "run-20260101T001301-001301"
    config = minimal_resolved_config()
    store.create_run(
        run_id,
        plan=_sample_plan(),
        phase=PLANNING,
        **create_run_kwargs(store.root, resolved_config=config),
    )
    pause_run(store, run_id, stop=_pause_stop(), revoke_phase=PLANNING)
    return run_id


def _paused_resume_plan(
    store: FileRunStore,
    run_id: str,
) -> ResumePlan:
    paused = store.load_run(run_id)
    config = store.load_resolved_config(run_id)
    return ResumePlan(
        run_id=run_id,
        expected_run_revision=int(paused["revision"]),
        state_transition=ResumeStateTransition(
            from_status="paused",
            to_status="running",
            prior_stop_code="user_cancelled",
        ),
        config_changes={},
        session_policy={},
        validation=ResumePlanValidation(
            contract_digest_valid=True,
            plan_binding_valid=True,
            approval_binding_valid=True,
            evidence_binding_valid=True,
            context_binding_valid=True,
        ),
        effective_config=config,
    )


def _apply_resume_config_worker(
    root: str,
    run_id: str,
    candidate_config: dict[str, Any],
    invocation: dict[str, Any],
    queue: Any,
    ready: Any,
) -> None:
    worker_store = FileRunStore(Path(root))
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

    ctx = multiprocessing.get_context("spawn")
    queue: multiprocessing.Queue[str] = ctx.Queue()
    ready = ctx.Barrier(2)

    token = acquire_run_ownership(run_id, run_dir=run_dir)
    process = ctx.Process(
        target=_apply_resume_config_worker,
        args=(
            str(tmp_path),
            run_id,
            candidate_config,
            invocation,
            queue,
            ready,
        ),
    )
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


def test_apply_resume_plan_blocked_while_other_process_holds_ownership(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_paused_planning_run(store)
    run_dir = store.run_dir(run_id)
    plan = _paused_resume_plan(store, run_id)
    config = store.load_resolved_config(run_id)
    revision_before = int(store.load_run(run_id)["revision"])

    barrier = threading.Barrier(2)
    apply_errors: list[ApplyResumeError] = []

    def holder() -> None:
        with run_ownership(run_id, run_dir=run_dir):
            barrier.wait()
            time.sleep(0.3)

    def contender() -> None:
        try:
            barrier.wait()
            apply_resume_plan_atomically(store, plan, resolved_config=config)
        except ApplyResumeError as exc:
            apply_errors.append(exc)

    holder_thread = threading.Thread(target=holder)
    contender_thread = threading.Thread(target=contender)
    holder_thread.start()
    contender_thread.start()
    holder_thread.join(timeout=5)
    contender_thread.join(timeout=5)
    assert not holder_thread.is_alive()
    assert not contender_thread.is_alive()

    assert len(apply_errors) == 1
    assert apply_errors[0].code == "run_owned_by_live_process"
    paused = store.load_run(run_id)
    assert paused["status"] == "paused"
    assert int(paused["revision"]) == revision_before


def test_apply_resume_holds_ownership_until_commit(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_paused_planning_run(store)
    plan = _paused_resume_plan(store, run_id)
    config = store.load_resolved_config(run_id)
    revision_before = int(store.load_run(run_id)["revision"])
    run_dir = store.run_dir(run_id)

    commit_barrier = threading.Barrier(2)
    ownership_errors: list[RunOwnershipError] = []
    original_commit = store.commit

    def slow_commit(*args: Any, **kwargs: Any) -> dict[str, Any]:
        commit_barrier.wait()
        time.sleep(0.2)
        return original_commit(*args, **kwargs)

    def apply_worker() -> None:
        with patch.object(store, "commit", side_effect=slow_commit):
            apply_resume_plan_atomically(store, plan, resolved_config=config)

    def contender() -> None:
        try:
            commit_barrier.wait()
            acquire_run_ownership(run_id, run_dir=run_dir)
        except RunOwnershipError as exc:
            ownership_errors.append(exc)

    apply_thread = threading.Thread(target=apply_worker)
    contender_thread = threading.Thread(target=contender)
    apply_thread.start()
    contender_thread.start()
    apply_thread.join(timeout=10)
    contender_thread.join(timeout=10)
    assert not apply_thread.is_alive()
    assert not contender_thread.is_alive()

    assert len(ownership_errors) == 1
    assert ownership_errors[0].code == "run_owned_by_live_process"
    resumed = store.load_run(run_id)
    assert resumed["status"] == "running"
    assert int(resumed["revision"]) == revision_before + 1


def test_apply_resume_contender_cannot_acquire_during_reconcile_stale_plan(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    from tests.helpers import grant_capability

    grant_capability(store, run_id, role="planner", phase=PLANNING)

    with patch(
        "top_down_planning.orchestrator.run_transitions.revoke_capabilities_for_phase",
        side_effect=OSError("revoke failed"),
    ):
        pause_run(store, run_id, stop=_pause_stop(), revoke_phase=PLANNING)

    revision_after_pause = int(store.load_run(run_id)["revision"])
    plan = _paused_resume_plan(store, run_id)
    config = store.load_resolved_config(run_id)
    run_dir = store.run_dir(run_id)

    reconcile_barrier = threading.Barrier(2)
    ownership_errors: list[RunOwnershipError] = []

    original_reconcile = reconcile_pending_capability_revocation

    def reconcile_and_hold(*args: Any, **kwargs: Any) -> None:
        original_reconcile(*args, **kwargs)
        reconcile_barrier.wait()
        time.sleep(0.2)

    apply_errors: list[ApplyResumeError] = []

    def apply_worker() -> None:
        with patch(
            "top_down_planning.orchestrator.apply_resume.reconcile_pending_capability_revocation",
            side_effect=reconcile_and_hold,
        ):
            try:
                apply_resume_plan_atomically(store, plan, resolved_config=config)
            except ApplyResumeError as exc:
                apply_errors.append(exc)

    def contender() -> None:
        reconcile_barrier.wait()
        try:
            acquire_run_ownership(run_id, run_dir=run_dir)
        except RunOwnershipError as exc:
            ownership_errors.append(exc)

    apply_thread = threading.Thread(target=apply_worker)
    contender_thread = threading.Thread(target=contender)
    apply_thread.start()
    contender_thread.start()
    apply_thread.join(timeout=10)
    contender_thread.join(timeout=10)
    assert not apply_thread.is_alive()
    assert not contender_thread.is_alive()

    assert len(ownership_errors) == 1
    assert ownership_errors[0].code == "run_owned_by_live_process"
    assert len(apply_errors) == 1
    assert apply_errors[0].code == "resume_apply_blocked"
    assert "stale after capability reconciliation" in str(apply_errors[0])
    paused = store.load_run(run_id)
    assert paused["status"] == "paused"
    assert int(paused["revision"]) == revision_after_pause + 1


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


def test_apply_resume_config_reuses_nested_run_ownership(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    run_dir = store.run_dir(run_id)
    stored_config = store.load_resolved_config(run_id)
    candidate_config = _with_limit_override(stored_config, "limits.production.max_batches", 99)
    invocation = store.load_invocation(run_id)

    with run_ownership(run_id, run_dir=run_dir):
        result = apply_resume_config_atomic(
            store,
            run_id,
            resolved_config=candidate_config,
            invocation=invocation,
            run_expected_revision=1,
        )

    assert result["run_revision"] == 2
    assert store.load_resolved_config(run_id) == candidate_config


def _with_limit_override(config: dict, path: str, value: int) -> dict:
    updated = copy.deepcopy(config)
    parts = path.split(".")
    current = updated
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value
    return updated


def test_apply_resume_config_blocked_while_other_process_holds_ownership(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    run_dir = store.run_dir(run_id)
    stored_config = store.load_resolved_config(run_id)
    candidate_config = _with_limit_override(stored_config, "limits.production.max_batches", 99)
    invocation = store.load_invocation(run_id)
    revision_before = int(store.load_run(run_id)["revision"])

    barrier = threading.Barrier(2)
    config_errors: list[ResumeConfigCommitError] = []

    def holder() -> None:
        with run_ownership(run_id, run_dir=run_dir):
            barrier.wait()
            time.sleep(0.3)

    def contender() -> None:
        try:
            barrier.wait()
            apply_resume_config_atomic(
                store,
                run_id,
                resolved_config=candidate_config,
                invocation=invocation,
                run_expected_revision=revision_before,
            )
        except ResumeConfigCommitError as exc:
            config_errors.append(exc)

    holder_thread = threading.Thread(target=holder)
    contender_thread = threading.Thread(target=contender)
    holder_thread.start()
    contender_thread.start()
    holder_thread.join(timeout=5)
    contender_thread.join(timeout=5)
    assert not holder_thread.is_alive()
    assert not contender_thread.is_alive()

    assert len(config_errors) == 1
    assert "owned" in str(config_errors[0]).lower()
    assert store.load_resolved_config(run_id) == stored_config
    assert store.load_invocation(run_id) == invocation
    assert int(store.load_run(run_id)["revision"]) == revision_before


def test_apply_resume_config_holds_ownership_until_commit(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    run_dir = store.run_dir(run_id)
    stored_config = store.load_resolved_config(run_id)
    candidate_config = _with_limit_override(stored_config, "limits.production.max_batches", 99)
    invocation = store.load_invocation(run_id)
    revision_before = int(store.load_run(run_id)["revision"])

    commit_barrier = threading.Barrier(2)
    ownership_errors: list[RunOwnershipError] = []
    original_commit = store.commit

    def slow_commit(*args: Any, **kwargs: Any) -> dict[str, Any]:
        commit_barrier.wait()
        time.sleep(0.2)
        return original_commit(*args, **kwargs)

    def config_worker() -> None:
        with patch.object(store, "commit", side_effect=slow_commit):
            apply_resume_config_atomic(
                store,
                run_id,
                resolved_config=candidate_config,
                invocation=invocation,
                run_expected_revision=revision_before,
            )

    def contender() -> None:
        try:
            commit_barrier.wait()
            acquire_run_ownership(run_id, run_dir=run_dir)
        except RunOwnershipError as exc:
            ownership_errors.append(exc)

    config_thread = threading.Thread(target=config_worker)
    contender_thread = threading.Thread(target=contender)
    config_thread.start()
    contender_thread.start()
    config_thread.join(timeout=10)
    contender_thread.join(timeout=10)
    assert not config_thread.is_alive()
    assert not contender_thread.is_alive()

    assert len(ownership_errors) == 1
    assert ownership_errors[0].code == "run_owned_by_live_process"
    assert store.load_resolved_config(run_id) == candidate_config
    assert int(store.load_run(run_id)["revision"]) == revision_before + 1
