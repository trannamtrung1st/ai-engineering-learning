"""Slice 6 regression tests for agent tool wire-contract and freshness guarantees."""

from __future__ import annotations

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
    RunAgentService,
)
from top_down_planning.agent_tool.authorization import authorize_mutation
from top_down_planning.agent_tool.errors import CapabilityDeniedError
from top_down_planning.agent_tool.request_schema import validate_agent_request
from top_down_planning.domain.models import Plan, PlanItem, Scope
from top_down_planning.orchestrator.phases import PLANNING, PRODUCTION, WHOLE_OUTPUT_REVIEW
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.commit import CommitSpec
from top_down_planning.persistence.digests import compute_plan_digest
from top_down_planning.schema_docs import PUBLIC_SCHEMAS, SCHEMAS, show_example, show_schema
from tests.conftest import run_cli
from tests.helpers import (
    create_run_kwargs,
    grant_capability,
    plan_root_item,
    set_capability_token_file,
    whole_plan_approval_record,
    write_agent_request_file,
)


def _create_planning_run(store: FileRunStore, run_id: str) -> None:
    root = plan_root_item()
    child = PlanItem(
        id="item-api",
        parent_id="item-root",
        order_key="0000000000",
        title="API",
        outcome="API exists.",
        kind="work",
        scope=Scope(includes=["API capability"]),
    )
    ui = PlanItem(
        id="item-ui",
        parent_id="item-root",
        order_key="0000000100",
        title="UI",
        outcome="UI exists.",
        kind="work",
        scope=Scope(includes=["UI capability"]),
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver the output.",
        scope=Scope(includes=["Plan scope"]),
        boundaries=["Plan boundary"],
        items={"item-root": root, "item-api": child, "item-ui": ui},
    )
    store.create_run(run_id, plan=plan, **create_run_kwargs(store.root))


def _create_production_run(store: FileRunStore, run_id: str) -> None:
    _create_planning_run(store, run_id)
    run = store.load_run(run_id)
    expected = int(run["revision"])
    updated = dict(run)
    updated["revision"] = expected + 1
    updated["phase"] = PRODUCTION
    store.commit(run_id, CommitSpec(run=updated, run_expected_revision=expected, events=[]))
    from tests.helpers import save_review_payload

    save_review_payload(store, run_id, whole_plan_approval_record(store, run_id))


def _batch_apply_request(
    *,
    plan_items: list[str],
    dispositions: dict[str, Any],
    production_revision: int = 0,
    outputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "production_revision": production_revision,
        "plan_items": plan_items,
        "dispositions": dispositions,
        "outputs": outputs or [],
        "contributions": [],
        "summary": "batch complete",
    }


def _advance_run_phase(store: FileRunStore, run_id: str, phase: str) -> None:
    run = store.load_run(run_id)
    expected = int(run["revision"])
    updated = dict(run)
    updated["revision"] = expected + 1
    updated["phase"] = phase
    store.commit(run_id, CommitSpec(run=updated, run_expected_revision=expected, events=[]))


def test_production_apply_rejects_stale_authorization_after_phase_change(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T060001-060001"
    _create_production_run(store, run_id)
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)
    service = ProductionAgentService(store, run_id)
    production_before = store.load_production(run_id)

    real_authorize = authorize_mutation

    def authorize_then_advance(*args: Any, **kwargs: Any) -> Any:
        result = real_authorize(*args, **kwargs)
        _advance_run_phase(store, run_id, WHOLE_OUTPUT_REVIEW)
        return result

    with patch(
        "top_down_planning.agent_tool.production_service.authorize_mutation",
        side_effect=authorize_then_advance,
    ):
        with pytest.raises((RevisionConflictError, CapabilityDeniedError)):
            service.apply(
                _batch_apply_request(
                    plan_items=["item-api"],
                    dispositions={"item-api": {"disposition": "completed"}},
                ),
                capability_token=token,
            )

    production_after = store.load_production(run_id)
    assert production_after["revision"] == production_before["revision"]
    assert production_after.get("batches") == production_before.get("batches")


