"""Unit tests for the production-phase orchestrator and service."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.agent_tool import ProductionAgentService, RequestError
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator import ProductionPhaseOrchestrator, ProviderRunError
from top_down_planning.orchestrator.phases import PLAN_VALIDATED, PRODUCTION, WHOLE_OUTPUT_REVIEW
from top_down_planning.persistence import FileRunStore
from core_tools.provider import StubProvider
from tests.helpers import create_run_kwargs, done_events, grant_capability, whole_plan_approval_record


def _batch_apply_request(
    *,
    plan_items: list[str],
    dispositions: dict,
    empty_output: bool = False,
    empty_output_reason: str | None = None,
    production_revision: int = 0,
) -> dict:
    return {
        "production_revision": production_revision,
        "plan_items": plan_items,
        "dispositions": dispositions,
        "outputs": [],
        "contributions": [],
        "summary": "batch complete",
        "empty_output": empty_output,
        "empty_output_reason": empty_output_reason,
    }


def _create_run_at_plan_validated(
    store: FileRunStore,
    run_id: str = "run-production",
    *,
    limits: dict | None = None,
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
    if limits:
        config["limits"]["production"].update(limits)

    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=config),
        phase=PLAN_VALIDATED,
    )
    store.save_review(run_id, whole_plan_approval_record(store, run_id))


def _enter_production_phase(store: FileRunStore, run_id: str) -> None:
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["phase"] = PRODUCTION
    store.save_run(run_id, run, expected_revision)


def test_production_phase_completes_two_batches_with_all_items_terminal(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    _create_run_at_plan_validated(store)
    provider = StubProvider()

    provider.script_turn(
        [
            {
                "type": "tool_call",
                "tool": "production_apply",
                "role": "producer",
                "request": _batch_apply_request(
                    plan_items=["item-first"],
                    dispositions={"item-first": {"disposition": "completed"}},
                ),
            },
            *done_events(signal="batch_complete", text="production turn"),
        ]
    )
    provider.script_turn(
        [
            {
                "type": "tool_call",
                "tool": "production_apply",
                "role": "producer",
                "request": _batch_apply_request(
                    plan_items=["item-second"],
                    dispositions={"item-second": {"disposition": "completed"}},
                    production_revision=1,
                ),
            },
            {
                "type": "tool_call",
                "tool": "production_submit_completion",
                "role": "producer",
                "request": {"goal_assessment": "Output goal is fully met.", "goal_met": True},
            },
            *done_events(signal="batch_complete", text="production turn"),
        ]
    )

    result = ProductionPhaseOrchestrator(store, "run-production", provider).run()

    assert result.ok is True
    assert result.phase == WHOLE_OUTPUT_REVIEW
    assert result.outcome is None
    assert result.batch_count == 2
    assert result.session_id is not None

    production = store.load_production("run-production")
    assert production["dispositions"] == {
        "item-first": "completed",
        "item-second": "completed",
    }
    assert len(production["batches"]) == 2
    assert production["output_revision"] == 2

    run = store.load_run("run-production")
    assert run["phase"] == WHOLE_OUTPUT_REVIEW
    assert run["sessions"]["primary_producer_session_id"] == result.session_id


def test_ready_set_blocks_item_with_unmet_dependency(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run_at_plan_validated(store)
    _enter_production_phase(store, "run-production")
    service = ProductionAgentService(store, "run-production")

    token = grant_capability(store, "run-production", role="producer", phase=PRODUCTION)

    with pytest.raises(RequestError, match="not in the ready set"):
        service.apply(
            _batch_apply_request(
                plan_items=["item-second"],
                dispositions={"item-second": {"disposition": "completed"}},
            ),
            capability_token=token,
        )


def test_not_applicable_requires_reason(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run_at_plan_validated(store)
    _enter_production_phase(store, "run-production")
    service = ProductionAgentService(store, "run-production")

    token = grant_capability(store, "run-production", role="producer", phase=PRODUCTION)

    with pytest.raises(RequestError, match="not_applicable requires reason"):
        service.apply(
            _batch_apply_request(
                plan_items=["item-first"],
                dispositions={"item-first": {"disposition": "not_applicable"}},
            ),
            capability_token=token,
        )


def test_superseded_requires_replacement_ref(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run_at_plan_validated(store)
    _enter_production_phase(store, "run-production")
    service = ProductionAgentService(store, "run-production")

    token = grant_capability(store, "run-production", role="producer", phase=PRODUCTION)

    with pytest.raises(RequestError, match="superseded requires replacement_ref"):
        service.apply(
            _batch_apply_request(
                plan_items=["item-first"],
                dispositions={"item-first": {"disposition": "superseded"}},
            ),
            capability_token=token,
        )


def test_blocked_requires_evidence(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run_at_plan_validated(store)
    _enter_production_phase(store, "run-production")
    service = ProductionAgentService(store, "run-production")

    token = grant_capability(store, "run-production", role="producer", phase=PRODUCTION)

    with pytest.raises(RequestError, match="blocked requires evidence"):
        service.apply(
            _batch_apply_request(
                plan_items=["item-first"],
                dispositions={"item-first": {"disposition": "blocked"}},
            ),
            capability_token=token,
        )

    result = service.apply(
        _batch_apply_request(
            plan_items=["item-first"],
            dispositions={
                "item-first": {
                    "disposition": "blocked",
                    "evidence": "Upstream dependency unavailable.",
                }
            },
        ),
        capability_token=token,
    )
    assert result["ok"] is True


def test_empty_output_batch_persists_justification(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run_at_plan_validated(store)
    _enter_production_phase(store, "run-production")
    service = ProductionAgentService(store, "run-production")

    token = grant_capability(store, "run-production", role="producer", phase=PRODUCTION)

    result = service.apply(
        _batch_apply_request(
            plan_items=["item-first"],
            dispositions={
                "item-first": {
                    "disposition": "satisfied_without_change",
                }
            },
            empty_output=True,
            empty_output_reason="Existing output already satisfies this item.",
        ),
        capability_token=token,
    )

    assert result["ok"] is True
    production = store.load_production("run-production")
    batch = production["batches"][0]
    assert batch["result"]["empty_output"] is True
    assert (
        batch["result"]["empty_output_reason"]
        == "Existing output already satisfies this item."
    )


def test_max_batches_exhaustion_yields_blocked_not_accepted(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run_at_plan_validated(store, limits={"max_batches": 1})
    provider = StubProvider()
    provider.script_turn(
        [
            {
                "type": "tool_call",
                "tool": "production_apply",
                "role": "producer",
                "request": _batch_apply_request(
                    plan_items=["item-first"],
                    dispositions={"item-first": {"disposition": "completed"}},
                ),
            },
            *done_events(signal="batch_complete", text="production turn"),
        ]
    )

    result = ProductionPhaseOrchestrator(store, "run-production", provider).run()

    assert result.ok is False
    assert result.outcome == "blocked"
    assert result.reason is not None
    assert "max_batches" in result.reason

    run = store.load_run("run-production")
    assert run["phase"] == PRODUCTION
    assert run["status"] == "completed"
    assert run["outcome"] == "blocked"


def test_plan_apply_during_production_is_rejected(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run_at_plan_validated(store)
    provider = StubProvider()
    provider.script_turn(
        [
            {
                "type": "tool_call",
                "tool": "plan_apply",
                "role": "producer",
                "request": {
                    "base_revision": 0,
                    "operations": [
                        {
                            "op": "add_item",
                            "temp_id": "item-x",
                            "parent_id": "item-root",
                            "placement": {"last_child": True},
                            "item": {"title": "X"},
                        }
                    ],
                },
            },
            *done_events(signal="batch_complete", text="production turn"),
        ]
    )

    with pytest.raises(ProviderRunError, match="plan mutations are not allowed"):
        ProductionPhaseOrchestrator(store, "run-production", provider).run()


def test_production_apply_rejects_plan_validated_phase(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run_at_plan_validated(store)
    service = ProductionAgentService(store, "run-production")

    token = grant_capability(store, "run-production", role="producer", phase=PLAN_VALIDATED)

    with pytest.raises(RequestError, match="whole-output review phases"):
        service.apply(
            _batch_apply_request(
                plan_items=["item-first"],
                dispositions={"item-first": {"disposition": "completed"}},
            ),
            capability_token=token,
        )


def test_production_apply_rejects_missing_plan_approval(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    root = PlanItem("item-root", None, "0000000000", "Root")
    first = PlanItem("item-first", "item-root", "0000000000", "First")
    plan = Plan(
        id="plan-run-unapproved",
        revision=0,
        output_goal="Deliver.",
        items={"item-root": root, "item-first": first},
    )
    config = {
        "run": {"output_goal": "Deliver.", "input_refs": []},
        "planning": {"stop_hint": "Stop.", "max_depth": 4, "max_expansion_per_item": 7},
        "limits": {"production": {"max_batches": 50, "max_agent_turns_per_batch": 10}},
        "provider": {"name": "stub"},
    }
    store.create_run(
        "run-unapproved",
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=config),
        phase=PRODUCTION,
    )
    service = ProductionAgentService(store, "run-unapproved")
    token = grant_capability(store, "run-unapproved", role="producer", phase=PRODUCTION)

    with pytest.raises(RequestError, match="approved whole-plan review"):
        service.apply(
            _batch_apply_request(
                plan_items=["item-first"],
                dispositions={"item-first": {"disposition": "completed"}},
            ),
            capability_token=token,
        )


def test_production_apply_rejects_already_terminal_item(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run_at_plan_validated(store)
    _enter_production_phase(store, "run-production")
    service = ProductionAgentService(store, "run-production")
    token = grant_capability(store, "run-production", role="producer", phase=PRODUCTION)
    service.apply(
        _batch_apply_request(
            plan_items=["item-first"],
            dispositions={"item-first": {"disposition": "completed"}},
        ),
        capability_token=token,
    )

    with pytest.raises(RequestError, match="already have terminal disposition"):
        service.apply(
            _batch_apply_request(
                plan_items=["item-first"],
                dispositions={"item-first": {"disposition": "completed"}},
                production_revision=1,
            ),
            capability_token=token,
        )


def test_production_without_plan_approval_is_rejected(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    root = PlanItem("item-root", None, "0000000000", "Root")
    first = PlanItem("item-first", "item-root", "0000000000", "First")
    plan = Plan(
        id="plan-run-unapproved",
        revision=0,
        output_goal="Deliver.",
        items={"item-root": root, "item-first": first},
    )
    config = {
        "run": {"output_goal": "Deliver.", "input_refs": []},
        "planning": {"stop_hint": "Stop.", "max_depth": 4, "max_expansion_per_item": 7},
        "limits": {"production": {"max_batches": 50, "max_agent_turns_per_batch": 10}},
        "provider": {"name": "stub"},
    }
    store.create_run(
        "run-unapproved",
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=config),
        phase=PLAN_VALIDATED,
    )
    provider = StubProvider()

    with pytest.raises(ProviderRunError, match="approved whole-plan review"):
        ProductionPhaseOrchestrator(store, "run-unapproved", provider).run()


def test_resume_preserves_batch_agent_turn_budget(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run_at_plan_validated(store, limits={"max_agent_turns_per_batch": 1})
    run = store.load_run("run-production")
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["production_loop"] = {"current_batch_agent_turns": 1}
    store.save_run("run-production", run, expected_revision)

    provider = StubProvider()
    provider.script_turn(done_events(text="another production turn"))

    result = ProductionPhaseOrchestrator(store, "run-production", provider).run()

    assert result.ok is False
    assert result.outcome == "blocked"
    assert result.reason is not None
    assert "max_agent_turns_per_batch" in result.reason
