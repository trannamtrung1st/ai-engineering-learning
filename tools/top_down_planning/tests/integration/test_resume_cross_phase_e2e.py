"""Cross-phase increase+resume E2E tests (proposal §20–§21 tests 1–5)."""

from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from top_down_planning.orchestrator import (
    RunEngine,
    WholePlanReviewOrchestrator,
)
from top_down_planning.orchestrator.apply_resume import apply_resume_plan_atomically
from top_down_planning.orchestrator.phases import (
    PLAN_VALIDATED,
    PLANNING,
    WHOLE_OUTPUT_REVIEW,
    WHOLE_PLAN_REVIEW,
)
from top_down_planning.orchestrator.prepare_resume import prepare_resume
from top_down_planning.persistence import FileRunStore
from core_tools.provider import StubProvider
from tests.conftest import run_cli
from tests.helpers import (
    apply_plan,
    done_events,
    mandatory_initial_respond_request,
    mandatory_scope_review_respond_request,
    mandatory_verification_respond_request,
    prepare_loop_for_scope_review_respond,
    respond_review,
    whole_output_approval_record,
    whole_plan_approval_record,
    with_root_contract,
    work_item_payload,
)
from top_down_planning.domain.approval_digests import OUTPUT_APPROVAL_DIGEST_KEYS
from tests.helpers import approved_digests_from_run
from tests.integration.e2e_helpers import (
    E2EStubProvider,
    planning_single_leaf_script,
    queue_turn,
    write_e2e_config,
)
from tests.unit.test_whole_output_review import (
    _create_run_at_whole_output_review as create_run_at_whole_output_review,
)
from tests.unit.test_whole_plan_review import (
    _create_run_at_whole_plan_review as create_run_at_whole_plan_review,
    _review_respond_request as whole_plan_review_respond_request,
)


@pytest.fixture
def provider() -> E2EStubProvider:
    return E2EStubProvider()


@pytest.fixture
def patch_provider(provider: E2EStubProvider):
    with patch("top_down_planning.cli.user.create_provider", return_value=provider):
        yield provider


def _planning_one_item_continue_script(
    store: FileRunStore,
) -> tuple[list[dict[str, Any]], Callable[[], None]]:
    operations = with_root_contract(
        [
            {
                "op": "add_item",
                "temp_id": "item-task",
                "parent_id": "item-root",
                "placement": {"last_child": True},
                "item": work_item_payload(
                    title="Deliver feature",
                    outcome="Feature is delivered and verifiable.",
                    acceptance=["Feature behavior is testable."],
                ),
            }
        ]
    )

    def mutate() -> None:
        from tests.helpers import only_run_id

        run_id = only_run_id(store)
        apply_plan(store, run_id, base_revision=0, operations=operations)()

    return done_events(signal="continue", text="planning turn"), mutate


def _planning_complete_script(
    store: FileRunStore,
) -> tuple[list[dict[str, Any]], Callable[[], None]]:
    operations = with_root_contract(
        [
            {
                "op": "add_item",
                "temp_id": "item-task-2",
                "parent_id": "item-root",
                "placement": {"last_child": True},
                "item": work_item_payload(
                    title="Deliver feature follow-up",
                    outcome="Follow-up feature work is delivered.",
                    acceptance=["Follow-up behavior is testable."],
                ),
            }
        ]
    )

    def mutate() -> None:
        from tests.helpers import only_run_id

        run_id = only_run_id(store)
        revision = int(store.load_plan(run_id)["revision"])
        apply_plan(store, run_id, base_revision=revision, operations=operations)()

    return done_events(signal="candidate_plan_ready", text="planning turn"), mutate


def _set_nested_limit(config: dict[str, Any], limit_path: str, value: int) -> None:
    parts = limit_path.removeprefix("limits.").split(".")
    node = config["limits"]
    for part in parts[:-1]:
        node = node[part]
    node[parts[-1]] = value


def _apply_limit_increase(
    store: FileRunStore,
    run_id: str,
    limit_path: str,
    new_value: int,
):
    stored = store.load_resolved_config(run_id)
    candidate = copy.deepcopy(stored)
    _set_nested_limit(candidate, limit_path, new_value)
    resume_plan = prepare_resume(store, run_id, candidate)
    apply_resume_plan_atomically(
        store,
        resume_plan,
        resolved_config=candidate,
        invocation=store.load_invocation(run_id),
    )
    return resume_plan


