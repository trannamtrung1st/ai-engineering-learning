"""Unit tests for agent request read/completion audit and path enforcement."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from top_down_planning.agent_tool.errors import CapabilityDeniedError, RequestError
from top_down_planning.agent_tool.plan_service import PlanAgentService
from top_down_planning.agent_tool.request_audit import (
    complete_agent_request,
    consume_agent_request,
    map_exception_to_result,
)
from top_down_planning.agent_tool.request_paths import (
    SOURCE_KIND_AGENT_REQUESTS,
    SOURCE_KIND_STDIN,
    assert_run_id_env_matches,
)
from top_down_planning.cli.common import (
    AGENT_REQUESTS_DIR_ENV_VAR,
    RUN_ID_ENV_VAR,
    provider_extra_env,
    store_diagnostics_payload,
)
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator.phases import PLANNING, WHOLE_PLAN_REVIEW
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.commit import CommitSpec
from core_tools.cli import ResolvedRunsDir
from tests.conftest import run_cli
from tests.helpers import (
    create_run_kwargs,
    with_root_contract,
    grant_capability,
    make_review_loop,
    mandatory_scope_review_respond_request,
    minimal_resolved_config,
    prepare_loop_for_scope_review_respond,
    set_capability_token_file,
    write_agent_request_file,
)


def _sample_plan(revision: int = 0) -> Plan:
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        kind="aggregate",
    )
    return Plan(
        id="plan-001",
        revision=revision,
        output_goal="Deliver the output.",
        items={"item-root": root},
    )


def _create_run(store: FileRunStore, run_id: str = "run-20260101T000001-000001") -> None:
    store.create_run(
        run_id,
        plan=_sample_plan(),
        **create_run_kwargs(store.root),
    )


def _apply_request() -> dict:
    return {
        "base_revision": 0,
        "operations": with_root_contract(
            [
                {
                    "op": "add_item",
                    "temp_id": "item-new",
                    "parent_id": "item-root",
                    "placement": {"last_child": True},
                    "item": {"kind": "work", "title": "API", "outcome": "API exists."},
                }
            ]
        ),
    }


def test_provider_extra_env_exports_run_context(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000001-000001"
    _create_run(store, run_id)
    resolved = ResolvedRunsDir(path=tmp_path, source="cli")
    env = provider_extra_env(resolved, run_id=run_id, store=store)
    assert env["TDP_RUNS_DIR"] == str(tmp_path)
    assert env["TDP_RUN_ID"] == run_id
    assert env[AGENT_REQUESTS_DIR_ENV_VAR] == str(tmp_path / run_id / "agent-requests")


def test_provider_extra_env_requires_store_when_run_id_set(tmp_path: Path) -> None:
    run_id = "run-20260101T000001-000001"
    resolved = ResolvedRunsDir(path=tmp_path, source="cli")
    with pytest.raises(ValueError, match="store is required"):
        provider_extra_env(resolved, run_id=run_id, store=None)


def test_consume_agent_request_emits_read_and_completed(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000001-000001"
    _create_run(store, run_id)
    request_path = store.agent_requests_dir(run_id) / "plan-apply-r0-a01.json"
    request_path.write_text(json.dumps(_apply_request()), encoding="utf-8")

    payload, context = consume_agent_request(
        store,
        run_id,
        operation="plan.apply",
        request_path=str(request_path),
    )
    assert payload["base_revision"] == 0
    assert context.source_kind == SOURCE_KIND_AGENT_REQUESTS
    assert context.source.startswith("agent-requests/")

    service = PlanAgentService(store, run_id)
    token = grant_capability(store, run_id, role="planner", phase=PLANNING)
    result = service.apply(payload, capability_token=token, request_audit=context)
    assert result["ok"] is True

    complete_agent_request(store, run_id, context, result="applied")
    events = store.load_events(run_id)
    read_events = [e for e in events if e["type"] == "agent_request_read"]
    completed = [e for e in events if e["type"] == "agent_request_completed"]
    assert len(read_events) == 1
    assert len(completed) == 1
    assert read_events[0]["request_id"] == completed[0]["request_id"]
    assert completed[0]["result"] == "applied"
    assert any(e.get("type") == "plan_applied" and e.get("request_id") for e in events)


def test_malformed_json_emits_rejected_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000001-000001"
    _create_run(store, run_id)
    request_path = store.agent_requests_dir(run_id) / "bad.json"
    request_path.write_text("{not json", encoding="utf-8")
    token = grant_capability(store, run_id, role="planner", phase=PLANNING)
    set_capability_token_file(monkeypatch, store, run_id, token)

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
    assert result.exit_code != 0
    events = store.load_events(run_id)
    assert len([e for e in events if e["type"] == "agent_request_read"]) == 1
    completed = [e for e in events if e["type"] == "agent_request_completed"]
    assert len(completed) == 1
    assert completed[0]["result"] == "rejected"


def test_empty_body_emits_read_and_rejected_completion(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000001-000001"
    _create_run(store, run_id)
    request_path = store.agent_requests_dir(run_id) / "empty.json"
    request_path.write_text("   \n", encoding="utf-8")

    with pytest.raises(RequestError, match="empty"):
        consume_agent_request(
            store,
            run_id,
            operation="plan.apply",
            request_path=str(request_path),
        )

    events = store.load_events(run_id)
    assert len([e for e in events if e["type"] == "agent_request_read"]) == 1
    completed = [e for e in events if e["type"] == "agent_request_completed"]
    assert len(completed) == 0


def test_empty_body_cli_emits_read_and_rejected_completion(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000001-000001"
    _create_run(store, run_id)
    request_path = store.agent_requests_dir(run_id) / "empty.json"
    request_path.write_text("", encoding="utf-8")

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
    assert result.exit_code != 0
    events = store.load_events(run_id)
    assert len([e for e in events if e["type"] == "agent_request_read"]) == 1
    completed = [e for e in events if e["type"] == "agent_request_completed"]
    assert len(completed) == 1
    assert completed[0]["result"] == "rejected"


def test_io_failure_before_read_emits_no_request_events(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000001-000001"
    _create_run(store, run_id)
    missing = tmp_path / "missing-request.json"

    with pytest.raises(RequestError, match="not found"):
        consume_agent_request(
            store,
            run_id,
            operation="plan.apply",
            request_path=str(missing),
        )
    assert not [
        event
        for event in store.load_events(run_id)
        if event["type"].startswith("agent_request")
    ]


def test_post_read_persistence_failure_emits_failed_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000001-000001"
    _create_run(store, run_id)
    request_path = store.agent_requests_dir(run_id) / "plan-apply-r0-a01.json"
    request_path.write_text(json.dumps(_apply_request()), encoding="utf-8")
    token = grant_capability(store, run_id, role="planner", phase=PLANNING)
    set_capability_token_file(monkeypatch, store, run_id, token)

    def boom(*_args: object, **_kwargs: object) -> dict:
        raise RuntimeError("simulated persistence failure")

    with patch("top_down_planning.cli.agent.PlanAgentService.apply", side_effect=boom):
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
    assert result.exit_code != 0
    events = store.load_events(run_id)
    assert len([e for e in events if e["type"] == "agent_request_read"]) == 1
    completed = [e for e in events if e["type"] == "agent_request_completed"]
    assert len(completed) == 1
    assert completed[0]["result"] == "failed"


def test_stdin_records_source_kind_stdin(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000001-000001"
    _create_run(store, run_id)
    payload, context = consume_agent_request(
        store,
        run_id,
        operation="plan.apply",
        stdin=StringIO(json.dumps(_apply_request())),
    )
    assert payload["base_revision"] == 0
    assert context.source_kind == SOURCE_KIND_STDIN
    assert context.source == "stdin"


def test_path_outside_agent_requests_is_rejected(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000001-000001"
    _create_run(store, run_id)
    external = tmp_path / "outside.json"
    external.write_text(json.dumps(_apply_request()), encoding="utf-8")

    with pytest.raises(RequestError, match="inside"):
        consume_agent_request(
            store,
            run_id,
            operation="plan.apply",
            request_path=str(external),
        )
    assert not [
        event
        for event in store.load_events(run_id)
        if event["type"].startswith("agent_request")
    ]


def test_stale_run_id_env_without_capability_does_not_reject_run_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000001-000001"
    _create_run(store, run_id)
    monkeypatch.setenv(RUN_ID_ENV_VAR, "run-other")
    request_path = store.agent_requests_dir(run_id) / "plan-apply-r0-a01.json"
    request_path.write_text(json.dumps(_apply_request()), encoding="utf-8")
    payload, _ = consume_agent_request(
        store,
        run_id,
        operation="plan.apply",
        request_path=str(request_path),
    )
    assert payload["base_revision"] == 0


def test_capability_run_id_mismatch_rejected_before_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000001-000001"
    _create_run(store, run_id)
    token = grant_capability(store, run_id, role="planner", phase=PLANNING)
    set_capability_token_file(monkeypatch, store, run_id, token)
    monkeypatch.setenv(RUN_ID_ENV_VAR, "run-other")
    request_path = store.agent_requests_dir(run_id) / "plan.json"
    request_path.write_text("{}", encoding="utf-8")

    with pytest.raises(RequestError, match="TDP_RUN_ID"):
        assert_run_id_env_matches(run_id, capability_token=token)


def test_map_exception_to_result() -> None:
    assert map_exception_to_result(RequestError("bad")) == "rejected"
    assert map_exception_to_result(CapabilityDeniedError("denied")) == "rejected"
    assert map_exception_to_result(RuntimeError("boom")) == "failed"


def test_status_commands_include_agent_requests_dir(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000001-000001"
    _create_run(store, run_id)
    resolved = ResolvedRunsDir(path=tmp_path, source="cli")
    diagnostics = store_diagnostics_payload(resolved, run_id=run_id, store=store)
    assert diagnostics["agent_requests_dir"] == str(
        tmp_path / run_id / "agent-requests"
    )

    with patch("top_down_planning.cli.user.emit_message"):
        status = run_cli(["status", "--run", run_id, "--runs-dir", str(tmp_path), "--stream-json"])
    payload = json.loads(status.stdout)
    assert payload["agent_requests_dir"] == str(tmp_path / run_id / "agent-requests")

    agent_status = run_cli(
        ["agent", "run", "status", "--run", run_id, "--runs-dir", str(tmp_path)]
    )
    agent_payload = json.loads(agent_status.stdout)
    assert agent_payload["agent_requests_dir"] == str(
        tmp_path / run_id / "agent-requests"
    )


def test_transaction_rollback_does_not_remove_agent_requests_files(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000001-000001"
    _create_run(store, run_id)
    request_path = write_agent_request_file(
        store,
        run_id,
        "plan-apply-r0-a01.json",
        _apply_request(),
    )
    run = store.load_run(run_id)
    plan = store.load_plan(run_id)
    run_expected = int(run["revision"])
    plan_expected = int(plan["revision"])
    run = dict(run)
    run["revision"] = run_expected + 1
    plan = dict(plan)
    plan["revision"] = plan_expected + 1

    original_replace = Path.replace
    calls = 0

    def crash_on_first_replace(self: Path, target: Path) -> Path:
        nonlocal calls
        self_parts = self.parts
        target_parts = target.parts
        if any(part.startswith(".txn-") for part in self_parts) and not any(
            part.startswith(".txn-") for part in target_parts
        ):
            calls += 1
            if calls == 1:
                raise OSError("simulated crash")
        return original_replace(self, target)

    with patch.object(Path, "replace", crash_on_first_replace):
        with pytest.raises(OSError, match="simulated crash"):
            store.commit(
                run_id,
                CommitSpec(
                    run=run,
                    run_expected_revision=run_expected,
                    plan=plan,
                    plan_expected_revision=plan_expected,
                    events=[{"type": "test_commit", "run_id": run_id}],
                ),
            )

    recovered = FileRunStore(tmp_path)
    assert request_path.exists()
    assert recovered.load_plan(run_id)["revision"] == plan_expected


def test_plan_commit_rollback_preserves_prior_agent_request_events(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000001-000001"
    _create_run(store, run_id)
    request_path = store.agent_requests_dir(run_id) / "plan-apply-r0-a01.json"
    request_path.write_text(json.dumps(_apply_request()), encoding="utf-8")

    payload, context = consume_agent_request(
        store,
        run_id,
        operation="plan.apply",
        request_path=str(request_path),
    )
    complete_agent_request(store, run_id, context, result="rejected")
    events_before = [
        event
        for event in store.load_events(run_id)
        if event["type"].startswith("agent_request")
    ]
    assert len(events_before) == 2

    run = store.load_run(run_id)
    plan = store.load_plan(run_id)
    run_expected = int(run["revision"])
    plan_expected = int(plan["revision"])
    run = dict(run)
    run["revision"] = run_expected + 1
    plan = dict(plan)
    plan["revision"] = plan_expected + 1

    original_replace = Path.replace
    calls = 0

    def crash_on_first_replace(self: Path, target: Path) -> Path:
        nonlocal calls
        self_parts = self.parts
        target_parts = target.parts
        if any(part.startswith(".txn-") for part in self_parts) and not any(
            part.startswith(".txn-") for part in target_parts
        ):
            calls += 1
            if calls == 1:
                raise OSError("simulated crash")
        return original_replace(self, target)

    with patch.object(Path, "replace", crash_on_first_replace):
        with pytest.raises(OSError, match="simulated crash"):
            store.commit(
                run_id,
                CommitSpec(
                    run=run,
                    run_expected_revision=run_expected,
                    plan=plan,
                    plan_expected_revision=plan_expected,
                    events=[{"type": "test_commit", "run_id": run_id}],
                ),
            )

    recovered = FileRunStore(tmp_path)
    assert recovered.load_plan(run_id)["revision"] == plan_expected
    events_after = [
        event
        for event in recovered.load_events(run_id)
        if event["type"].startswith("agent_request")
    ]
    assert events_after == events_before
    assert payload["base_revision"] == 0


def test_review_respond_under_agent_requests_records_request_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000001-000001"
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Deliver the output",
        outcome="Deliver the output.",
        kind="aggregate",
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver.",
        items={"item-root": root},
    )
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
        phase=WHOLE_PLAN_REVIEW,
    )
    loop_id = "review-whole-plan-01"
    loop = make_review_loop(
        id=loop_id,
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=0,
        scope={"kind": "whole_plan"},
        status="pending",
        lifecycle_status="review_pending",
        active_stage=None,
        finding_set_id="review-whole-plan-01-fs-01",
        revise_at="major",
    )
    store.save_review(run_id, loop.to_dict())
    prepare_loop_for_scope_review_respond(
        store,
        run_id,
        loop_id,
        target_revision=0,
    )
    token = grant_capability(
        store,
        run_id,
        role="reviewer",
        phase=WHOLE_PLAN_REVIEW,
        loop_id=loop_id,
        session_id="sess",
    )
    set_capability_token_file(monkeypatch, store, run_id, token)
    request_path = write_agent_request_file(
        store,
        run_id,
        "review-respond-scope-r0-a01.json",
        mandatory_scope_review_respond_request(
            store,
            run_id,
            loop_id=loop_id,
            target_revision=0,
            review_type="whole_plan",
        ),
    )

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
    assert result.exit_code == 0, result.stderr
    events = store.load_events(run_id)
    read_events = [e for e in events if e["type"] == "agent_request_read"]
    completed = [e for e in events if e["type"] == "agent_request_completed"]
    responded = [e for e in events if e["type"] == "review_responded"]
    assert len(read_events) == 1
    assert len(completed) == 1
    assert completed[0]["result"] == "applied"
    assert len(responded) == 1
    assert responded[0]["request_id"] == read_events[0]["request_id"]
    assert store.load_review(run_id, loop_id)["id"] == loop_id