def test_production_apply_rejects_stale_authorization_after_capability_revoke(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T060002-060002"
    _create_production_run(store, run_id)
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)
    token_id = token.split(".", 1)[0]
    service = ProductionAgentService(store, run_id)
    production_before = store.load_production(run_id)

    real_authorize = authorize_mutation

    def authorize_then_revoke(*args: Any, **kwargs: Any) -> Any:
        result = real_authorize(*args, **kwargs)
        store.revoke_capability(run_id, token_id)
        return result

    with patch(
        "top_down_planning.agent_tool.production_service.authorize_mutation",
        side_effect=authorize_then_revoke,
    ):
        with pytest.raises((RevisionConflictError, CapabilityDeniedError)):
            service.apply(
                _batch_apply_request(
                    plan_items=["item-api"],
                    dispositions={"item-api": {"disposition": "completed"}},
                ),
                capability_token=token,
            )

    production_after = store.load_production(run_id)
    assert production_after["revision"] == production_before["revision"]


def test_strict_requests_reject_unknown_null_properties() -> None:
    for operation, example_name in (
        ("plan_apply", "expand-branch"),
        ("production_apply", "batch-result"),
        ("production_request_amendment", "amendment-request"),
        ("production_submit_completion", "completion-claim"),
        ("production_report_blocked", "blocker-report"),
        ("review_record_finding_actions", "review-record-finding-actions"),
    ):
        payload = dict(show_example(example_name)["payload"])
        payload["typo"] = None
        with pytest.raises(RequestError, match="unexpected"):
            validate_agent_request(operation, payload)


def test_plan_transaction_parent_ids_are_non_null_strings() -> None:
    schema = show_schema("plan-transaction")
    add_item = {
        "base_revision": 0,
        "operations": [
            {
                "op": "add_item",
                "temp_id": "item-new",
                "parent_id": None,
                "item": {"title": "New", "kind": "work"},
            }
        ],
    }
    issues = validate_against_schema(add_item, schema)
    assert issues
    move = {
        "base_revision": 0,
        "operations": [
            {
                "op": "move_subtree",
                "item_id": "item-api",
                "new_parent_id": None,
            }
        ],
    }
    assert validate_against_schema(move, schema)


def test_nested_unknown_fields_are_rejected_on_public_requests() -> None:
    payload = dict(show_example("expand-branch")["payload"])
    payload["operations"][0]["typo_field"] = "ignored"
    with pytest.raises(RequestError, match="unexpected|oneOf"):
        validate_agent_request("plan_apply", payload)

    production = dict(show_example("batch-result")["payload"])
    production["outputs"][0]["ouptut_refs"] = ["typo"]
    with pytest.raises(RequestError, match="unexpected"):
        validate_agent_request("production_apply", production)

    production["outputs"] = [{"id": "out-1", "type": "artifact", "ref": "a.txt"}]
    production["contributions"] = [
        {"item_id": "item-api", "ouptut_refs": ["out-1"], "summary": "done"}
    ]
    with pytest.raises(RequestError, match="unexpected"):
        validate_agent_request("production_apply", production)


def test_stale_amendment_completion_and_blocker_requests_conflict(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T060003-060003"
    _create_production_run(store, run_id)
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)
    service = ProductionAgentService(store, run_id)
    revision_n = int(store.load_production(run_id)["revision"])

    service.apply(
        _batch_apply_request(
            plan_items=["item-api"],
            dispositions={"item-api": {"disposition": "completed"}},
            production_revision=revision_n,
        ),
        capability_token=token,
    )
    stale = revision_n
    current = int(store.load_production(run_id)["revision"])
    assert current == stale + 1

    with pytest.raises(RevisionConflictError) as excinfo:
        service.request_amendment(
            {
                "production_revision": stale,
                "evidence": "Need a missing branch.",
                "affected_refs": ["item-root"],
            },
            capability_token=token,
        )
    assert excinfo.value.code == "revision_conflict"
    assert store.load_production(run_id).get("pending_amendment_id") is None

    with pytest.raises(RevisionConflictError):
        service.report_blocked(
            {
                "production_revision": stale,
                "evidence": "Upstream unavailable.",
            },
            capability_token=token,
        )
    assert store.load_production(run_id).get("blocker_report") in (None, {})

    service.apply(
        _batch_apply_request(
            plan_items=["item-ui"],
            dispositions={"item-ui": {"disposition": "completed"}},
            production_revision=current,
        ),
        capability_token=token,
    )
    after_both = int(store.load_production(run_id)["revision"])
    with pytest.raises(RevisionConflictError):
        service.submit_completion(
            {
                "production_revision": current,
                "goal_assessment": "Done.",
            },
            capability_token=token,
        )
    assert store.load_production(run_id).get("completion_claim") in (None, {})
    assert int(store.load_production(run_id)["revision"]) == after_both


