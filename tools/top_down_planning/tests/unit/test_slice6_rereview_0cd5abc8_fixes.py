"""Second-pass Slice 6 regressions against commit 0cd5abc8."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from core_tools.schema import validate_against_schema
from top_down_planning.agent_tool import (
    PlanAgentService,
    ProductionAgentService,
    RequestError,
    ReviewAgentService,
    RevisionConflictError,
)
from top_down_planning.agent_tool.request_schema import validate_agent_request
from top_down_planning.orchestrator.phases import PLANNING, PRODUCTION
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.commit import CommitSpec, StagedArtifact
from top_down_planning.persistence.digests import compute_output_digest, compute_plan_digest
from top_down_planning.schema_docs import PUBLIC_SCHEMAS, SCHEMAS, show_schema
from tests.conftest import run_cli
from tests.helpers import (
    create_run_kwargs,
    grant_capability,
    plan_root_item,
    save_review_payload,
    set_capability_token_file,
    whole_plan_approval_record,
    write_agent_request_file,
)
from tests.unit.test_slice6_agent_tool_fixes import (
    _batch_apply_request,
    _create_planning_run,
    _create_production_run,
)


_PLAN_OPERATION_BRANCHES: dict[str, dict[str, Any]] = {
    "add_item": {
        "op": "add_item",
        "temp_id": "item-docs",
        "parent_id": "item-root",
        "item": {"title": "Docs", "kind": "work", "scope": {"includes": ["Docs capability"]}},
    },
    "update_item": {
        "op": "update_item",
        "item_id": "item-api",
        "patch": {"title": "API renamed"},
    },
    "update_plan": {
        "op": "update_plan",
        "patch": {"boundaries": ["Plan boundary", "Docs stay in scope."]},
    },
    "move_subtree": {
        "op": "move_subtree",
        "item_id": "item-ui",
        "new_parent_id": "item-api",
    },
    "supersede_item": {
        "op": "supersede_item",
        "item_id": "item-api",
        "temp_id": "item-api-v2",
        "replacement": {
            "title": "API v2",
            "kind": "work",
            "scope": {"includes": ["API capability"]},
        },
    },
    "remove_item": {
        "op": "remove_item",
        "item_id": "item-ui",
    },
    "add_dependency": {
        "op": "add_dependency",
        "item_id": "item-ui",
        "depends_on": "item-api",
    },
    "remove_dependency": {
        "op": "remove_dependency",
        "item_id": "item-ui",
        "depends_on": "item-api",
    },
    "replace_dependencies": {
        "op": "replace_dependencies",
        "item_id": "item-ui",
        "depends_on": ["item-api"],
    },
}


def test_move_subtree_schema_requires_new_parent_id() -> None:
    schema = show_schema("plan-transaction")
    missing = {
        "base_revision": 0,
        "operations": [{"op": "move_subtree", "item_id": "item-api"}],
    }
    issues = validate_against_schema(missing, schema)
    assert issues
    with pytest.raises(RequestError):
        validate_agent_request("plan_apply", missing)


def test_every_plan_operation_branch_is_schema_valid_and_runtime_compatible(
    tmp_path: Path,
) -> None:
    schema = show_schema("plan-transaction")
    advertised = {
        branch["properties"]["op"]["const"]
        for branch in schema["properties"]["operations"]["items"]["oneOf"]
    }
    assert advertised == set(_PLAN_OPERATION_BRANCHES)

    for index, (op_name, operation) in enumerate(_PLAN_OPERATION_BRANCHES.items(), start=1):
        store = FileRunStore(tmp_path / op_name)
        branch_run = f"run-20260101T07010{index}-07010{index}"
        _create_planning_run(store, branch_run)
        token = grant_capability(store, branch_run, role="planner", phase=PLANNING)
        operations = [operation]
        if op_name == "remove_dependency":
            operations = [_PLAN_OPERATION_BRANCHES["add_dependency"], operation]
        payload = {"base_revision": 0, "operations": operations}
        assert validate_against_schema(payload, schema) == []
        result = PlanAgentService(store, branch_run).apply(payload, capability_token=token)
        assert result["applied"] is True
        assert int(store.load_plan(branch_run)["revision"]) == 1


def test_artifact_crash_before_production_replace_rolls_back_snapshots(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T070011-070011"
    _create_production_run(store, run_id)
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)
    production_before = store.load_production(run_id)

    original_replace = Path.replace

    def crash_on_production_json(self: Path, target: Path) -> Path:
        if target.name == "production.json":
            raise OSError("simulated crash before production replace")
        return original_replace(self, target)

    with patch.object(Path, "replace", crash_on_production_json):
        with pytest.raises(OSError, match="simulated crash before production replace"):
            ProductionAgentService(store, run_id).apply(
                _batch_apply_request(
                    plan_items=["item-api"],
                    dispositions={"item-api": {"disposition": "completed"}},
                    outputs=[{"id": "out-a", "type": "artifact", "ref": "a.txt"}],
                ),
                capability_token=token,
            )

    recovered = FileRunStore(tmp_path)
    production_after = recovered.load_production(run_id)
    assert production_after["revision"] == production_before["revision"]
    artifacts = recovered.artifacts_dir(run_id)
    leftover = list(artifacts.glob("*")) if artifacts.is_dir() else []
    assert leftover == []


def test_artifact_rollback_survives_cleanup_failure(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T070012-070012"
    _create_production_run(store, run_id)
    production = store.load_production(run_id)
    expected = int(production["revision"])
    updated = dict(production)
    updated["revision"] = expected + 1
    artifact = StagedArtifact(snapshot_id="snapdeadbeef01", filename="a.txt", data=b"hello")
    original_unlink = Path.unlink

    def fail_first_unlink(self: Path, *args: Any, **kwargs: Any) -> None:
        if self.name == "a.txt" and "artifacts" in str(self):
            raise OSError("simulated cleanup failure")
        return original_unlink(self, *args, **kwargs)

    original_replace = Path.replace

    def crash_on_production_json(self: Path, target: Path) -> Path:
        if target.name == "production.json":
            raise OSError("simulated crash after artifact promote")
        return original_replace(self, target)

    with patch.object(Path, "replace", crash_on_production_json):
        with pytest.raises(OSError, match="simulated crash after artifact promote"):
            store.commit(
                run_id,
                CommitSpec(
                    production=updated,
                    production_expected_revision=expected,
                    artifacts=[artifact],
                    events=[{"type": "test_artifact_commit", "run_id": run_id}],
                ),
            )

    with patch.object(Path, "unlink", fail_first_unlink):
        recovered = FileRunStore(tmp_path)
        recovered.load_production(run_id)

    leftover = list(recovered.artifacts_dir(run_id).glob("*"))
    assert leftover == []
    assert recovered.load_production(run_id)["revision"] == expected


def test_production_and_plan_snapshots_expose_artifact_digests(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T070013-070013"
    _create_production_run(store, run_id)
    plan = store.load_plan(run_id)
    production = store.load_production(run_id)
    plan_view = PlanAgentService(store, run_id).snapshot()
    production_view = ProductionAgentService(store, run_id).snapshot()
    assert plan_view["plan_digest"] == compute_plan_digest(plan)
    assert production_view["output_digest"] == compute_output_digest(production)
    assert production_view["plan_digest"] == compute_plan_digest(plan)
    schema = show_schema("focused-review-request")
    description = str(schema.get("description") or "").lower()
    assert "plan_digest" in description
    assert "output_digest" in description


def test_stale_review_respond_and_record_actions_are_revision_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T070014-070014"
    _create_planning_run(store, run_id)
    planner = grant_capability(store, run_id, role="planner", phase=PLANNING)
    plan = store.load_plan(run_id)
    created = ReviewAgentService(store, run_id).request(
        {
            "type": "focused_plan",
            "scope": {"item_ids": ["item-api"]},
            "target_revision": int(plan["revision"]),
            "target_digest": compute_plan_digest(plan),
        },
        capability_token=planner,
    )
    loop_id = created["loop_id"]
    save_review_payload(
        store,
        run_id,
        {
            **store.load_review(run_id, loop_id),
            "reviewer_session_id": "stub-session-reviewer",
        },
    )
    reviewer = grant_capability(
        store,
        run_id,
        role="reviewer",
        phase=PLANNING,
        session_kind="reviewer",
        session_id="stub-session-reviewer",
        loop_id=loop_id,
    )
    loop = store.load_review(run_id, loop_id)
    request_path = write_agent_request_file(
        store,
        run_id,
        "review-respond-stale.json",
        {
            "loop_id": loop_id,
            "target_revision": int(plan["revision"]) + 9,
            "finding_set_id": loop["finding_set_id"],
            "reported_findings": [],
            "review_completed": True,
            "summary": "stale",
            "target_digest": "not-the-current-digest",
        },
    )
    set_capability_token_file(monkeypatch, store, run_id, reviewer)
    result = run_cli(
        [
            "agent",
            "review",
            "respond",
            "--run",
            run_id,
            "--runs-dir",
            str(tmp_path),
            "--request",
            str(request_path),
        ]
    )
    payload = result.json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "revision_conflict"

    owner = grant_capability(store, run_id, role="planner", phase=PLANNING)
    set_capability_token_file(monkeypatch, store, run_id, owner)
    record_path = write_agent_request_file(
        store,
        run_id,
        "review-record-stale.json",
        {
            "loop_id": loop_id,
            "target_revision": int(plan["revision"]) + 9,
            "target_digest": "not-the-current-digest",
            "finding_set_id": loop["finding_set_id"],
            "default_optional_action": "defer",
        },
    )
    recorded = run_cli(
        [
            "agent",
            "review",
            "record-actions",
            "--run",
            run_id,
            "--runs-dir",
            str(tmp_path),
            "--request",
            str(record_path),
        ]
    )
    recorded_payload = recorded.json()
    assert recorded_payload["ok"] is False
    assert recorded_payload["error"]["code"] == "revision_conflict"


def test_every_public_agent_verb_has_a_response_schema(tmp_path: Path) -> None:
    required = {
        "plan-snapshot-response",
        "plan-check-response",
        "plan-apply-response",
        "production-snapshot-response",
        "production-check-response",
        "production-apply-response",
        "production-amendment-response",
        "production-completion-response",
        "production-blocker-response",
        "review-respond-response",
        "review-record-finding-actions-response",
        "focused-review-request-response",
        "run-status-response",
        "agent-error",
    }
    assert required.issubset(set(PUBLIC_SCHEMAS))

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T070015-070015"
    _create_planning_run(store, run_id)
    token = grant_capability(store, run_id, role="planner", phase=PLANNING)
    plan_service = PlanAgentService(store, run_id)
    pairs = [
        (plan_service.snapshot(), "plan-snapshot-response"),
        (plan_service.check(), "plan-check-response"),
        (
            plan_service.apply(
                {
                    "base_revision": 0,
                    "operations": [
                        {
                            "op": "update_item",
                            "item_id": "item-api",
                            "patch": {"title": "API applied"},
                        }
                    ],
                },
                capability_token=token,
            ),
            "plan-apply-response",
        ),
    ]
    for payload, schema_name in pairs:
        assert validate_against_schema(payload, SCHEMAS[schema_name]) == []


def test_approval_mode_plan_views_do_not_hybridize_independent_loads(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T070016-070016"
    _create_planning_run(store, run_id)
    save_review_payload(store, run_id, whole_plan_approval_record(store, run_id))

    class HybridStore:
        def __init__(self, inner: FileRunStore) -> None:
            self._inner = inner

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

        def load_canonical_snapshot(self, loaded_run_id: str) -> Any:
            return self._inner.load_canonical_snapshot(loaded_run_id)

        def list_reviews(self, loaded_run_id: str) -> list[dict[str, Any]]:
            return []

        def load_run(self, loaded_run_id: str) -> dict[str, Any]:
            raise AssertionError("approval-mode views must not reread run state")

        def load_resolved_config(self, loaded_run_id: str) -> dict[str, Any]:
            raise AssertionError("approval-mode views must not reread resolved config")

    hybrid = HybridStore(store)
    snapshot = PlanAgentService(hybrid, run_id).snapshot(view="issues", mode="approval")
    check = PlanAgentService(hybrid, run_id).check(mode="approval")
    canonical_issues = PlanAgentService(store, run_id).snapshot(view="issues", mode="approval")
    assert snapshot["issues"] == canonical_issues["issues"]
    assert check["issues"] == PlanAgentService(store, run_id).check(mode="approval")["issues"]
