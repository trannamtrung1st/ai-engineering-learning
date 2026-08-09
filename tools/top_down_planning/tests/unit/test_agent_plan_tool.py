"""Unit tests for agent plan snapshot/apply/check tool."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from top_down_planning.agent_tool import PlanAgentService, RevisionConflictError
from top_down_planning.agent_tool.errors import CapabilityDeniedError, OperationError, RequestError
from top_down_planning.cli.main import main
from top_down_planning.domain.models import Plan, PlanItem, Scope
from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.persistence import FileRunStore
from tests.conftest import run_cli
from tests.helpers import (
    create_run_kwargs,
    decorate_sub_tdp_v2_package,
    goal_met_completion_claim,
    grant_capability,
    make_review_loop,
    mirrored_production_batch,
    save_review_payload,
    set_capability_token_file,
    write_agent_request_file,
    whole_plan_approval_record,
)


def _sample_plan(revision: int = 0) -> Plan:
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Deliver the output",
        outcome="Deliver the output.",
        kind="aggregate",
    )
    gate = PlanItem(
        id="item-gate",
        parent_id="item-root",
        order_key="0000000000",
        title="Gate",
        kind="work",
        scope=Scope(includes=["Gate capability"]),
    )
    child = PlanItem(
        id="item-child",
        parent_id="item-root",
        order_key="0000000100",
        title="Child",
        depends_on=["item-gate"],
        kind="work",
        scope=Scope(includes=["Child capability"]),
    )
    return Plan(
        id="plan-001",
        revision=revision,
        output_goal="Deliver the output.",
        items={"item-root": root, "item-gate": gate, "item-child": child},
    )


def _create_run(store: FileRunStore, run_id: str = "run-20260101T000001-000001", *, revision: int = 0) -> None:
    plan = _sample_plan(revision=revision)
    config = {
        "run": {"output_goal": "Deliver the output.", "input_refs": []},
        "planning": {"max_depth": 4, "max_expansion_per_item": 7},
    }
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=config),
    )


def test_apply_persists_multi_op_transaction(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)

    service = PlanAgentService(store, "run-20260101T000001-000001")
    token = grant_capability(store, "run-20260101T000001-000001", role="planner", phase=PLANNING)
    result = service.apply(
        {
            "base_revision": 0,
            "operations": [
                {
                    "op": "add_item",
                    "temp_id": "item-new",
                    "parent_id": "item-root",
                    "placement": {"last_child": True},
                    "item": {"kind": "work", "title": "API", "outcome": "API exists."},
                },
                {
                    "op": "add_dependency",
                    "item_id": "item-child",
                    "depends_on": "item-new",
                },
            ],
        },
        capability_token=token,
    )

    assert result["ok"] is True
    assert result["revision"] == 1
    assert "item-new" in result["id_map"]
    new_id = result["id_map"]["item-new"]

    saved = store.load_plan_model("run-20260101T000001-000001")
    assert saved.revision == 1
    assert new_id in saved.items
    assert new_id in saved.items["item-child"].depends_on

    events = store.load_events("run-20260101T000001-000001")
    assert any(event["type"] == "plan_applied" for event in events)


def test_apply_inline_depends_on_with_temp_id(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)

    service = PlanAgentService(store, "run-20260101T000001-000001")
    token = grant_capability(store, "run-20260101T000001-000001", role="planner", phase=PLANNING)
    result = service.apply(
        {
            "base_revision": 0,
            "operations": [
                {
                    "op": "add_item",
                    "temp_id": "item-api",
                    "parent_id": "item-root",
                    "placement": {"last_child": True},
                    "item": {"kind": "work", "title": "API", "outcome": "API exists."},
                },
                {
                    "op": "add_item",
                    "temp_id": "item-ui",
                    "parent_id": "item-root",
                    "placement": {"last_child": True},
                    "item": {
                        "kind": "work",
                        "title": "UI",
                        "outcome": "UI exists.",
                        "depends_on": "item-api",
                    },
                },
            ],
        },
        capability_token=token,
    )

    api_id = result["id_map"]["item-api"]
    ui_id = result["id_map"]["item-ui"]
    saved = store.load_plan_model("run-20260101T000001-000001")
    assert saved.items[ui_id].depends_on == [api_id]


def test_apply_unknown_dependency_includes_hint(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)

    service = PlanAgentService(store, "run-20260101T000001-000001")
    token = grant_capability(store, "run-20260101T000001-000001", role="planner", phase=PLANNING)
    with pytest.raises(OperationError) as exc_info:
        service.apply(
            {
                "base_revision": 0,
                "operations": [
                    {
                        "op": "add_item",
                        "temp_id": "item-ui",
                        "parent_id": "item-root",
                        "placement": {"last_child": True},
                        "item": {
                            "kind": "work",
                            "title": "UI",
                            "outcome": "UI exists.",
                            "depends_on": ["item-missing"],
                        },
                    },
                ],
            },
            capability_token=token,
        )

    assert exc_info.value.hint is not None
    assert "expand-branch" in exc_info.value.hint


def test_stale_revision_apply_fails_with_snapshot_instruction(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    service = PlanAgentService(store, "run-20260101T000001-000001")
    token = grant_capability(store, "run-20260101T000001-000001", role="planner", phase=PLANNING)

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
            capability_token=token,
        )

    assert exc_info.value.action is not None
    assert "snapshot" in exc_info.value.action.lower()


def test_snapshot_ready_view_reflects_dependency_readiness(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    service = PlanAgentService(store, "run-20260101T000001-000001")

    ready = service.snapshot(view="ready")
    assert ready["ok"] is True
    assert "item-child" not in ready["ready_item_ids"]
    assert "item-child" in ready["not_ready"]


def test_snapshot_active_and_audit_views(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    plan = Plan(
        id="plan-views",
        revision=0,
        output_goal="Deliver the output.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="Deliver the output",
                outcome="Deliver the output.",
                kind="aggregate",
            ),
            "item-live": PlanItem(
                id="item-live",
                parent_id="item-root",
                order_key="0000000000",
                title="Live",
                kind="work",
            ),
            "item-old": PlanItem(
                id="item-old",
                parent_id="item-root",
                order_key="0000000100",
                title="Old",
                kind="work",
                planning_status="superseded",
                superseded_by="item-live",
            ),
            "item-gone": PlanItem(
                id="item-gone",
                parent_id="item-root",
                order_key="0000000200",
                title="Gone",
                kind="work",
                planning_status="removed",
            ),
        },
    )
    store.create_run(
        "run-20260101T000001-000001",
        plan=plan,
        **create_run_kwargs(
            store.root,
            resolved_config={
                "run": {"output_goal": "Deliver the output.", "input_refs": []},
                "planning": {"max_depth": 4, "max_expansion_per_item": 7},
            },
        ),
    )
    service = PlanAgentService(store, "run-20260101T000001-000001")

    active = service.snapshot(view="active")
    assert active["view"] == "active"
    assert active["revision"] == 0
    active_ids = [item["id"] for item in active["items"]]
    assert active_ids == ["item-root", "item-live"]
    assert "item-old" not in active_ids
    assert "item-gone" not in active_ids
    assert all(item["planning_status"] == "open" for item in active["items"])
    assert all("superseded_by" not in item for item in active["items"])

    audit = service.snapshot(view="audit")
    assert audit["view"] == "audit"
    assert audit["revision"] == 0
    audit_ids = [item["id"] for item in audit["items"]]
    assert audit_ids[:2] == ["item-root", "item-live"]
    assert "item-gone" in audit_ids
    assert "item-old" in audit_ids
    old = next(item for item in audit["items"] if item["id"] == "item-old")
    assert old["planning_status"] == "superseded"
    assert old["superseded_by"] == "item-live"
    gone = next(item for item in audit["items"] if item["id"] == "item-gone")
    assert gone["planning_status"] == "removed"
    assert "superseded_by" not in gone


def test_audit_view_includes_nested_inactive_under_root_filter(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    plan = Plan(
        id="plan-audit-nested",
        revision=0,
        output_goal="Deliver the output.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="Deliver the output",
                outcome="Deliver the output.",
                kind="aggregate",
            ),
            "item-live": PlanItem(
                id="item-live",
                parent_id="item-root",
                order_key="0000000000",
                title="Live",
                kind="work",
            ),
            "item-dead-parent": PlanItem(
                id="item-dead-parent",
                parent_id="item-root",
                order_key="0000000100",
                title="Dead parent",
                kind="work",
                planning_status="removed",
            ),
            "item-dead-child": PlanItem(
                id="item-dead-child",
                parent_id="item-dead-parent",
                order_key="0000000000",
                title="Dead child",
                kind="work",
                planning_status="removed",
            ),
        },
    )
    store.create_run(
        "run-20260101T000001-000001",
        plan=plan,
        **create_run_kwargs(
            store.root,
            resolved_config={
                "run": {"output_goal": "Deliver the output.", "input_refs": []},
                "planning": {"max_depth": 4, "max_expansion_per_item": 7},
            },
        ),
    )
    service = PlanAgentService(store, "run-20260101T000001-000001")

    audit = service.snapshot(view="audit", root_id="item-root")
    audit_ids = [item["id"] for item in audit["items"]]
    assert audit_ids[:2] == ["item-root", "item-live"]
    assert "item-dead-parent" in audit_ids
    assert "item-dead-child" in audit_ids


def test_plan_snapshot_defaults_to_active_view(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    service = PlanAgentService(store, "run-20260101T000001-000001")

    snapshot = service.snapshot()
    assert snapshot["view"] == "active"


def test_whole_plan_and_producer_packages_remain_active_only(tmp_path: Path) -> None:
    """walk_active_tree already filters packages; assert inactive history stays out."""

    from top_down_planning.agent_tool.views import build_plan_review_snapshot
    from top_down_planning.domain.models import PlanningLimits
    from top_down_planning.domain.production import build_compact_approved_plan
    from top_down_planning.domain.reviews import ReviewLoop
    from top_down_planning.orchestrator.production import build_producer_context_manifest
    from top_down_planning.orchestrator.whole_plan_review import (
        build_whole_plan_review_package,
    )
    from tests.helpers import minimal_resolved_config

    plan = Plan(
        id="plan-active-only",
        revision=2,
        output_goal="Deliver the output.",
        risks=["Plan-level risk."],
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="Deliver the output",
                outcome="Deliver the output.",
                kind="aggregate",
            ),
            "item-live": PlanItem(
                id="item-live",
                parent_id="item-root",
                order_key="0000000000",
                title="Live",
                kind="work",
                outcome="Live outcome.",
                risks=["Item-level risk."],
                source_refs=["spec.md → Live section"],
                scope=Scope(includes=["Live capability"]),
            ),
            "item-old": PlanItem(
                id="item-old",
                parent_id="item-root",
                order_key="0000000100",
                title="Old",
                kind="work",
                planning_status="superseded",
                superseded_by="item-live",
            ),
            "item-gone": PlanItem(
                id="item-gone",
                parent_id="item-root",
                order_key="0000000200",
                title="Gone",
                kind="work",
                planning_status="removed",
            ),
        },
    )
    inactive_ids = {"item-old", "item-gone"}

    approved = build_compact_approved_plan(plan)
    approved_ids = {item["id"] for item in approved["items"]}
    assert approved_ids == {"item-root", "item-live"}
    assert approved_ids.isdisjoint(inactive_ids)
    assert approved["risks"] == ["Plan-level risk."]
    live_item = next(item for item in approved["items"] if item["id"] == "item-live")
    assert live_item["risks"] == ["Item-level risk."]
    assert live_item["source_refs"] == ["spec.md → Live section"]
    assert live_item["scope"] == {"includes": ["Live capability"], "excludes": []}
    assert live_item["boundaries"] == []
    assert live_item["effective_scope"] == {
        "includes": ["Live capability"],
        "excludes": [],
    }
    assert live_item["effective_boundaries"] == []

    review_snapshot = build_plan_review_snapshot(plan, limits=PlanningLimits())
    assert review_snapshot["view"] == "active"
    assert review_snapshot["risks"] == ["Plan-level risk."]
    review_ids = {item["id"] for item in review_snapshot["items"]}
    assert review_ids == {"item-root", "item-live"}
    assert review_ids.isdisjoint(inactive_ids)

    config = minimal_resolved_config(
        run={"output_goal": "Deliver the output.", "input_refs": []},
    )
    config["project"]["workspace"] = str(tmp_path.resolve())
    run = {"digests": {}, "workspace": str(tmp_path.resolve())}
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=2,
        scope={"kind": "whole_plan"},
    )
    package = build_whole_plan_review_package(
        "run-20260101T000301-000301",
        run,
        config,
        plan,
        loop,
    )
    package_ids = {item["id"] for item in package["plan"]["items"]}
    assert package_ids == {"item-root", "item-live"}
    assert package_ids.isdisjoint(inactive_ids)

    producer = build_producer_context_manifest(
        "run-20260101T000201-000201",
        run,
        config,
        plan,
    )
    producer_ids = {item["id"] for item in producer["approved_plan"]["items"]}
    assert producer_ids == {"item-root", "item-live"}
    assert producer_ids.isdisjoint(inactive_ids)


def test_plan_check_matches_validator_modes(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    service = PlanAgentService(store, "run-20260101T000001-000001")

    draft = service.check(mode="draft")
    approval = service.check(mode="approval")

    assert draft["ok"] is True
    assert approval["ok"] is False
    assert draft["mode"] == "draft"
    assert approval["mode"] == "approval"


def test_plan_check_surfaces_overlap_warnings_without_blocking(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    plan = Plan(
        id="plan-overlap-check",
        revision=0,
        output_goal="Deliver the output.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="Deliver the output",
                outcome="Deliver the output.",
                kind="aggregate",
            ),
            "item-parent": PlanItem(
                id="item-parent",
                parent_id="item-root",
                order_key="0000000000",
                title="Parent work",
                kind="work",
                outcome="Parent.",
            ),
            "item-child": PlanItem(
                id="item-child",
                parent_id="item-parent",
                order_key="0000000000",
                title="Child work",
                kind="work",
                outcome="Child.",
            ),
        },
    )
    store.create_run(
        "run-20260101T000001-000001",
        plan=plan,
        **create_run_kwargs(
            store.root,
            resolved_config={
                "run": {"output_goal": "Deliver the output.", "input_refs": []},
                "planning": {"max_depth": 4, "max_expansion_per_item": 7},
            },
        ),
    )
    service = PlanAgentService(store, "run-20260101T000001-000001")
    draft = service.check(mode="draft")
    assert draft["ok"] is True
    assert draft["issues"] == []
    assert any(
        "executable descendants" in warning and "item-parent" in warning
        for warning in draft["warnings"]
    )


def test_apply_requires_capability_token(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    service = PlanAgentService(store, "run-20260101T000001-000001")

    with pytest.raises(CapabilityDeniedError, match="capability token"):
        service.apply(
            {
                "base_revision": 0,
                "operations": [
                    {
                        "op": "update_item",
                        "item_id": "item-root",
                        "patch": {"title": "Missing capability"},
                    }
                ],
            },
        )


def test_producer_capability_denied_for_apply(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    service = PlanAgentService(store, "run-20260101T000001-000001")
    token = grant_capability(store, "run-20260101T000001-000001", role="producer", phase=PLANNING)

    with pytest.raises(CapabilityDeniedError):
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
            capability_token=token,
        )


def test_cli_plan_commands_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    set_capability_token_file(
        monkeypatch,
        store,
        "run-20260101T000001-000001",
        grant_capability(store, "run-20260101T000001-000001", role="planner", phase=PLANNING),
    )

    request = {
        "base_revision": 0,
        "operations": [
            {
                "op": "add_item",
                "temp_id": "item-api",
                "parent_id": "item-root",
                "placement": {"last_child": True},
                "item": {"kind": "work", "title": "API"},
            }
        ],
    }
    request_path = write_agent_request_file(
        store, "run-20260101T000001-000001", "apply.json", request
    )

    apply = run_cli(
        [
            "agent",
            "plan",
            "apply",
            "--run",
            "run-20260101T000001-000001",
            "--runs-dir",
            str(tmp_path),
            "--request",
            str(request_path),
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
            "run-20260101T000001-000001",
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
            "run-20260101T000001-000001",
            "--runs-dir",
            str(tmp_path),
        ]
    )
    assert status.exit_code == 0, status.stderr
    status_payload = status.json()
    assert status_payload["ok"] is True
    assert status_payload["run"]["phase"] == "planning"
    assert status_payload["run"]["plan_revision"] == 1


def test_cli_stale_revision_returns_actionable_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    set_capability_token_file(
        monkeypatch,
        store,
        "run-20260101T000001-000001",
        grant_capability(store, "run-20260101T000001-000001", role="planner", phase=PLANNING),
    )

    request_path = write_agent_request_file(
        store,
        "run-20260101T000001-000001",
        "stale.json",
        {
            "base_revision": 5,
            "operations": [
                {
                    "op": "update_item",
                    "item_id": "item-root",
                    "patch": {"title": "Stale"},
                }
            ],
        },
    )

    result = run_cli(
        [
            "agent",
            "plan",
            "apply",
            "--run",
            "run-20260101T000001-000001",
            "--runs-dir",
            str(tmp_path),
            "--request",
            str(request_path),
        ]
    )
    assert result.exit_code == 1
    payload = result.json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "revision_conflict"
    assert "snapshot" in payload["error"]["action"].lower()


def test_cli_unknown_dependency_returns_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    set_capability_token_file(
        monkeypatch,
        store,
        "run-20260101T000001-000001",
        grant_capability(store, "run-20260101T000001-000001", role="planner", phase=PLANNING),
    )

    request_path = write_agent_request_file(
        store,
        "run-20260101T000001-000001",
        "bad-dep.json",
        {
            "base_revision": 0,
            "operations": [
                {
                    "op": "add_item",
                    "temp_id": "item-ui",
                    "parent_id": "item-root",
                    "placement": {"last_child": True},
                    "item": {
                        "kind": "work",
                        "title": "UI",
                        "depends_on": ["item-missing"],
                    },
                },
            ],
        },
    )

    result = run_cli(
        [
            "agent",
            "plan",
            "apply",
            "--run",
            "run-20260101T000001-000001",
            "--runs-dir",
            str(tmp_path),
            "--request",
            str(request_path),
        ]
    )
    assert result.exit_code == 1
    payload = result.json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "operation_error"
    assert "expand-branch" in payload["error"]["hint"]


def test_main_help_still_works() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0


def test_apply_returns_post_mutation_validation_issues_for_pre_existing_errors(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    gate = PlanItem("item-gate", None, "0000000000", "Gate", kind="work")
    worker = PlanItem(
        "item-worker",
        None,
        "0000000100",
        "Worker",
        depends_on=["item-gate"],
        kind="work",
    )
    plan = Plan(
        id="plan-001",
        revision=0,
        output_goal="Deliver the output.",
        items={"item-gate": gate, "item-worker": worker},
    )
    gate_batch = {
        "id": "batch-gate",
        "status": "completed",
        "plan_items": ["item-gate"],
        "result": {
            "outputs": [],
            "contributions": [],
            "dispositions": {
                "item-gate": {"disposition": "blocked", "evidence": "blocked"},
            },
        },
    }
    store.create_run(
        "run-20260101T000001-000001",
        plan=plan,
        **create_run_kwargs(
            store.root,
            resolved_config={
                "run": {"output_goal": "Deliver the output.", "input_refs": []},
                "planning": {"max_depth": 4, "max_expansion_per_item": 7},
            },
        ),
        production={
            "dispositions": {"item-gate": "blocked"},
            "batches": [gate_batch],
            "output_evidence": [],
            "revision": 0,
            "output_revision": 0,
        },
    )

    service = PlanAgentService(store, "run-20260101T000001-000001")
    token = grant_capability(store, "run-20260101T000001-000001", role="planner", phase=PLANNING)
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
        capability_token=token,
    )

    assert result["ok"] is False
    assert result["applied"] is True
    assert any(issue["code"] == "dependency_deadlock" for issue in result["issues"])


def test_apply_rejects_add_item_without_title(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)

    service = PlanAgentService(store, "run-20260101T000001-000001")
    token = grant_capability(store, "run-20260101T000001-000001", role="planner", phase=PLANNING)
    with pytest.raises(RequestError, match="oneOf|title"):
        service.apply(
            {
                "base_revision": 0,
                "operations": [
                    {
                        "op": "add_item",
                        "parent_id": "item-root",
                        "placement": {"last_child": True},
                        "item": {},
                    }
                ],
            },
            capability_token=token,
        )

    assert store.load_plan("run-20260101T000001-000001")["revision"] == 0
    events = store.load_events("run-20260101T000001-000001")
    assert not any(event.get("type") == "plan_applied" for event in events)


def test_cli_plan_apply_exits_nonzero_when_validation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FileRunStore(tmp_path)
    gate = PlanItem("item-gate", None, "0000000000", "Gate", kind="work")
    worker = PlanItem(
        "item-worker",
        None,
        "0000000100",
        "Worker",
        depends_on=["item-gate"],
        kind="work",
    )
    plan = Plan(
        id="plan-001",
        revision=0,
        output_goal="Deliver the output.",
        items={"item-gate": gate, "item-worker": worker},
    )
    gate_batch = {
        "id": "batch-gate",
        "status": "completed",
        "plan_items": ["item-gate"],
        "result": {
            "outputs": [],
            "contributions": [],
            "dispositions": {
                "item-gate": {"disposition": "blocked", "evidence": "blocked"},
            },
        },
    }
    store.create_run(
        "run-20260101T000001-000001",
        plan=plan,
        **create_run_kwargs(
            store.root,
            resolved_config={
                "run": {"output_goal": "Deliver the output.", "input_refs": []},
                "planning": {"max_depth": 4, "max_expansion_per_item": 7},
            },
        ),
        production={
            "dispositions": {"item-gate": "blocked"},
            "batches": [gate_batch],
            "output_evidence": [],
            "revision": 0,
            "output_revision": 0,
        },
    )
    set_capability_token_file(
        monkeypatch,
        store,
        "run-20260101T000001-000001",
        grant_capability(store, "run-20260101T000001-000001", role="planner", phase=PLANNING),
    )

    request_path = write_agent_request_file(
        store,
        "run-20260101T000001-000001",
        "apply.json",
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
    )

    result = run_cli(
        [
            "agent",
            "plan",
            "apply",
            "--run",
            "run-20260101T000001-000001",
            "--runs-dir",
            str(tmp_path),
            "--request",
            str(request_path),
        ]
    )

    assert result.exit_code == 1
    payload = result.json()
    assert payload["applied"] is True
    assert payload["ok"] is False


def test_snapshot_ready_excludes_review_blocked_items(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    save_review_payload(store, "run-20260101T000001-000001", {
            "id": "review-focused-plan-01",
            "type": "focused_plan",
            "revise_at": "blocker",
            "reviewer_session_id": "session-1",
            "target_revision": 0,
            "scope": {"kind": "focused_plan", "item_ids": ["item-child"]},
            "status": "changes_requested",
            "findings": [
                {
                    "id": "finding-01",
                    "severity": "blocker",
                    "category": "correctness",
                    "target_refs": ["item-child"],
                    "issue": "Needs more detail.",
                    "recommended_change": "Expand acceptance.",
                    "status": "unresolved",
                }
            ],
            "revision_cycles": 0,
        },
    )

    service = PlanAgentService(store, "run-20260101T000001-000001")
    ready = service.snapshot(view="ready")

    assert ready["ok"] is True
    assert "item-child" not in ready["ready_item_ids"]
    assert ready["not_ready"]["item-child"]["reason"] == "review_blocked"


def test_snapshot_active_includes_scope_boundaries_acceptance(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        scope=Scope(includes=["auth"], excludes=["billing"]),
        boundaries=["No external APIs"],
        acceptance=["Login works"],
        kind="aggregate",
    )
    plan = Plan(
        id="plan-001",
        revision=0,
        output_goal="Deliver the output.",
        items={"item-root": root},
    )
    store.create_run(
        "run-20260101T000001-000001",
        plan=plan,
        **create_run_kwargs(
            store.root,
            resolved_config={
                "run": {"output_goal": "Deliver the output.", "input_refs": []},
                "planning": {"max_depth": 4, "max_expansion_per_item": 7},
            },
        ),
    )

    service = PlanAgentService(store, "run-20260101T000001-000001")
    snapshot = service.snapshot(view="active")

    item = snapshot["items"][0]
    assert item["depth"] == 0
    assert item["scope"] == {"includes": ["auth"], "excludes": ["billing"]}
    assert item["boundaries"] == ["No external APIs"]
    assert item["acceptance"] == ["Login works"]


def test_plan_check_approval_without_binding_surfaces_not_checked_warnings(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    service = PlanAgentService(store, "run-20260101T000001-000001")

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
    save_review_payload(store, "run-20260101T000001-000001",
        whole_plan_approval_record(
            store,
            "run-20260101T000001-000001",
            reviewer_session_id="session-1",
        ),
    )

    service = PlanAgentService(store, "run-20260101T000001-000001")
    draft = service.check(mode="draft")
    approval = service.check(mode="approval")

    assert draft["ok"] is True
    assert approval["ok"] is True

    review = store.load_review("run-20260101T000001-000001", "review-whole-plan-01")
    review = dict(review)
    review["approved_digests"] = dict(review["approved_digests"])
    review["approved_digests"]["plan"] = "stale-plan-digest"
    save_review_payload(store, "run-20260101T000001-000001", review)

    approval_after_tamper = service.check(mode="approval")
    assert approval_after_tamper["ok"] is False
    assert any(
        issue["code"] == "digest_mismatch" for issue in approval_after_tamper["issues"]
    )
