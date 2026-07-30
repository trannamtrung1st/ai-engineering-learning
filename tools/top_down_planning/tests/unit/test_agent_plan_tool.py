"""Unit tests for agent plan snapshot/apply/check tool."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from top_down_planning.agent_tool import PlanAgentService, RequestError, RevisionConflictError
from top_down_planning.agent_tool.errors import RoleDeniedError
from top_down_planning.cli.main import main
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.persistence import FileRunStore


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
    store.create_run(
        run_id,
        plan=plan,
        resolved_config={"planning": {"max_depth": 4, "max_expansion_per_item": 7}},
        input_digest="input-a",
        output_goal_digest="goal-b",
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
    assert approval["ok"] is True
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


def test_cli_apply_and_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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

    apply = subprocess.run(
        [
            sys.executable,
            "-m",
            "top_down_planning.cli.main",
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
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert apply.returncode == 0, apply.stderr
    apply_payload = json.loads(apply.stdout)
    assert apply_payload["ok"] is True
    assert apply_payload["revision"] == 1

    snapshot = subprocess.run(
        [
            sys.executable,
            "-m",
            "top_down_planning.cli.main",
            "agent",
            "plan",
            "snapshot",
            "--run",
            "run-001",
            "--runs-dir",
            str(tmp_path),
            "--view",
            "ready",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert snapshot.returncode == 0, snapshot.stderr
    snapshot_payload = json.loads(snapshot.stdout)
    assert snapshot_payload["view"] == "ready"
    assert "planning_budget" not in snapshot_payload
    assert "ready_item_ids" in snapshot_payload


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

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "top_down_planning.cli.main",
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
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "revision_conflict"
    assert "snapshot" in payload["error"]["action"].lower()


def test_cli_run_status(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "top_down_planning.cli.main",
            "agent",
            "run",
            "status",
            "--run",
            "run-001",
            "--runs-dir",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["run"]["phase"] == "planning"
    assert payload["run"]["plan_revision"] == 0


def test_main_help_still_works() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
