"""Unit tests for the production-phase orchestrator and service."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.agent_tool import ProductionAgentService, RequestError
from top_down_planning.agent_tool.errors import CapabilityDeniedError
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator import ProductionPhaseOrchestrator, ProviderRunError
from top_down_planning.orchestrator.phases import PLAN_VALIDATED, PRODUCTION, WHOLE_OUTPUT_REVIEW
from top_down_planning.persistence import FileRunStore
from core_tools.provider import StubProvider
from tests.helpers import apply_plan, apply_production, create_run_kwargs, done_events, grant_capability, whole_plan_approval_record


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
    run_id: str = "run-20260101T000201-000201",
    *,
    limits: dict | None = None,
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

    run_id = "run-20260101T000201-000201"
    provider.script_turn(done_events(text="producer session start"))
    provider.script_turn(
        done_events(signal="batch_complete", text="production turn"),
        mutate_store=apply_production(
            store,
            run_id,
            _batch_apply_request(
                plan_items=["item-first"],
                dispositions={"item-first": {"disposition": "completed"}},
            ),
            handler="apply",
        ),
    )
    provider.script_turn(
        done_events(signal="batch_complete", text="production turn"),
        mutate_store=lambda: (
            apply_production(
                store,
                run_id,
                _batch_apply_request(
                    plan_items=["item-second"],
                    dispositions={"item-second": {"disposition": "completed"}},
                    production_revision=1,
                ),
                handler="apply",
            )(),
            apply_production(
                store,
                run_id,
                {"goal_assessment": "Output goal is fully met.", "goal_met": True},
                handler="submit_completion",
            )(),
        ),
    )

    result = ProductionPhaseOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    assert result.phase == WHOLE_OUTPUT_REVIEW
    assert result.outcome is None
    assert result.batch_count == 2
    assert result.session_id is not None

    production = store.load_production("run-20260101T000201-000201")
    assert production["dispositions"] == {
        "item-first": "completed",
        "item-second": "completed",
    }
    assert len(production["batches"]) == 2
    assert production["output_revision"] == 2

    run = store.load_run("run-20260101T000201-000201")
    assert run["phase"] == WHOLE_OUTPUT_REVIEW
    assert run["sessions"]["primary_producer_session_id"] == result.session_id


def test_ready_set_blocks_item_with_unmet_dependency(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run_at_plan_validated(store)
    _enter_production_phase(store, "run-20260101T000201-000201")
    service = ProductionAgentService(store, "run-20260101T000201-000201")

    token = grant_capability(store, "run-20260101T000201-000201", role="producer", phase=PRODUCTION)

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
    _enter_production_phase(store, "run-20260101T000201-000201")
    service = ProductionAgentService(store, "run-20260101T000201-000201")

    token = grant_capability(store, "run-20260101T000201-000201", role="producer", phase=PRODUCTION)

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
    _enter_production_phase(store, "run-20260101T000201-000201")
    service = ProductionAgentService(store, "run-20260101T000201-000201")

    token = grant_capability(store, "run-20260101T000201-000201", role="producer", phase=PRODUCTION)

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
    _enter_production_phase(store, "run-20260101T000201-000201")
    service = ProductionAgentService(store, "run-20260101T000201-000201")

    token = grant_capability(store, "run-20260101T000201-000201", role="producer", phase=PRODUCTION)

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
    _enter_production_phase(store, "run-20260101T000201-000201")
    service = ProductionAgentService(store, "run-20260101T000201-000201")

    token = grant_capability(store, "run-20260101T000201-000201", role="producer", phase=PRODUCTION)

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
    production = store.load_production("run-20260101T000201-000201")
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
    run_id = "run-20260101T000201-000201"
    provider.script_turn(done_events(text="producer session start"))
    provider.script_turn(
        done_events(signal="batch_complete", text="production turn"),
        mutate_store=apply_production(
            store,
            run_id,
            _batch_apply_request(
                plan_items=["item-first"],
                dispositions={"item-first": {"disposition": "completed"}},
            ),
            handler="apply",
        ),
    )

    result = ProductionPhaseOrchestrator(store, run_id, provider).run()

    assert result.ok is False
    assert result.outcome == "blocked"
    assert result.reason is not None
    assert "max_batches" in result.reason

    run = store.load_run("run-20260101T000201-000201")
    assert run["phase"] == PRODUCTION
    assert run["status"] == "completed"
    assert run["outcome"] == "blocked"


def test_plan_apply_during_production_is_rejected(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run_at_plan_validated(store)
    provider = StubProvider()
    run_id = "run-20260101T000201-000201"
    provider.script_turn(done_events(text="producer session start"))
    provider.script_turn(
        done_events(signal="batch_complete", text="production turn"),
        mutate_store=apply_plan(
            store,
            run_id,
            base_revision=0,
            operations=[
                {
                    "op": "add_item",
                    "temp_id": "item-x",
                    "parent_id": "item-root",
                    "placement": {"last_child": True},
                    "item": {"kind": "work", "title": "X"},
                }
            ],
            role="producer",
            phase=PRODUCTION,
        ),
    )

    with pytest.raises(CapabilityDeniedError, match="plan_apply"):
        ProductionPhaseOrchestrator(store, run_id, provider).run()


def test_production_apply_rejects_plan_validated_phase(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run_at_plan_validated(store)
    service = ProductionAgentService(store, "run-20260101T000201-000201")

    token = grant_capability(store, "run-20260101T000201-000201", role="producer", phase=PLAN_VALIDATED)

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
    root = PlanItem("item-root", None, "0000000000", "Root", kind="aggregate")
    first = PlanItem("item-first", "item-root", "0000000000", "First", kind="work")
    plan = Plan(
        id="plan-run-20260101T002101-002101",
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
        "run-20260101T002101-002101",
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=config),
        phase=PRODUCTION,
    )
    service = ProductionAgentService(store, "run-20260101T002101-002101")
    token = grant_capability(store, "run-20260101T002101-002101", role="producer", phase=PRODUCTION)

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
    _enter_production_phase(store, "run-20260101T000201-000201")
    service = ProductionAgentService(store, "run-20260101T000201-000201")
    token = grant_capability(store, "run-20260101T000201-000201", role="producer", phase=PRODUCTION)
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
    root = PlanItem("item-root", None, "0000000000", "Root", kind="aggregate")
    first = PlanItem("item-first", "item-root", "0000000000", "First", kind="work")
    plan = Plan(
        id="plan-run-20260101T002101-002101",
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
        "run-20260101T002101-002101",
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=config),
        phase=PLAN_VALIDATED,
    )
    provider = StubProvider()

    with pytest.raises(ProviderRunError, match="approved whole-plan review"):
        ProductionPhaseOrchestrator(store, "run-20260101T002101-002101", provider).run()


def test_resume_preserves_batch_agent_turn_budget(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run_at_plan_validated(store, limits={"max_agent_turns_per_batch": 1})
    run = store.load_run("run-20260101T000201-000201")
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["production_loop"] = {"current_batch_agent_turns": 1}
    store.save_run("run-20260101T000201-000201", run, expected_revision)

    provider = StubProvider()
    provider.script_turn(done_events(text="another production turn"))

    result = ProductionPhaseOrchestrator(store, "run-20260101T000201-000201", provider).run()

    assert result.ok is False
    assert result.outcome == "blocked"
    assert result.reason is not None
    assert "max_agent_turns_per_batch" in result.reason
