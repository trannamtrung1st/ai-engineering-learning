"""prepare_resume() blocker and purity tests (§21 tests 11–15, 21, 44–45)."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest

from top_down_planning.config import resolve_config
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator.phases import PLANNING, PRODUCTION, WHOLE_PLAN_REVIEW
from top_down_planning.orchestrator.prepare_resume import (
    PrepareResumeBlockedError,
    prepare_resume,
)
from top_down_planning.persistence import FileRunStore
from tests.helpers import (
    create_run_kwargs,
    make_review_loop,
    minimal_resolved_config,
    whole_plan_approval_record,
    write_config,
)


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


def _create_production_run(
    store: FileRunStore,
    *,
    run_id: str = "run-20260101T001201-001201",
    status: str = "running",
    phase: str = PRODUCTION,
) -> str:
    config = minimal_resolved_config()
    store.create_run(
        run_id,
        plan=_sample_plan(),
        phase=phase,
        **create_run_kwargs(store.root, resolved_config=config),
    )
    store.save_review(run_id, whole_plan_approval_record(store, run_id))
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["status"] = status
    run["revision"] = expected_revision + 1
    if status == "paused":
        run["stop"] = {
            "code": "limit_exhausted",
            "category": "operational",
            "phase": phase,
            "message": "limit reached",
            "details": {
                "limit": "limits.production.max_batches",
                "consumed": 1,
                "configured": 1,
            },
        }
        run["planning"] = {"agent_turns": 0, "items_added": 0}
    store.save_run(run_id, run, expected_revision)
    return run_id


def _run_dir_digest(run_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file():
            continue
        digest.update(path.relative_to(run_dir).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def test_prepare_resume_rejects_input_change(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_production_run(store)
    stored = store.load_resolved_config(run_id)
    candidate = copy.deepcopy(stored)
    run_section = dict(candidate.get("run") or {})
    run_section["input_refs"] = ["other-input.md"]
    candidate["run"] = run_section

    with pytest.raises(PrepareResumeBlockedError, match="input digest"):
        prepare_resume(store, run_id, candidate)


def test_prepare_resume_rejects_output_goal_change(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_production_run(store)
    stored = store.load_resolved_config(run_id)
    candidate = copy.deepcopy(stored)
    run_section = dict(candidate.get("run") or {})
    run_section["output_goal"] = "Different goal."
    candidate["run"] = run_section

    with pytest.raises(PrepareResumeBlockedError, match="output-goal digest"):
        prepare_resume(store, run_id, candidate)


def test_prepare_resume_rejects_workspace_change(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_production_run(store)
    stored = store.load_resolved_config(run_id)
    candidate = copy.deepcopy(stored)
    project = dict(candidate.get("project") or {})
    project["workspace"] = str((tmp_path / "other-workspace").resolve())
    candidate["project"] = project

    with pytest.raises(PrepareResumeBlockedError, match="workspace change blocked"):
        prepare_resume(store, run_id, candidate)


def test_prepare_resume_rejects_context_change(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    resource = tmp_path / "context-resource.txt"
    resource.write_text("version-1\n", encoding="utf-8")
    config = minimal_resolved_config(
        agent_context={
            "default": {"resources": [], "skills": [], "guidance": []},
            "roles": {
                "planner": {"resources": [], "skills": [], "guidance": []},
                "producer": {
                    "resources": ["context-resource.txt"],
                    "skills": [],
                    "guidance": [],
                },
                "reviewer": {"resources": [], "skills": [], "guidance": []},
            },
        },
    )
    run_id = "run-20260101T001401-001401"
    store.create_run(
        run_id,
        plan=_sample_plan(),
        phase=PRODUCTION,
        **create_run_kwargs(store.root, resolved_config=config),
    )
    store.save_review(run_id, whole_plan_approval_record(store, run_id))
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["status"] = "running"
    run["revision"] = expected_revision + 1
    store.save_run(run_id, run, expected_revision)

    resource.write_text("version-2\n", encoding="utf-8")
    stored = store.load_resolved_config(run_id)

    with pytest.raises(PrepareResumeBlockedError, match="context"):
        prepare_resume(store, run_id, stored)


def test_prepare_resume_rejects_review_policy_change(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "base.yaml",
        "run:\n  output_goal: Goal.\nreview:\n  revise_at: suggestion\n",
    )
    stored = resolve_config(config_path)
    stored = copy.deepcopy(stored)
    stored["project"]["workspace"] = str(tmp_path.resolve())
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T001301-001301"
    store.create_run(
        run_id,
        plan=_sample_plan(),
        phase=PRODUCTION,
        **create_run_kwargs(tmp_path, resolved_config=stored),
    )
    store.save_review(run_id, whole_plan_approval_record(store, run_id))
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["status"] = "running"
    run["revision"] = expected_revision + 1
    store.save_run(run_id, run, expected_revision)

    candidate = resolve_config(config_path, ["review.revise_at=blocker"])
    candidate = copy.deepcopy(candidate)
    candidate["project"]["workspace"] = str(tmp_path.resolve())
    with pytest.raises(PrepareResumeBlockedError, match="config_contract"):
        prepare_resume(store, run_id, candidate)


def test_prepare_resume_conflicting_review_loops(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_production_run(store)
    stored = store.load_resolved_config(run_id)
    store.save_review(
        run_id,
        {
            "id": "review-loop-a",
            "type": "whole_plan",
            "revise_at": "blocker",
            "target_revision": 0,
            "scope": {"kind": "whole_plan"},
            "status": "pending",
            "findings": [],
            "revision_cycles": 0,
            "lifecycle_status": "review_pending",
            "scope_review_rounds": 0,
        },
    )
    store.save_review(
        run_id,
        {
            "id": "review-loop-b",
            "type": "focused_output",
            "revise_at": "blocker",
            "target_revision": 0,
            "scope": {"kind": "focused_output", "item_ids": ["item-root"]},
            "status": "pending",
            "findings": [],
            "revision_cycles": 0,
            "lifecycle_status": "review_pending",
            "scope_review_rounds": 0,
        },
    )

    with pytest.raises(PrepareResumeBlockedError, match="conflicting active review loops"):
        prepare_resume(store, run_id, stored)


def test_prepare_resume_rejects_failed_run(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_production_run(store)
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["status"] = "failed"
    run["revision"] = expected_revision + 1
    run["stop"] = {
        "code": "orchestrator_invariant_failure",
        "category": "invariant",
        "phase": PRODUCTION,
        "message": "invariant failure",
        "details": {},
    }
    store.save_run(run_id, run, expected_revision)
    stored = store.load_resolved_config(run_id)

    with pytest.raises(PrepareResumeBlockedError) as exc_info:
        prepare_resume(store, run_id, stored)
    assert exc_info.value.code == "failed_run_not_resumable"


def test_prepare_resume_performs_no_writes(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_production_run(store)
    run_dir = store.run_dir(run_id)
    before = _run_dir_digest(run_dir)
    stored = store.load_resolved_config(run_id)
    candidate = copy.deepcopy(stored)
    candidate["limits"] = copy.deepcopy(stored["limits"])
    candidate["limits"]["production"] = copy.deepcopy(
        stored["limits"]["production"]
    )
    candidate["limits"]["production"]["max_batches"] = 99

    plan = prepare_resume(store, run_id, candidate)
    after = _run_dir_digest(run_dir)

    assert before == after
    assert plan.state_transition is not None
    assert plan.config_changes


def test_prepare_resume_failed_preparation_leaves_files_unchanged(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_production_run(store)
    run_dir = store.run_dir(run_id)
    before = _run_dir_digest(run_dir)
    stored = store.load_resolved_config(run_id)
    candidate = copy.deepcopy(stored)
    candidate["run"] = {
        **dict(stored.get("run") or {}),
        "output_goal": "Mutated goal.",
    }

    with pytest.raises(PrepareResumeBlockedError):
        prepare_resume(store, run_id, candidate)
    assert _run_dir_digest(run_dir) == before


def test_prepare_resume_paused_limit_increase_success(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_production_run(store, status="paused")
    stored = store.load_resolved_config(run_id)
    candidate = copy.deepcopy(stored)
    candidate["limits"] = copy.deepcopy(stored["limits"])
    candidate["limits"]["production"] = copy.deepcopy(
        stored["limits"]["production"]
    )
    candidate["limits"]["production"]["max_batches"] = 99

    plan = prepare_resume(store, run_id, candidate)

    assert plan.expected_run_revision == int(store.load_run(run_id)["revision"])
    assert plan.state_transition is not None
    assert plan.state_transition.from_status == "paused"
    assert plan.state_transition.to_status == "running"
    assert plan.state_transition.prior_stop_code == "limit_exhausted"
    assert "limits.production.max_batches" in plan.config_changes
    assert plan.validation.contract_digest_valid is True


def test_prepare_resume_running_continuation(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_production_run(store, status="running")
    stored = store.load_resolved_config(run_id)

    plan = prepare_resume(store, run_id, stored)

    assert plan.state_transition is not None
    assert plan.state_transition.from_status == "running"
    assert plan.state_transition.to_status == "running"


def test_prepare_resume_completed_returns_informational_plan(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_production_run(store)
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["status"] = "completed"
    run["outcome"] = "success"
    run["stop"] = None
    run["revision"] = expected_revision + 1
    store.save_run(run_id, run, expected_revision)
    stored = store.load_resolved_config(run_id)

    plan = prepare_resume(store, run_id, stored)

    assert plan.already_completed is True
    assert plan.state_transition is None
    assert plan.message == "run already completed"


def test_prepare_resume_planning_paused_without_approval(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_production_run(store, status="paused", phase=PLANNING)
    stored = store.load_resolved_config(run_id)
    candidate = copy.deepcopy(stored)
    candidate["limits"] = copy.deepcopy(stored["limits"])
    candidate["limits"]["planning"] = copy.deepcopy(stored["limits"]["planning"])
    candidate["limits"]["planning"]["max_agent_turns"] = 99

    plan = prepare_resume(
        store,
        run_id,
        candidate,
        consumed_limits={"limits.planning.max_agent_turns": 1},
    )

    assert plan.state_transition is not None
    assert plan.state_transition.from_status == "paused"
    assert plan.state_transition.to_status == "running"


def test_prepare_resume_blocks_gate_turn_limit_without_increase(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T002101-002101"
    store.create_run(
        run_id,
        plan=_sample_plan(),
        phase=WHOLE_PLAN_REVIEW,
        **create_run_kwargs(store.root),
    )
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        status="pending",
        lifecycle_status="review_pending",
        gate_agent_turns=2,
        target_revision=0,
        scope={"kind": "whole_plan"},
        revise_at="blocker",
    )
    store.save_review(run_id, loop.to_dict())
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["status"] = "paused"
    run["stop"] = {
        "code": "limit_exhausted",
        "category": "operational",
        "phase": WHOLE_PLAN_REVIEW,
        "message": "gate turns exhausted",
        "details": {
            "limit": "limits.review.max_agent_turns_per_gate",
            "consumed": 2,
            "configured": 2,
            "loop_id": loop.id,
        },
    }
    store.save_run(run_id, run, expected_revision)
    stored = store.load_resolved_config(run_id)
    candidate = copy.deepcopy(stored)
    candidate.setdefault("limits", {})
    candidate["limits"].setdefault("review", {})
    candidate["limits"]["review"]["max_agent_turns_per_gate"] = 2
    with pytest.raises(PrepareResumeBlockedError, match="max_agent_turns_per_gate"):
        prepare_resume(store, run_id, candidate)


def test_prepare_resume_blocks_replacement_exhausted_for_phase_action(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_production_run(store, status="paused")
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["phase_action_id"] = "action-replacement-01"
    run["session_replacement_phase_action_id"] = "action-replacement-01"
    run["stop"] = {
        "code": "provider_unavailable",
        "category": "operational",
        "phase": PRODUCTION,
        "message": "replacement session startup failed",
        "details": {},
    }
    store.save_run(run_id, run, expected_revision)

    stored = store.load_resolved_config(run_id)
    with pytest.raises(PrepareResumeBlockedError, match="replacement already exhausted"):
        prepare_resume(store, run_id, stored)


def test_prepare_resume_blocks_review_incomplete_without_loop_id(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_production_run(store, status="paused")
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["stop"] = {
        "code": "review_incomplete",
        "category": "operational",
        "phase": PRODUCTION,
        "message": "review incomplete",
        "details": {},
    }
    store.save_run(run_id, run, expected_revision)

    stored = store.load_resolved_config(run_id)
    with pytest.raises(PrepareResumeBlockedError, match="loop_id"):
        prepare_resume(store, run_id, stored)


def test_prepare_resume_blocks_provider_turn_failed_without_phase_action_id(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_production_run(store, status="paused")
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["phase_action_id"] = None
    run["stop"] = {
        "code": "provider_turn_failed",
        "category": "operational",
        "phase": PRODUCTION,
        "message": "turn failed",
        "details": {},
    }
    store.save_run(run_id, run, expected_revision)

    stored = store.load_resolved_config(run_id)
    with pytest.raises(PrepareResumeBlockedError, match="phase_action_id"):
        prepare_resume(store, run_id, stored)
