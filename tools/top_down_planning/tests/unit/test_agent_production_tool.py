"""Unit tests for agent production snapshot/apply/check tool."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from top_down_planning.agent_tool import (
    ProductionAgentService,
    RequestError,
    RevisionConflictError,
)
from top_down_planning.agent_tool.errors import CapabilityDeniedError
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator.phases import PRODUCTION
from top_down_planning.persistence import FileRunStore
from tests.conftest import run_cli
from tests.helpers import (
    save_review_payload,
    create_run_kwargs,
    grant_capability,
    set_capability_env,
    whole_plan_approval_record,
)


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
    run_id: str = "run-20260101T000201-000201",
) -> None:
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        kind="aggregate",
    )
    first = PlanItem(
        id="item-first",
        parent_id="item-root",
        order_key="0000000000",
        title="First",
        outcome="First outcome.",
        kind="work",
    )
    second = PlanItem(
        id="item-second",
        parent_id="item-root",
        order_key="0000000100",
        title="Second",
        outcome="Second outcome.",
        depends_on=["item-first"],
        kind="work",
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
    }
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=config),
        phase=PRODUCTION,
    )
    save_review_payload(store, run_id, whole_plan_approval_record(store, run_id))


def test_apply_requires_production_revision(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_production_run(store)
    service = ProductionAgentService(store, "run-20260101T000201-000201")
    token = grant_capability(store, "run-20260101T000201-000201", role="producer", phase=PRODUCTION)

    with pytest.raises(RequestError, match="production_revision"):
        service.apply(
            {
                "plan_items": ["item-first"],
                "dispositions": {"item-first": {"disposition": "completed"}},
            },
            capability_token=token,
        )


def test_producer_can_record_batch_via_service(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_production_run(store)
    service = ProductionAgentService(store, "run-20260101T000201-000201")
    token = grant_capability(store, "run-20260101T000201-000201", role="producer", phase=PRODUCTION)

    result = service.apply(
        _batch_apply_request(
            plan_items=["item-first"],
            dispositions={"item-first": {"disposition": "completed"}},
        ),
        capability_token=token,
    )

    assert result["ok"] is True
    assert result["production_revision"] == 1
    production = store.load_production("run-20260101T000201-000201")
    assert production["dispositions"]["item-first"] == "completed"


def test_stale_production_revision_apply_fails(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_production_run(store)
    service = ProductionAgentService(store, "run-20260101T000201-000201")
    token = grant_capability(store, "run-20260101T000201-000201", role="producer", phase=PRODUCTION)

    with pytest.raises(RevisionConflictError) as exc_info:
        service.apply(
            _batch_apply_request(
                plan_items=["item-first"],
                dispositions={"item-first": {"disposition": "completed"}},
                production_revision=5,
            ),
            capability_token=token,
        )

    assert exc_info.value.action is not None
    assert "production snapshot" in exc_info.value.action.lower()


def test_reviewer_capability_denied_for_production_apply(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_production_run(store)
    service = ProductionAgentService(store, "run-20260101T000201-000201")
    token = grant_capability(
        store,
        "run-20260101T000201-000201",
        role="reviewer",
        phase=PRODUCTION,
        session_kind="reviewer",
    )

    with pytest.raises(CapabilityDeniedError):
        service.apply(
            _batch_apply_request(
                plan_items=["item-first"],
                dispositions={"item-first": {"disposition": "completed"}},
            ),
            capability_token=token,
        )


def test_submit_completion_rejected_when_items_remain_open(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_production_run(store)
    service = ProductionAgentService(store, "run-20260101T000201-000201")
    token = grant_capability(store, "run-20260101T000201-000201", role="producer", phase=PRODUCTION)

    with pytest.raises(RequestError, match="every applicable item"):
        service.submit_completion(
            {"goal_assessment": "Goal is met.", "goal_met": True},
            capability_token=token,
        )


def test_submit_completion_success_does_not_set_outcome(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_production_run(store)
    service = ProductionAgentService(store, "run-20260101T000201-000201")
    token = grant_capability(store, "run-20260101T000201-000201", role="producer", phase=PRODUCTION)

    service.apply(
        _batch_apply_request(
            plan_items=["item-first"],
            dispositions={"item-first": {"disposition": "completed"}},
        ),
        capability_token=token,
    )
    service.apply(
        _batch_apply_request(
            plan_items=["item-second"],
            dispositions={"item-second": {"disposition": "completed"}},
            production_revision=1,
        ),
        capability_token=token,
    )

    result = service.submit_completion(
        {"goal_assessment": "Output goal is fully met.", "goal_met": True},
        capability_token=token,
    )

    assert result["ok"] is True
    assert result["run_outcome"] is None
    run = store.load_run("run-20260101T000201-000201")
    assert run["outcome"] is None
    production = store.load_production("run-20260101T000201-000201")
    assert production["completion_claim"]["goal_assessment"] == "Output goal is fully met."


def test_request_amendment_persists_pending_request(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_production_run(store)
    service = ProductionAgentService(store, "run-20260101T000201-000201")
    token = grant_capability(store, "run-20260101T000201-000201", role="producer", phase=PRODUCTION)

    result = service.request_amendment(
        {
            "evidence": "Missing API branch in approved plan.",
            "affected_refs": ["item-root"],
            "summary": "Need API subtree.",
        },
        capability_token=token,
    )

    assert result["ok"] is True
    assert result["signal"] == "amendment_requested"
    production = store.load_production("run-20260101T000201-000201")
    assert production["pending_amendment_id"] == "amendment-01"
    assert production["amendment_requests"][0]["status"] == "pending"


def test_report_blocked_persists_blocker_without_outcome(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_production_run(store)
    service = ProductionAgentService(store, "run-20260101T000201-000201")
    token = grant_capability(store, "run-20260101T000201-000201", role="producer", phase=PRODUCTION)

    result = service.report_blocked(
        {
            "evidence": "Upstream service unavailable.",
            "affected_refs": ["item-first"],
            "summary": "Cannot proceed.",
        },
        capability_token=token,
    )

    assert result["ok"] is True
    assert result["run_outcome"] is None
    production = store.load_production("run-20260101T000201-000201")
    assert production["blocker_report"]["evidence"] == "Upstream service unavailable."


def test_production_check_reports_open_items(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_production_run(store)
    service = ProductionAgentService(store, "run-20260101T000201-000201")

    result = service.check()

    assert result["ok"] is False
    assert result["all_applicable_items_processed"] is False
    assert any("remain without terminal disposition" in issue for issue in result["issues"])


def test_cli_production_workflow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = FileRunStore(tmp_path)
    _create_production_run(store)
    set_capability_env(
        monkeypatch,
        grant_capability(store, "run-20260101T000201-000201", role="producer", phase=PRODUCTION),
    )

    first_request = _batch_apply_request(
        plan_items=["item-first"],
        dispositions={"item-first": {"disposition": "completed"}},
    )
    first_path = tmp_path / "batch-first.json"
    first_path.write_text(json.dumps(first_request), encoding="utf-8")

    first_apply = run_cli(
        [
            "agent",
            "production",
            "apply",
            "--run",
            "run-20260101T000201-000201",
            "--runs-dir",
            str(tmp_path),
            "--request",
            str(first_path),
        ]
    )
    assert first_apply.exit_code == 0, first_apply.stderr
    first_payload = first_apply.json()
    assert first_payload["ok"] is True

    second_request = _batch_apply_request(
        plan_items=["item-second"],
        dispositions={"item-second": {"disposition": "completed"}},
        production_revision=first_payload["production_revision"],
    )
    second_path = tmp_path / "batch-second.json"
    second_path.write_text(json.dumps(second_request), encoding="utf-8")

    second_apply = run_cli(
        [
            "agent",
            "production",
            "apply",
            "--run",
            "run-20260101T000201-000201",
            "--runs-dir",
            str(tmp_path),
            "--request",
            str(second_path),
        ]
    )
    assert second_apply.exit_code == 0, second_apply.stderr

    completion_path = tmp_path / "completion.json"
    completion_path.write_text(
        json.dumps({"goal_assessment": "Delivered the feature.", "goal_met": True}),
        encoding="utf-8",
    )
    completion = run_cli(
        [
            "agent",
            "production",
            "submit-completion",
            "--run",
            "run-20260101T000201-000201",
            "--runs-dir",
            str(tmp_path),
            "--request",
            str(completion_path),
        ]
    )
    assert completion.exit_code == 0, completion.stderr
    completion_payload = completion.json()
    assert completion_payload["ok"] is True
    assert completion_payload["run_outcome"] is None


def test_cli_reviewer_denied_for_production_apply(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FileRunStore(tmp_path)
    _create_production_run(store)
    set_capability_env(
        monkeypatch,
        grant_capability(
            store,
            "run-20260101T000201-000201",
            role="reviewer",
            phase=PRODUCTION,
            session_kind="reviewer",
        ),
    )

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

    result = run_cli(
        [
            "agent",
            "production",
            "apply",
            "--run",
            "run-20260101T000201-000201",
            "--runs-dir",
            str(tmp_path),
            "--request",
            str(request_path),
        ]
    )
    assert result.exit_code == 1
    payload = result.json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "capability_denied"


def test_production_ready_snapshot_excludes_review_blocked_items(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_production_run(store)
    save_review_payload(store, "run-20260101T000201-000201", {
            "id": "review-focused-output-01",
            "type": "focused_output",
            "revise_at": "blocker",
            "reviewer_session_id": "stub-session-reviewer",
            "target_revision": 0,
            "scope": {"kind": "focused_output", "item_ids": ["item-second"]},
            "status": "changes_requested",
            "findings": [
                {
                    "id": "finding-01",
                    "severity": "blocker",
                    "target_refs": ["item-second"],
                    "issue": "Output incomplete.",
                    "recommended_change": "Add evidence.",
                    "status": "unresolved",
                }
            ],
            "revision_cycles": 0,
        },
    )

    service = ProductionAgentService(store, "run-20260101T000201-000201")
    ready = service.snapshot(view="ready")

    assert ready["ok"] is True
    assert "item-first" in ready["ready_item_ids"]
    assert "item-second" not in ready["ready_item_ids"]
    assert ready["not_ready"]["item-second"]["reason"] == "review_blocked"


def test_production_ready_snapshot_includes_plan_validation_fields(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_production_run(store)

    service = ProductionAgentService(store, "run-20260101T000201-000201")
    ready = service.snapshot(view="ready")

    assert "ok" in ready
    assert "issues" in ready
    assert "warnings" in ready
    assert ready["ok"] is True


def test_production_ready_snapshot_includes_ready_item_contracts(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_production_run(store)
    service = ProductionAgentService(store, "run-20260101T000201-000201")

    ready = service.snapshot(view="ready")

    assert "item-first" in ready["ready_item_ids"]
    assert "item-root" not in ready["ready_item_ids"]
    by_id = {item["id"]: item for item in ready["ready_items"]}
    assert set(by_id) == set(ready["ready_item_ids"])
    first = by_id["item-first"]
    assert first["title"] == "First"
    assert first["outcome"] == "First outcome."
    assert first["scope"] == {"includes": [], "excludes": []}
    assert first["boundaries"] == []
    assert first["acceptance"] == []
    assert first["depends_on"] == []
    assert first["ancestor_path"] == ["item-root"]
    assert "item-second" not in by_id


def test_production_ready_snapshot_preserves_blocker_behavior_with_ready_items(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    _create_production_run(store)
    service = ProductionAgentService(store, "run-20260101T000201-000201")
    ready = service.snapshot(view="ready")

    assert "item-second" not in ready["ready_item_ids"]
    assert ready["not_ready"]["item-second"]["reason"] == "unsatisfied_dependency"
    assert all(item["id"] in ready["ready_item_ids"] for item in ready["ready_items"])


def test_multi_item_batch_still_works_with_ready_items(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    root = PlanItem(id="item-root", parent_id=None, order_key="0000000000", title="Root", kind="aggregate")
    a = PlanItem(
        id="item-a",
        parent_id="item-root",
        order_key="0000000000",
        title="A",
        outcome="A done.",
        acceptance=["A ok"],
        kind="work",
    )
    b = PlanItem(
        id="item-b",
        parent_id="item-root",
        order_key="0000000100",
        title="B",
        outcome="B done.",
        kind="work",
    )
    plan = Plan(
        id="plan-multi",
        revision=0,
        output_goal="Deliver.",
        items={"item-root": root, "item-a": a, "item-b": b},
    )
    config = {
        "run": {"output_goal": "Deliver.", "input_refs": ["README.md"]},
        "planning": {
            "stop_hint": "Stop.",
            "max_depth": 4,
            "max_expansion_per_item": 7,
        },
        "limits": {"production": {"max_batches": 50, "max_agent_turns_per_batch": 10}},
    }
    store.create_run(
        "run-20260101T000211-000211",
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=config),
        phase=PRODUCTION,
    )
    save_review_payload(store, "run-20260101T000211-000211",
        whole_plan_approval_record(store, "run-20260101T000211-000211"),
    )
    service = ProductionAgentService(store, "run-20260101T000211-000211")
    ready = service.snapshot(view="ready")
    assert "item-a" in ready["ready_item_ids"]
    assert "item-b" in ready["ready_item_ids"]
    token = grant_capability(
        store, "run-20260101T000211-000211", role="producer", phase=PRODUCTION
    )
    result = service.apply(
        {
            "production_revision": 0,
            "plan_items": ["item-a", "item-b"],
            "dispositions": {
                "item-a": {"disposition": "completed", "evidence": "A done"},
                "item-b": {"disposition": "completed", "evidence": "B done"},
            },
            "outputs": [],
            "contributions": [],
            "summary": "both items",
            "empty_output": True,
            "empty_output_reason": "no artifacts required",
        },
        capability_token=token,
    )
    assert result["ok"] is True
    assert result["production_revision"] == 1


def test_ready_items_equivalent_after_reload(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_production_run(store)
    first = ProductionAgentService(store, "run-20260101T000201-000201").snapshot(
        view="ready"
    )
    reloaded = FileRunStore(tmp_path)
    second = ProductionAgentService(reloaded, "run-20260101T000201-000201").snapshot(
        view="ready"
    )
    assert first["ready_item_ids"] == second["ready_item_ids"]
    assert first["ready_items"] == second["ready_items"]
    assert first["not_ready"] == second["not_ready"]


def test_cli_production_snapshot_exits_nonzero_when_plan_validation_fails(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    _create_production_run(store)
    plan_payload = store.load_plan("run-20260101T000201-000201")
    expected_revision = int(plan_payload["revision"])
    plan_payload = dict(plan_payload)
    plan_payload["schema_version"] = 99
    plan_payload["revision"] = expected_revision + 1
    store.save_plan("run-20260101T000201-000201", plan_payload, expected_revision)

    result = run_cli(
        [
            "agent",
            "production",
            "snapshot",
            "--run",
            "run-20260101T000201-000201",
            "--runs-dir",
            str(tmp_path),
            "--view",
            "ready",
        ]
    )

    assert result.exit_code == 1
    payload = result.json()
    assert payload["ok"] is False
    assert any(issue["code"] == "invalid_schema_version" for issue in payload["issues"])


def test_duplicate_evidence_id_across_batches_is_rejected(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_production_run(store)
    artifact = tmp_path / "leaf.txt"
    artifact.write_text("first", encoding="utf-8")
    service = ProductionAgentService(store, "run-20260101T000201-000201")
    token = grant_capability(store, "run-20260101T000201-000201", role="producer", phase=PRODUCTION)

    first_request = _batch_apply_request(
        plan_items=["item-first"],
        dispositions={"item-first": {"disposition": "completed"}},
    )
    first_request["outputs"] = [{"id": "output-leaf", "type": "artifact", "ref": "leaf.txt"}]
    service.apply(first_request, capability_token=token)

    second_request = _batch_apply_request(
        plan_items=["item-second"],
        dispositions={"item-second": {"disposition": "completed"}},
        production_revision=1,
    )
    second_request["outputs"] = [{"id": "output-leaf", "type": "artifact", "ref": "leaf.txt"}]
    with pytest.raises(RequestError, match="duplicate output id across run history"):
        service.apply(second_request, capability_token=token)


def test_artifact_snapshots_use_unique_directories(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_production_run(store)
    artifact = tmp_path / "leaf.txt"
    artifact.write_text("content", encoding="utf-8")
    service = ProductionAgentService(store, "run-20260101T000201-000201")
    token = grant_capability(store, "run-20260101T000201-000201", role="producer", phase=PRODUCTION)

    request = _batch_apply_request(
        plan_items=["item-first"],
        dispositions={"item-first": {"disposition": "completed"}},
    )
    request["outputs"] = [{"id": "output-a", "type": "artifact", "ref": "leaf.txt"}]
    service.apply(request, capability_token=token)

    request2 = _batch_apply_request(
        plan_items=["item-second"],
        dispositions={"item-second": {"disposition": "completed"}},
        production_revision=1,
    )
    request2["outputs"] = [{"id": "output-b", "type": "artifact", "ref": "leaf.txt"}]
    service.apply(request2, capability_token=token)

    production = store.load_production("run-20260101T000201-000201")
    evidence = production["output_evidence"]
    snapshot_refs = [entry["snapshot_ref"] for entry in evidence]
    assert len(snapshot_refs) == 2
    assert snapshot_refs[0] != snapshot_refs[1]
    assert all(ref.startswith("artifacts/") for ref in snapshot_refs)
    assert "output-a" not in snapshot_refs[0] or snapshot_refs[0].split("/")[1] != "output-a"
