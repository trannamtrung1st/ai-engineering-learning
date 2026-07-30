"""Unit tests for agent production snapshot/apply/check tool."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from top_down_planning.agent_tool import (
    ProductionAgentService,
    RequestError,
    RevisionConflictError,
)
from top_down_planning.agent_tool.errors import RoleDeniedError
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator.phases import PRODUCTION
from top_down_planning.persistence import FileRunStore


def _batch_apply_request(
    *,
    plan_items: list[str],
    dispositions: dict,
    production_revision: int = 0,
) -> dict:
    return {
        "production_revision": production_revision,
        "plan_items": plan_items,
        "dispositions": dispositions,
        "outputs": [],
        "contributions": [],
        "summary": "batch complete",
    }


def _create_production_run(
    store: FileRunStore,
    run_id: str = "run-production",
) -> None:
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
    )
    first = PlanItem(
        id="item-first",
        parent_id="item-root",
        order_key="0000000000",
        title="First",
        outcome="First outcome.",
    )
    second = PlanItem(
        id="item-second",
        parent_id="item-root",
        order_key="0000000100",
        title="Second",
        outcome="Second outcome.",
        depends_on=["item-first"],
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver the feature.",
        items={
            "item-root": root,
            "item-first": first,
            "item-second": second,
        },
    )
    config = {
        "run": {
            "output_goal": "Deliver the feature.",
            "input_refs": ["README.md"],
        },
        "planning": {
            "stop_hint": "Stop when ready.",
            "max_depth": 4,
            "max_expansion_per_item": 7,
        },
        "limits": {
            "production": {
                "max_batches": 50,
                "max_agent_turns_per_batch": 10,
            }
        },
        "provider": {"name": "stub"},
    }
    store.create_run(
        run_id,
        plan=plan,
        resolved_config=config,
        input_digest="input-a",
        output_goal_digest="goal-b",
        phase=PRODUCTION,
    )
    store.save_review(
        run_id,
        {
            "id": "review-whole-plan-01",
            "type": "whole_plan",
            "reviewer_session_id": "stub-session-reviewer",
            "target_revision": 0,
            "scope": {"kind": "whole_plan"},
            "status": "approved",
            "findings": [],
            "revision_cycles": 0,
        },
    )


def test_apply_requires_production_revision(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_production_run(store)
    service = ProductionAgentService(store, "run-production")

    with pytest.raises(RequestError, match="production_revision"):
        service.apply(
            {
                "plan_items": ["item-first"],
                "dispositions": {"item-first": {"disposition": "completed"}},
            },
            role="producer",
        )


def test_producer_can_record_batch_via_service(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_production_run(store)
    service = ProductionAgentService(store, "run-production")

    result = service.apply(
        _batch_apply_request(
            plan_items=["item-first"],
            dispositions={"item-first": {"disposition": "completed"}},
        ),
        role="producer",
    )

    assert result["ok"] is True
    assert result["production_revision"] == 1
    production = store.load_production("run-production")
    assert production["dispositions"]["item-first"] == "completed"


def test_stale_production_revision_apply_fails(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_production_run(store)
    service = ProductionAgentService(store, "run-production")

    with pytest.raises(RevisionConflictError) as exc_info:
        service.apply(
            _batch_apply_request(
                plan_items=["item-first"],
                dispositions={"item-first": {"disposition": "completed"}},
                production_revision=5,
            ),
            role="producer",
        )

    assert exc_info.value.action is not None
    assert "production snapshot" in exc_info.value.action.lower()


def test_reviewer_role_denied_for_production_apply(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_production_run(store)
    service = ProductionAgentService(store, "run-production")

    with pytest.raises(RoleDeniedError):
        service.apply(
            _batch_apply_request(
                plan_items=["item-first"],
                dispositions={"item-first": {"disposition": "completed"}},
            ),
            role="reviewer",
        )


def test_submit_completion_rejected_when_items_remain_open(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_production_run(store)
    service = ProductionAgentService(store, "run-production")

    with pytest.raises(RequestError, match="every applicable item"):
        service.submit_completion(
            {"goal_assessment": "Goal is met."},
            role="producer",
        )


def test_submit_completion_success_does_not_set_outcome(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_production_run(store)
    service = ProductionAgentService(store, "run-production")

    service.apply(
        _batch_apply_request(
            plan_items=["item-first"],
            dispositions={"item-first": {"disposition": "completed"}},
        ),
        role="producer",
    )
    service.apply(
        _batch_apply_request(
            plan_items=["item-second"],
            dispositions={"item-second": {"disposition": "completed"}},
            production_revision=1,
        ),
        role="producer",
    )

    result = service.submit_completion(
        {"goal_assessment": "Output goal is fully met."},
        role="producer",
    )

    assert result["ok"] is True
    assert result["run_outcome"] is None
    run = store.load_run("run-production")
    assert run["outcome"] is None
    production = store.load_production("run-production")
    assert production["completion_claim"]["goal_assessment"] == "Output goal is fully met."


def test_request_amendment_persists_pending_request(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_production_run(store)
    service = ProductionAgentService(store, "run-production")

    result = service.request_amendment(
        {
            "evidence": "Missing API branch in approved plan.",
            "affected_refs": ["item-root"],
            "summary": "Need API subtree.",
        },
        role="producer",
    )

    assert result["ok"] is True
    assert result["signal"] == "amendment_requested"
    production = store.load_production("run-production")
    assert production["pending_amendment_id"] == "amendment-01"
    assert production["amendment_requests"][0]["status"] == "pending"


def test_report_blocked_persists_blocker_without_outcome(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_production_run(store)
    service = ProductionAgentService(store, "run-production")

    result = service.report_blocked(
        {
            "evidence": "Upstream service unavailable.",
            "affected_refs": ["item-first"],
            "summary": "Cannot proceed.",
        },
        role="producer",
    )

    assert result["ok"] is True
    assert result["run_outcome"] is None
    production = store.load_production("run-production")
    assert production["blocker_report"]["evidence"] == "Upstream service unavailable."


def test_production_check_reports_open_items(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_production_run(store)
    service = ProductionAgentService(store, "run-production")

    result = service.check()

    assert result["ok"] is False
    assert result["all_applicable_items_processed"] is False
    assert any("remain without terminal disposition" in issue for issue in result["issues"])


def test_cli_production_apply_and_submit_completion(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_production_run(store)

    first_request = _batch_apply_request(
        plan_items=["item-first"],
        dispositions={"item-first": {"disposition": "completed"}},
    )
    first_path = tmp_path / "batch-first.json"
    first_path.write_text(json.dumps(first_request), encoding="utf-8")

    first_apply = subprocess.run(
        [
            sys.executable,
            "-m",
            "top_down_planning.cli.main",
            "agent",
            "production",
            "apply",
            "--run",
            "run-production",
            "--runs-dir",
            str(tmp_path),
            "--request",
            str(first_path),
            "--role",
            "producer",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert first_apply.returncode == 0, first_apply.stderr
    first_payload = json.loads(first_apply.stdout)
    assert first_payload["ok"] is True

    second_request = _batch_apply_request(
        plan_items=["item-second"],
        dispositions={"item-second": {"disposition": "completed"}},
        production_revision=first_payload["production_revision"],
    )
    second_path = tmp_path / "batch-second.json"
    second_path.write_text(json.dumps(second_request), encoding="utf-8")

    second_apply = subprocess.run(
        [
            sys.executable,
            "-m",
            "top_down_planning.cli.main",
            "agent",
            "production",
            "apply",
            "--run",
            "run-production",
            "--runs-dir",
            str(tmp_path),
            "--request",
            str(second_path),
            "--role",
            "producer",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert second_apply.returncode == 0, second_apply.stderr

    completion_path = tmp_path / "completion.json"
    completion_path.write_text(
        json.dumps({"goal_assessment": "Delivered the feature."}),
        encoding="utf-8",
    )
    completion = subprocess.run(
        [
            sys.executable,
            "-m",
            "top_down_planning.cli.main",
            "agent",
            "production",
            "submit-completion",
            "--run",
            "run-production",
            "--runs-dir",
            str(tmp_path),
            "--request",
            str(completion_path),
            "--role",
            "producer",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completion.returncode == 0, completion.stderr
    completion_payload = json.loads(completion.stdout)
    assert completion_payload["ok"] is True
    assert completion_payload["run_outcome"] is None


def test_cli_reviewer_denied_for_production_apply(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_production_run(store)

    request_path = tmp_path / "apply.json"
    request_path.write_text(
        json.dumps(
            _batch_apply_request(
                plan_items=["item-first"],
                dispositions={"item-first": {"disposition": "completed"}},
            )
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "top_down_planning.cli.main",
            "agent",
            "production",
            "apply",
            "--run",
            "run-production",
            "--runs-dir",
            str(tmp_path),
            "--request",
            str(request_path),
            "--role",
            "reviewer",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "role_denied"
