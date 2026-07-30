"""Unit tests for agent plan snapshot/apply/check tool."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from top_down_planning.agent_tool import PlanAgentService, RequestError, RevisionConflictError
from top_down_planning.agent_tool.errors import RoleDeniedError
from top_down_planning.cli.main import main
from top_down_planning.domain.models import Plan, PlanItem, Scope
from top_down_planning.persistence import FileRunStore
from tests.conftest import run_cli
from tests.helpers import run_digests_for_config, whole_plan_approval_record


def _sample_plan(revision: int = 0) -> Plan:
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
    )
    child = PlanItem(
        id="item-child",
        parent_id="item-root",
        order_key="0000000000",
        title="Child",
        depends_on=["item-root"],
    )
    return Plan(
        id="plan-001",
        revision=revision,
        output_goal="Deliver the output.",
        items={"item-root": root, "item-child": child},
    )


def _create_run(store: FileRunStore, run_id: str = "run-001", *, revision: int = 0) -> None:
    plan = _sample_plan(revision=revision)
    config = {
        "run": {"output_goal": "Deliver the output.", "input_refs": []},
        "planning": {"max_depth": 4, "max_expansion_per_item": 7},
    }
    input_digest, output_goal_digest = run_digests_for_config(store.root, config)
    store.create_run(
        run_id,
        plan=plan,
        resolved_config=config,
        input_digest=input_digest,
        output_goal_digest=output_goal_digest,
        workspace=str(store.root),
    )


def test_apply_persists_multi_op_transaction(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)

    service = PlanAgentService(store, "run-001")
    result = service.apply(
        {
            "base_revision": 0,
            "operations": [
                {
                    "op": "add_item",
                    "temp_id": "item-new",
                    "parent_id": "item-root",
                    "placement": {"last_child": True},
                    "item": {"title": "API", "outcome": "API exists."},
                },
                {
                    "op": "add_dependency",
                    "item_id": "item-child",
                    "depends_on": "item-new",
                },
            ],
        },
        role="planner",
    )

    assert result["ok"] is True
    assert result["revision"] == 1
    assert "item-new" in result["id_map"]
    new_id = result["id_map"]["item-new"]

    saved = store.load_plan_model("run-001")
    assert saved.revision == 1
    assert new_id in saved.items
    assert new_id in saved.items["item-child"].depends_on

    events = store.load_events("run-001")
    assert any(event["type"] == "plan_applied" for event in events)


def test_stale_revision_apply_fails_with_snapshot_instruction(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    service = PlanAgentService(store, "run-001")

    with pytest.raises(RevisionConflictError) as exc_info:
        service.apply(
            {
                "base_revision": 99,
                "operations": [
                    {
                        "op": "update_item",
                        "item_id": "item-root",
                        "patch": {"title": "Updated"},
                    }
                ],
            },
            role="planner",
        )

    assert exc_info.value.action is not None
    assert "snapshot" in exc_info.value.action.lower()


def test_snapshot_ready_view_reflects_dependency_readiness(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    service = PlanAgentService(store, "run-001")

    ready = service.snapshot(view="ready")
    assert ready["ok"] is True
    assert "item-child" not in ready["ready_item_ids"]
    assert "item-child" in ready["not_ready"]


def test_plan_check_matches_validator_modes(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    service = PlanAgentService(store, "run-001")

    draft = service.check(mode="draft")
    approval = service.check(mode="approval")

    assert draft["ok"] is True
    assert approval["ok"] is False
    assert draft["mode"] == "draft"
    assert approval["mode"] == "approval"


def test_apply_requires_role(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    service = PlanAgentService(store, "run-001")

    with pytest.raises(RequestError, match="requires role"):
        service.apply(
            {
                "base_revision": 0,
                "operations": [
                    {
                        "op": "update_item",
                        "item_id": "item-root",
                        "patch": {"title": "Missing role"},
                    }
                ],
            },
            role="",
        )


def test_producer_role_denied_for_apply(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    service = PlanAgentService(store, "run-001")

    with pytest.raises(RoleDeniedError):
        service.apply(
            {
                "base_revision": 0,
                "operations": [
                    {
                        "op": "update_item",
                        "item_id": "item-root",
                        "patch": {"title": "Nope"},
                    }
                ],
            },
            role="producer",
        )


def test_cli_plan_commands_smoke(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)

    request = {
        "base_revision": 0,
        "operations": [
            {
                "op": "add_item",
                "temp_id": "item-api",
                "parent_id": "item-root",
                "placement": {"last_child": True},
                "item": {"title": "API"},
            }
        ],
    }
    request_path = tmp_path / "apply.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")

    apply = run_cli(
        [
            "agent",
            "plan",
            "apply",
            "--run",
            "run-001",
            "--runs-dir",
            str(tmp_path),
            "--request",
            str(request_path),
            "--role",
            "planner",
        ]
    )
    assert apply.exit_code == 0, apply.stderr
    apply_payload = apply.json()
    assert apply_payload["ok"] is True
    assert apply_payload["revision"] == 1

    snapshot = run_cli(
        [
            "agent",
            "plan",
            "snapshot",
            "--run",
            "run-001",
            "--runs-dir",
            str(tmp_path),
            "--view",
            "ready",
        ]
    )
    assert snapshot.exit_code == 0, snapshot.stderr
    snapshot_payload = snapshot.json()
    assert snapshot_payload["view"] == "ready"
    assert "planning_budget" not in snapshot_payload
    assert "ready_item_ids" in snapshot_payload

    status = run_cli(
        [
            "agent",
            "run",
            "status",
            "--run",
            "run-001",
            "--runs-dir",
            str(tmp_path),
        ]
    )
    assert status.exit_code == 0, status.stderr
    status_payload = status.json()
    assert status_payload["ok"] is True
    assert status_payload["run"]["phase"] == "planning"
    assert status_payload["run"]["plan_revision"] == 1


def test_cli_stale_revision_returns_actionable_error(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)

    request_path = tmp_path / "stale.json"
    request_path.write_text(
        json.dumps(
            {
                "base_revision": 5,
                "operations": [
                    {
                        "op": "update_item",
                        "item_id": "item-root",
                        "patch": {"title": "Stale"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = run_cli(
        [
            "agent",
            "plan",
            "apply",
            "--run",
            "run-001",
            "--runs-dir",
            str(tmp_path),
            "--request",
            str(request_path),
            "--role",
            "planner",
        ]
    )
    assert result.exit_code == 1
    payload = result.json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "revision_conflict"
    assert "snapshot" in payload["error"]["action"].lower()


def test_main_help_still_works() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0


def test_apply_returns_post_mutation_validation_issues(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    gate = PlanItem("item-gate", None, "0000000000", "Gate")
    worker = PlanItem(
        "item-worker",
        None,
        "0000000100",
        "Worker",
        depends_on=["item-gate"],
    )
    plan = Plan(
        id="plan-001",
        revision=0,
        output_goal="Deliver the output.",
        items={"item-gate": gate, "item-worker": worker},
    )
    store.create_run(
        "run-001",
        plan=plan,
        resolved_config={"planning": {"max_depth": 4, "max_expansion_per_item": 7}},
        input_digest="input-a",
        output_goal_digest="goal-b",
        production={"dispositions": {"item-gate": "blocked"}, "revision": 0},
        workspace=str(store.root),
    )

    service = PlanAgentService(store, "run-001")
    result = service.apply(
        {
            "base_revision": 0,
            "operations": [
                {
                    "op": "update_item",
                    "item_id": "item-worker",
                    "patch": {"title": "Worker updated"},
                }
            ],
        },
        role="planner",
    )

    assert result["ok"] is False
    assert result["applied"] is True
    assert any(issue["code"] == "dependency_deadlock" for issue in result["issues"])


def test_cli_plan_apply_exits_nonzero_when_validation_fails(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    gate = PlanItem("item-gate", None, "0000000000", "Gate")
    worker = PlanItem(
        "item-worker",
        None,
        "0000000100",
        "Worker",
        depends_on=["item-gate"],
    )
    plan = Plan(
        id="plan-001",
        revision=0,
        output_goal="Deliver the output.",
        items={"item-gate": gate, "item-worker": worker},
    )
    store.create_run(
        "run-001",
        plan=plan,
        resolved_config={"planning": {"max_depth": 4, "max_expansion_per_item": 7}},
        input_digest="input-a",
        output_goal_digest="goal-b",
        production={"dispositions": {"item-gate": "blocked"}, "revision": 0},
        workspace=str(store.root),
    )

    request_path = tmp_path / "apply.json"
    request_path.write_text(
        json.dumps(
            {
                "base_revision": 0,
                "operations": [
                    {
                        "op": "update_item",
                        "item_id": "item-worker",
                        "patch": {"title": "Worker updated"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = run_cli(
        [
            "agent",
            "plan",
            "apply",
            "--run",
            "run-001",
            "--runs-dir",
            str(tmp_path),
            "--request",
            str(request_path),
            "--role",
            "planner",
        ]
    )

    assert result.exit_code == 1
    payload = result.json()
    assert payload["applied"] is True
    assert payload["ok"] is False


def test_snapshot_ready_excludes_review_blocked_items(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    store.save_review(
        "run-001",
        {
            "id": "review-focused-plan-01",
            "type": "focused_plan",
            "reviewer_session_id": "session-1",
            "target_revision": 0,
            "scope": {"kind": "focused_plan", "item_ids": ["item-child"]},
            "status": "changes_requested",
            "findings": [
                {
                    "id": "finding-01",
                    "importance": "blocking",
                    "target_refs": ["item-child"],
                    "issue": "Needs more detail.",
                    "required_change": "Expand acceptance.",
                    "status": "unresolved",
                }
            ],
            "revision_cycles": 0,
        },
    )

    service = PlanAgentService(store, "run-001")
    ready = service.snapshot(view="ready")

    assert ready["ok"] is True
    assert "item-child" not in ready["ready_item_ids"]
    assert ready["not_ready"]["item-child"]["reason"] == "review_blocked"


def test_snapshot_tree_includes_scope_boundaries_acceptance(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        scope=Scope(includes=["auth"], excludes=["billing"]),
        boundaries=["No external APIs"],
        acceptance=["Login works"],
    )
    plan = Plan(
        id="plan-001",
        revision=0,
        output_goal="Deliver the output.",
        items={"item-root": root},
    )
    store.create_run(
        "run-001",
        plan=plan,
        resolved_config={"planning": {"max_depth": 4, "max_expansion_per_item": 7}},
        input_digest="input-a",
        output_goal_digest="goal-b",
        workspace=str(store.root),
    )

    service = PlanAgentService(store, "run-001")
    snapshot = service.snapshot(view="tree")

    item = snapshot["items"][0]
    assert item["scope"] == {"includes": ["auth"], "excludes": ["billing"]}
    assert item["boundaries"] == ["No external APIs"]
    assert item["acceptance"] == ["Login works"]


def test_plan_check_approval_without_binding_surfaces_not_checked_warnings(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    service = PlanAgentService(store, "run-001")

    approval = service.check(mode="approval")

    assert approval["ok"] is False
    assert any(
        "approved revision was not provided" in issue["message"]
        for issue in approval["issues"]
        if issue["severity"] == "error"
    )
    assert any(
        issue["code"] == "digest_not_checked" and issue["severity"] == "error"
        for issue in approval["issues"]
    )


def test_plan_check_approval_mode_runs_review_and_digest_hooks(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    store.save_review(
        "run-001",
        whole_plan_approval_record(
            store,
            "run-001",
            reviewer_session_id="session-1",
        ),
    )

    service = PlanAgentService(store, "run-001")
    draft = service.check(mode="draft")
    approval = service.check(mode="approval")

    assert draft["ok"] is True
    assert approval["ok"] is True

    review = store.load_review("run-001", "review-whole-plan-01")
    review = dict(review)
    review["approved_digests"] = dict(review["approved_digests"])
    review["approved_digests"]["plan"] = "stale-plan-digest"
    store.save_review("run-001", review)

    approval_after_tamper = service.check(mode="approval")
    assert approval_after_tamper["ok"] is False
    assert any(
        issue["code"] == "digest_mismatch" for issue in approval_after_tamper["issues"]
    )