def _continue_after_apply(
    store: FileRunStore,
    run_id: str,
    provider: E2EStubProvider | StubProvider,
    resume_plan,
    *,
    until: str,
):
    engine = RunEngine(
        store,
        create_provider=lambda config, workspace: provider,
    )
    return engine.continue_run(
        run_id,
        until=until,
        session_policy=resume_plan.session_policy,
    )


def _increase_limit_apply_and_continue(
    store: FileRunStore,
    run_id: str,
    provider: E2EStubProvider | StubProvider,
    limit_path: str,
    new_value: int,
    *,
    until: str,
):
    resume_plan = _apply_limit_increase(store, run_id, limit_path, new_value)
    return _continue_after_apply(
        store,
        run_id,
        provider,
        resume_plan,
        until=until,
    )


def _assert_limit_resume_traceability(
    store: FileRunStore,
    run_id: str,
    *,
    limit_path: str,
    new_value: int,
    counters_before: dict[str, Any],
    counters_key: str,
) -> None:
    run = store.load_run(run_id)
    assert run["status"] == "running"
    assert run["stop"] is None
    assert dict(run.get(counters_key) or {}) == counters_before

    config = store.load_resolved_config(run_id)
    limit_parts = limit_path.removeprefix("limits.").split(".")
    value: Any = config["limits"]
    for part in limit_parts:
        value = value[part]
    assert int(value) == new_value

    events = store.load_events(run_id)
    assert any(event.get("type") == "resume_applied" for event in events)
    assert any(event.get("type") == "resume_limit_extended" for event in events)
    extended = [
        event
        for event in events
        if event.get("type") == "resume_limit_extended"
    ][-1]
    assert limit_path in extended.get("paths", [])