def test_stale_focused_review_request_conflicts(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T060004-060004"
    _create_planning_run(store, run_id)
    token = grant_capability(store, run_id, role="planner", phase=PLANNING)
    plan = store.load_plan(run_id)
    stale_revision = int(plan["revision"])
    stale_digest = compute_plan_digest(plan)

    PlanAgentService(store, run_id).apply(
        {
            "base_revision": stale_revision,
            "operations": [
                {
                    "op": "update_item",
                    "item_id": "item-api",
                    "patch": {"title": "API v2"},
                }
            ],
        },
        capability_token=token,
    )
    with pytest.raises(RevisionConflictError):
        ReviewAgentService(store, run_id).request(
            {
                "type": "focused_plan",
                "scope": {"item_ids": ["item-api"]},
                "target_revision": stale_revision,
                "target_digest": stale_digest,
            },
            capability_token=token,
        )
    assert store.list_reviews(run_id) == []


def test_second_artifact_capture_failure_leaves_no_unreferenced_snapshot(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T060005-060005"
    _create_production_run(store, run_id)
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)
    service = ProductionAgentService(store, run_id)

    captured = {"count": 0}
    real_write = store.write_artifact_bytes

    def fail_on_second(*args: Any, **kwargs: Any) -> str:
        captured["count"] += 1
        if captured["count"] == 2:
            raise OSError("simulated second capture failure")
        return real_write(*args, **kwargs)

    with patch.object(store, "write_artifact_bytes", side_effect=fail_on_second):
        with pytest.raises(OSError, match="second capture"):
            service.apply(
                _batch_apply_request(
                    plan_items=["item-api"],
                    dispositions={"item-api": {"disposition": "completed"}},
                    outputs=[
                        {"id": "out-a", "type": "artifact", "ref": "a.txt"},
                        {"id": "out-b", "type": "artifact", "ref": "b.txt"},
                    ],
                ),
                capability_token=token,
            )

    artifacts = store.artifacts_dir(run_id)
    leftover = list(artifacts.glob("*")) if artifacts.is_dir() else []
    assert leftover == []
    production = store.load_production(run_id)
    assert production.get("output_evidence") in (None, [])


def test_cas_conflict_after_capture_leaves_no_unreferenced_snapshot(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T060006-060006"
    _create_production_run(store, run_id)
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)
    service = ProductionAgentService(store, run_id)
    production_before = store.load_production(run_id)

    real_commit = store.commit

    def conflict_after_capture(commit_run_id: str, spec: CommitSpec) -> dict[str, Any]:
        if spec.production is not None:
            from core_tools.persistence import StoreRevisionConflictError

            raise StoreRevisionConflictError(0, 1)
        return real_commit(commit_run_id, spec)

    with patch.object(store, "commit", side_effect=conflict_after_capture):
        with pytest.raises(RevisionConflictError):
            service.apply(
                _batch_apply_request(
                    plan_items=["item-api"],
                    dispositions={"item-api": {"disposition": "completed"}},
                    outputs=[{"id": "out-a", "type": "artifact", "ref": "a.txt"}],
                ),
                capability_token=token,
            )

    artifacts = store.artifacts_dir(run_id)
    leftover = list(artifacts.glob("*")) if artifacts.is_dir() else []
    assert leftover == []
    assert store.load_production(run_id)["revision"] == production_before["revision"]


def test_duplicate_focused_review_create_is_revision_conflict(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T060007-060007"
    _create_planning_run(store, run_id)
    token = grant_capability(store, run_id, role="planner", phase=PLANNING)
    service = ReviewAgentService(store, run_id)
    plan = store.load_plan(run_id)
    payload_api = {
        "type": "focused_plan",
        "scope": {"item_ids": ["item-api"]},
        "target_revision": int(plan["revision"]),
        "target_digest": compute_plan_digest(plan),
    }
    payload_ui = {
        "type": "focused_plan",
        "scope": {"item_ids": ["item-ui"]},
        "target_revision": int(plan["revision"]),
        "target_digest": compute_plan_digest(plan),
    }
    with patch(
        "top_down_planning.agent_tool.review_service._next_focused_loop_id",
        return_value="review-focused-plan-01",
    ):
        first = service.request(payload_api, capability_token=token)
        assert first["ok"] is True
        with pytest.raises(RevisionConflictError):
            service.request(payload_ui, capability_token=token)
    reviews = store.list_reviews(run_id)
    assert len(reviews) == 1


def test_applied_plan_mutation_survives_audit_completion_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T060008-060008"
    _create_planning_run(store, run_id)
    token = grant_capability(store, run_id, role="planner", phase=PLANNING)
    set_capability_token_file(monkeypatch, store, run_id, token)
    request_path = write_agent_request_file(
        store,
        run_id,
        "plan-apply-r0-a01.json",
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
    )

    with patch(
        "top_down_planning.cli.agent.complete_agent_request",
        side_effect=OSError("audit write failed"),
    ):
        result = run_cli(
            [
                "agent",
                "plan",
                "apply",
                "--run",
                run_id,
                "--runs-dir",
                str(tmp_path),
                "--request",
                str(request_path),
            ]
        )

    payload = result.json()
    assert payload.get("applied") is True
    assert payload.get("ok") is True
    assert int(store.load_plan(run_id)["revision"]) == 1

    retry = run_cli(
        [
            "agent",
            "plan",
            "apply",
            "--run",
            run_id,
            "--runs-dir",
            str(tmp_path),
            "--request",
            str(request_path),
        ]
    )
    retry_payload = retry.json()
    assert retry_payload["ok"] is False
    assert retry_payload["error"]["code"] == "revision_conflict"
    assert int(store.load_plan(run_id)["revision"]) == 1


def test_public_response_schemas_are_published() -> None:
    required = {
        "agent-error",
        "plan-apply-response",
        "production-apply-response",
        "run-status-response",
        "focused-review-request-response",
    }
    assert required.issubset(set(PUBLIC_SCHEMAS))
    for name in required:
        schema = show_schema(name)
        assert schema["$schema"].startswith("https://json-schema.org/draft/2020-12/")


def test_plan_apply_response_matches_published_schema(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T060009-060009"
    _create_planning_run(store, run_id)
    token = grant_capability(store, run_id, role="planner", phase=PLANNING)
    result = PlanAgentService(store, run_id).apply(
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
    )
    issues = validate_against_schema(result, SCHEMAS["plan-apply-response"])
    assert issues == []


def test_run_status_uses_coherent_snapshot_not_hybrid_loads(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T060010-060010"
    _create_planning_run(store, run_id)

    class HybridStore:
        def __init__(self, inner: FileRunStore) -> None:
            self._inner = inner

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

        def load_canonical_snapshot(self, loaded_run_id: str) -> Any:
            return self._inner.load_canonical_snapshot(loaded_run_id)

        def load_run(self, loaded_run_id: str) -> dict[str, Any]:
            return self._inner.load_run(loaded_run_id)

        def load_plan(self, loaded_run_id: str) -> dict[str, Any]:
            plan = self._inner.load_plan(loaded_run_id)
            hybrid = dict(plan)
            hybrid["revision"] = int(plan["revision"]) + 99
            return hybrid

        def agent_requests_dir(self, loaded_run_id: str) -> Path:
            return self._inner.agent_requests_dir(loaded_run_id)

        def run_dir(self, loaded_run_id: str) -> Path:
            return self._inner.run_dir(loaded_run_id)

    hybrid = HybridStore(store)
    status = RunAgentService(hybrid, run_id).status()
    run_view = status["run"]
    assert int(run_view["plan_revision"]) == int(store.load_plan(run_id)["revision"])
    assert int(run_view["plan_revision"]) != int(store.load_plan(run_id)["revision"]) + 99