def _pause_whole_plan_revision_limit(
    store: FileRunStore,
) -> str:
    run_id = "run-20260101T000301-000301"
    provider = StubProvider()
    create_run_at_whole_plan_review(
        store,
        run_id,
        limits={"max_revision_cycles": 1},
        provider=provider,
    )
    provider.script_turn(
        done_events(text="turn complete"),
        mutate_store=respond_review(
            store,
            run_id,
            whole_plan_review_respond_request(
                decision="changes_requested",
                findings=[
                    {
                        "id": "finding-01",
                        "severity": "blocker",
                        "target_refs": ["item-api"],
                        "issue": "Needs work.",
                        "recommended_change": "Improve acceptance.",
                        "status": "unresolved",
                    }
                ],
                store=store,
                run_id=run_id,
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id="review-whole-plan-01",
        ),
    )
    provider.script_turn(done_events(text="turn complete"))
    provider.script_turn(
        done_events(text="turn complete"),
        mutate_store=respond_review(
            store,
            run_id,
            whole_plan_review_respond_request(
                decision="changes_requested",
                target_revision=0,
                findings=[
                    {
                        "id": "finding-01",
                        "severity": "blocker",
                        "target_refs": ["item-api"],
                        "issue": "Still needs work.",
                        "recommended_change": "Improve acceptance.",
                        "status": "unresolved",
                    }
                ],
                store=store,
                run_id=run_id,
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id="review-whole-plan-01",
        ),
    )
    result = WholePlanReviewOrchestrator(store, run_id, provider).run()
    assert result.ok is False
    assert result.status == "paused"
    return run_id


def _pause_whole_output_revision_limit(
    store: FileRunStore,
) -> str:
    run_id = "run-20260101T000801-000801"
    provider = StubProvider()
    create_run_at_whole_output_review(
        store,
        run_id,
        limits={"max_revision_cycles": 1},
        provider=provider,
    )
    plan_approval = whole_plan_approval_record(store, run_id)
    plan_approval["approved_digests"] = approved_digests_from_run(
        store,
        run_id,
        keys=OUTPUT_APPROVAL_DIGEST_KEYS,
    )
    store.save_review(run_id, plan_approval)
    store.save_review(
        run_id,
        whole_output_approval_record(
            store,
            run_id,
            status="changes_requested",
            lifecycle_status="limit_reached",
            revision_cycles=1,
        ),
    )
    review = store.load_review(run_id, "review-whole-output-01")
    revision_cycles = int(review.get("revision_cycles") or 1)
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["status"] = "paused"
    run["stop"] = {
        "code": "limit_exhausted",
        "category": "operational",
        "phase": WHOLE_OUTPUT_REVIEW,
        "message": "whole-output review exceeded max_revision_cycles (1)",
        "details": {
            "limit": "limits.whole_output_review.max_revision_cycles",
            "consumed": revision_cycles,
            "configured": 1,
        },
    }
    store.save_run(run_id, run, expected_revision)
    return run_id


def _pause_whole_plan_scope_review_limit(
    store: FileRunStore,
) -> str:
    run_id = "run-20260101T000301-000301"
    provider = StubProvider()
    create_run_at_whole_plan_review(
        store,
        run_id,
        limits={"max_revision_cycles": 5, "max_scope_review_rounds": 1},
        provider=provider,
    )
    respond_review(
        store,
        run_id,
        mandatory_initial_respond_request(
            store,
            run_id,
            loop_id="review-whole-plan-01",
            target_revision=0,
            review_type="whole_plan",
        ),
        phase=WHOLE_PLAN_REVIEW,
        loop_id="review-whole-plan-01",
    )()
    prepare_loop_for_scope_review_respond(
        store,
        run_id,
        "review-whole-plan-01",
        target_revision=0,
    )
    respond_review(
        store,
        run_id,
        mandatory_scope_review_respond_request(
            store,
            run_id,
            loop_id="review-whole-plan-01",
            target_revision=0,
            review_type="whole_plan",
            findings=[
                {
                    "id": "finding-blocker-01",
                    "severity": "blocker",
                    "target_refs": ["item-api"],
                    "issue": "Still blocked.",
                    "recommended_change": "Fix coverage.",
                    "status": "unresolved",
                }
            ],
        ),
        phase=WHOLE_PLAN_REVIEW,
        loop_id="review-whole-plan-01",
    )()
    apply_plan(
        store,
        run_id,
        base_revision=0,
        operations=[
            {
                "op": "update_item",
                "item_id": "item-api",
                "patch": {"acceptance": ["API behavior is verifiable.", "Extra."]},
            }
        ],
        phase=WHOLE_PLAN_REVIEW,
    )()
    loop = store.load_review(run_id, "review-whole-plan-01")
    loop_payload = dict(loop)
    loop_payload["lifecycle_status"] = "verification_pending"
    loop_payload["active_stage"] = "finding_verification"
    loop_payload["status"] = "pending"
    loop_payload["target_revision"] = 1
    store.save_review(run_id, loop_payload)
    respond_review(
        store,
        run_id,
        mandatory_verification_respond_request(
            store,
            run_id,
            loop_id="review-whole-plan-01",
            target_revision=1,
            review_type="whole_plan",
            finding_set_id=str(loop.get("finding_set_id") or "fs-1"),
            finding_results=[
                {
                    "finding_id": "finding-blocker-01",
                    "disposition": "resolved",
                    "evidence": ["fixed"],
                    "direct_side_effects": [],
                }
            ],
        ),
        phase=WHOLE_PLAN_REVIEW,
        loop_id="review-whole-plan-01",
    )()
    result = WholePlanReviewOrchestrator(store, run_id, provider).run()
    assert result.ok is False
    assert result.status == "paused"
    return run_id


@pytest.mark.integration
def test_resume_planning_turn_limit_exhausted_increased_and_resumed(
    tmp_path: Path,
    patch_provider: E2EStubProvider,
) -> None:
    """§21 test 1: planning turn limit pause, limit increase, resume, and continuation."""

    config_path = write_e2e_config(
        tmp_path / "run.yaml",
        limits={"planning": {"max_agent_turns": 1}},
    )
    runs_dir = tmp_path / "runs"
    store = FileRunStore(runs_dir)

    patch_provider.script_turn(done_events(signal="continue", text="planning turn"))
    run_result = run_cli(
        [
            "run",
            "--config",
            str(config_path),
            "--runs-dir",
            str(runs_dir),
            "--stream-json",
        ]
    )
    assert run_result.exit_code == 1
    pause_payload = run_result.json()
    assert pause_payload["status"] == "paused"
    run_id = pause_payload["run_id"]

    counters_before = dict(store.load_run(run_id).get("planning") or {})
    queue_turn(patch_provider, planning_single_leaf_script(store))
    resume_plan = _apply_limit_increase(
        store,
        run_id,
        "limits.planning.max_agent_turns",
        5,
    )
    _assert_limit_resume_traceability(
        store,
        run_id,
        limit_path="limits.planning.max_agent_turns",
        new_value=5,
        counters_before=counters_before,
        counters_key="planning",
    )
    continuation = _continue_after_apply(
        store,
        run_id,
        patch_provider,
        resume_plan,
        until="plan",
    )
    assert continuation.ok is True
    assert continuation.phase == WHOLE_PLAN_REVIEW


@pytest.mark.integration
def test_resume_planning_item_limit_exhausted_increased_and_resumed(
    tmp_path: Path,
    patch_provider: E2EStubProvider,
) -> None:
    """§21 test 2: planning item limit pause, limit increase, resume, and continuation."""

    config_path = write_e2e_config(
        tmp_path / "run.yaml",
        limits={"planning": {"max_items_added": 1, "max_agent_turns": 5}},
    )
    runs_dir = tmp_path / "runs"
    store = FileRunStore(runs_dir)

    queue_turn(patch_provider, _planning_one_item_continue_script(store))
    run_result = run_cli(
        [
            "run",
            "--config",
            str(config_path),
            "--runs-dir",
            str(runs_dir),
            "--stream-json",
        ]
    )
    assert run_result.exit_code == 1
    pause_payload = run_result.json()
    assert pause_payload["status"] == "paused"
    assert pause_payload["phase"] == PLANNING
    run_id = pause_payload["run_id"]

    counters_before = dict(store.load_run(run_id).get("planning") or {})

    queue_turn(patch_provider, _planning_complete_script(store))
    resume_plan = _apply_limit_increase(
        store,
        run_id,
        "limits.planning.max_items_added",
        5,
    )
    _assert_limit_resume_traceability(
        store,
        run_id,
        limit_path="limits.planning.max_items_added",
        new_value=5,
        counters_before=counters_before,
        counters_key="planning",
    )
    continuation = _continue_after_apply(
        store,
        run_id,
        patch_provider,
        resume_plan,
        until="plan",
    )
    assert continuation.ok is True
    assert continuation.phase == WHOLE_PLAN_REVIEW


@pytest.mark.integration
def test_resume_whole_plan_revision_limit_exhausted_increased_and_resumed(
    tmp_path: Path,
) -> None:
    """§21 test 3: whole-plan revision limit pause, increase, resume, and approval."""

    runs_dir = tmp_path / "runs"
    store = FileRunStore(runs_dir)
    run_id = _pause_whole_plan_revision_limit(store)

    review_before = store.load_review(run_id, "review-whole-plan-01")
    revision_cycles_before = int(review_before.get("revision_cycles") or 0)

    _apply_limit_increase(
        store,
        run_id,
        "limits.whole_plan_review.max_revision_cycles",
        5,
    )

    run = store.load_run(run_id)
    assert run["status"] == "running"
    assert run["stop"] is None
    review_after = store.load_review(run_id, "review-whole-plan-01")
    assert int(review_after.get("revision_cycles") or 0) == revision_cycles_before
    config = store.load_resolved_config(run_id)
    assert int(config["limits"]["whole_plan_review"]["max_revision_cycles"]) == 5
    events = store.load_events(run_id)
    assert any(event.get("type") == "resume_applied" for event in events)
    assert any(event.get("type") == "resume_limit_extended" for event in events)


@pytest.mark.integration
def test_resume_whole_output_revision_limit_exhausted_increased_and_resumed(
    tmp_path: Path,
) -> None:
    """§21 test 4: whole-output revision limit pause, increase, resume, and approval."""

    runs_dir = tmp_path / "runs"
    store = FileRunStore(runs_dir)
    run_id = _pause_whole_output_revision_limit(store)

    review_before = store.load_review(run_id, "review-whole-output-01")
    revision_cycles_before = int(review_before.get("revision_cycles") or 0)

    _apply_limit_increase(
        store,
        run_id,
        "limits.whole_output_review.max_revision_cycles",
        5,
    )

    review_after = store.load_review(run_id, "review-whole-output-01")
    assert int(review_after.get("revision_cycles") or 0) == revision_cycles_before
    config = store.load_resolved_config(run_id)
    assert int(config["limits"]["whole_output_review"]["max_revision_cycles"]) == 5
    events = store.load_events(run_id)
    assert any(event.get("type") == "resume_applied" for event in events)
    assert any(event.get("type") == "resume_limit_extended" for event in events)


@pytest.mark.integration
def test_resume_scope_review_limit_exhausted_increased_and_resumed(
    tmp_path: Path,
) -> None:
    """§21 test 5: scope-review round limit pause, increase, resume, and approval."""

    runs_dir = tmp_path / "runs"
    store = FileRunStore(runs_dir)
    run_id = _pause_whole_plan_scope_review_limit(store)

    review_before = store.load_review(run_id, "review-whole-plan-01")
    scope_rounds_before = int(review_before.get("scope_review_rounds") or 0)

    _apply_limit_increase(
        store,
        run_id,
        "limits.whole_plan_review.max_scope_review_rounds",
        5,
    )

    review_after = store.load_review(run_id, "review-whole-plan-01")
    assert int(review_after.get("scope_review_rounds") or 0) == scope_rounds_before
    config = store.load_resolved_config(run_id)
    assert int(config["limits"]["whole_plan_review"]["max_scope_review_rounds"]) == 5
    events = store.load_events(run_id)
    assert any(event.get("type") == "resume_applied" for event in events)
    assert any(event.get("type") == "resume_limit_extended" for event in events)


@pytest.mark.integration
def test_success_signal_limit_increase_check_apply_and_continue(
    tmp_path: Path,
    patch_provider: E2EStubProvider,
) -> None:
    """Proposal success signal: pause → prepare_resume (--check) → apply → continue."""

    config_path = write_e2e_config(
        tmp_path / "run.yaml",
        limits={"planning": {"max_agent_turns": 1}},
    )
    runs_dir = tmp_path / "runs"
    store = FileRunStore(runs_dir)

    patch_provider.script_turn(done_events(signal="continue", text="planning turn"))
    run_result = run_cli(
        [
            "run",
            "--config",
            str(config_path),
            "--runs-dir",
            str(runs_dir),
            "--stream-json",
        ]
    )
    assert run_result.exit_code == 1
    run_id = run_result.json()["run_id"]
    revision_before = int(store.load_run(run_id)["revision"])

    stored = store.load_resolved_config(run_id)
    candidate = copy.deepcopy(stored)
    _set_nested_limit(candidate, "limits.planning.max_agent_turns", 5)
    prepare_resume(store, run_id, candidate)
    assert int(store.load_run(run_id)["revision"]) == revision_before

    queue_turn(patch_provider, planning_single_leaf_script(store))
    continuation = _increase_limit_apply_and_continue(
        store,
        run_id,
        patch_provider,
        "limits.planning.max_agent_turns",
        5,
        until="plan",
    )
    assert continuation.ok is True
    assert continuation.phase == WHOLE_PLAN_REVIEW


@pytest.mark.integration
def test_running_continuation_resume_without_config_mutation(
    tmp_path: Path,
    patch_provider: E2EStubProvider,
) -> None:
    """Idle ``running`` runs continue without config mutation after a milestone."""

    from top_down_planning.orchestrator.resume import assert_running_continuation_preconditions

    config_path = write_e2e_config(tmp_path / "run.yaml")
    runs_dir = tmp_path / "runs"
    store = FileRunStore(runs_dir)

    queue_turn(patch_provider, planning_single_leaf_script(store))
    run_result = run_cli(
        [
            "run",
            "--config",
            str(config_path),
            "--runs-dir",
            str(runs_dir),
            "--stream-json",
        ]
    )
    assert run_result.exit_code == 0
    run_id = run_result.json()["run_id"]
    stored_config = store.load_resolved_config(run_id)

    run = store.load_run(run_id)
    snapshot = assert_running_continuation_preconditions(
        store,
        run_id,
        expected_run_revision=int(run["revision"]),
    )
    assert snapshot.status == "running"
    assert store.load_resolved_config(run_id) == stored_config
