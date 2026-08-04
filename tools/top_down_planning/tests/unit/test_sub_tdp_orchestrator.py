"""Tests for Sub-TDP phase orchestrator and child driver."""

from __future__ import annotations

from pathlib import Path

from core_tools.provider import StubProvider
from top_down_planning.domain.models import Plan, PlanItem, Scope
from top_down_planning.domain.plan_tree import PLAN_ROOT_ITEM_ID
from top_down_planning.orchestrator.phases import PLAN_VALIDATED, SUB_TDPS, WHOLE_OUTPUT_REVIEW
from top_down_planning.orchestrator.sub_tdps import SubTdpsPhaseOrchestrator
from top_down_planning.orchestrator.sub_tdp_child_driver import (
    child_runs_store_path,
    continue_child_sub_tdp,
    create_child_run,
)
from top_down_planning.domain.sub_tdp_units import SubTdpUnit
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.sub_tdp_state import load_sub_tdp_state
from tests.helpers import (
    apply_production,
    create_run_kwargs,
    done_events,
    whole_plan_approval_record,
)


def _parent_plan(run_id: str) -> Plan:
    root = PlanItem(
        id=PLAN_ROOT_ITEM_ID,
        parent_id=None,
        order_key="0000000000",
        title="Deliver",
        outcome="Deliver the output.",
        kind="aggregate",
    )
    first = PlanItem(
        id="item-a",
        parent_id=PLAN_ROOT_ITEM_ID,
        order_key="0000000000",
        title="Persistence foundation",
        outcome="Persist state reliably.",
        kind="work",
        scope=Scope(includes=["storage"]),
    )
    return Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Ship the product.",
        items={PLAN_ROOT_ITEM_ID: root, "item-a": first},
    )


def _create_parent_at_plan_validated(
    store: FileRunStore,
    workspace: Path,
    run_id: str = "run-20260101T000801-000801",
) -> None:
    config = create_run_kwargs(workspace)["resolved_config"]
    config["execution"] = {"mode": "sub_tdps"}
    kwargs = create_run_kwargs(workspace, resolved_config=config)
    store.create_run(
        run_id,
        plan=_parent_plan(run_id),
        phase=PLAN_VALIDATED,
        **kwargs,
    )
    store.save_review(run_id, whole_plan_approval_record(store, run_id))


def _batch_apply_request(plan_item_id: str, production_revision: int = 0) -> dict:
    return {
        "production_revision": production_revision,
        "plan_items": [plan_item_id],
        "dispositions": {plan_item_id: {"disposition": "completed"}},
        "outputs": [],
        "contributions": [],
        "summary": "batch complete",
        "empty_output": False,
    }


def test_sub_tdps_orchestrator_completes_child_and_synthesizes(tmp_path: Path) -> None:
    from unittest.mock import patch

    store = FileRunStore(tmp_path / "runs")
    workspace = tmp_path
    run_id = "run-20260101T000801-000801"
    _create_parent_at_plan_validated(store, workspace, run_id)
    plan_item_id = "item-a"

    def _stub_continue_child(
        child_store: FileRunStore,
        child_run_id: str,
        *,
        create_provider,
        workspace: Path,
    ) -> dict:
        run = child_store.load_run(child_run_id)
        expected = int(run["revision"])
        run = dict(run)
        run["revision"] = expected + 1
        run["phase"] = "production"
        child_store.save_run(child_run_id, run, expected)
        apply_production(
            child_store,
            child_run_id,
            _batch_apply_request(plan_item_id),
            handler="apply",
        )()
        apply_production(
            child_store,
            child_run_id,
            {"goal_assessment": "Child goal met."},
            handler="submit_completion",
        )()
        run = child_store.load_run(child_run_id)
        expected = int(run["revision"])
        run = dict(run)
        run["revision"] = expected + 1
        run["status"] = "completed"
        run["phase"] = "output_validated"
        run["outcome"] = "accepted"
        child_store.save_run(child_run_id, run, expected)
        return child_store.load_run(child_run_id)

    with patch(
        "top_down_planning.orchestrator.sub_tdps.continue_child_sub_tdp",
        side_effect=_stub_continue_child,
    ):
        result = SubTdpsPhaseOrchestrator(
            store,
            run_id,
            StubProvider(),
        ).run()

    assert result.ok is True
    assert result.phase == WHOLE_OUTPUT_REVIEW
    production = store.load_production(run_id)
    assert production.get("completion_claim") is not None
    state = load_sub_tdp_state(production)
    assert state is not None
    assert state["status"] == "completed"


def test_sub_tdps_orchestrator_rejects_stale_orchestration_state(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    workspace = tmp_path
    run_id = "run-20260101T000803-000803"
    _create_parent_at_plan_validated(store, workspace, run_id)
    production = store.load_production(run_id)
    production["sub_tdps"] = {
        "version": 1,
        "status": "running",
        "active_unit_id": None,
        "units": [
            {
                "id": "item-stale",
                "plan_item_id": "item-stale",
                "title": "Stale",
                "directory": "01-stale",
                "status": "pending",
                "child_run_id": None,
                "notes": [],
            }
        ],
    }
    expected = int(production["revision"])
    production["revision"] = expected + 1
    store.save_production(run_id, production, expected)

    orchestrator = SubTdpsPhaseOrchestrator(store, run_id, StubProvider())
    from top_down_planning.orchestrator.errors import ProviderRunError

    import pytest

    with pytest.raises(ProviderRunError, match="does not match"):
        orchestrator.run()


def test_continue_child_sub_tdp_applies_resume_when_paused(tmp_path: Path) -> None:
    from unittest.mock import MagicMock, patch

    workspace = tmp_path
    unit = SubTdpUnit(
        plan_item_id="item-a",
        title="Persistence foundation",
        outcome="Persist state reliably.",
        directory="01-persistence-foundation",
        ordinal=1,
    )
    parent_config = create_run_kwargs(workspace)["resolved_config"]
    parent_config["execution"] = {"mode": "sub_tdps"}
    from top_down_planning.orchestrator.sub_tdp_artifact_writer import write_sub_tdp_artifacts

    write_sub_tdp_artifacts(workspace, [unit], parent_config=parent_config)
    child_store = FileRunStore(child_runs_store_path(workspace, unit))
    from top_down_planning.orchestrator.sub_tdp_child_driver import (
        child_unit_directory,
        load_child_resolved_config,
    )

    child_config = load_child_resolved_config(child_unit_directory(workspace, unit))
    child_run_id = create_child_run(
        child_store,
        unit,
        child_config=child_config,
        workspace=workspace,
    )
    run = child_store.load_run(child_run_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["status"] = "paused"
    run["stop"] = {
        "code": "provider_turn_failed",
        "category": "operational",
        "phase": "production",
        "message": "paused for test",
    }
    child_store.save_run(child_run_id, run, expected)

    resume_plan = MagicMock()
    engine_result = MagicMock(ok=True)

    def _engine_continue(_run_id: str, **kwargs: object) -> MagicMock:
        run = child_store.load_run(child_run_id)
        expected_revision = int(run["revision"])
        run = dict(run)
        run["revision"] = expected_revision + 1
        run["status"] = "completed"
        run["phase"] = "output_validated"
        run["outcome"] = "accepted"
        run["stop"] = None
        child_store.save_run(child_run_id, run, expected_revision)
        return engine_result

    with patch(
        "top_down_planning.orchestrator.sub_tdp_child_driver.prepare_resume",
        return_value=resume_plan,
    ) as prepare_mock:
        with patch(
            "top_down_planning.orchestrator.sub_tdp_child_driver.apply_resume_plan_atomically",
        ) as apply_mock:
            with patch("top_down_planning.orchestrator.engine.RunEngine") as engine_cls:
                engine_cls.return_value.continue_run.side_effect = _engine_continue
                child_run = continue_child_sub_tdp(
                    child_store,
                    child_run_id,
                    create_provider=lambda _cfg, _ws: StubProvider(),
                    workspace=workspace,
                )

    prepare_mock.assert_called_once()
    apply_mock.assert_called_once()
    assert child_run["phase"] == "output_validated"


def test_continue_child_sub_tdp_skips_already_terminal_child(tmp_path: Path) -> None:
    workspace = tmp_path
    unit = SubTdpUnit(
        plan_item_id="item-a",
        title="Persistence foundation",
        outcome="Persist state reliably.",
        directory="01-persistence-foundation",
        ordinal=1,
    )
    parent_config = create_run_kwargs(workspace)["resolved_config"]
    parent_config["execution"] = {"mode": "sub_tdps"}
    from top_down_planning.orchestrator.sub_tdp_artifact_writer import write_sub_tdp_artifacts

    write_sub_tdp_artifacts(workspace, [unit], parent_config=parent_config)
    child_store = FileRunStore(child_runs_store_path(workspace, unit))
    from top_down_planning.orchestrator.sub_tdp_child_driver import (
        child_unit_directory,
        load_child_resolved_config,
    )

    child_config = load_child_resolved_config(child_unit_directory(workspace, unit))
    child_run_id = create_child_run(
        child_store,
        unit,
        child_config=child_config,
        workspace=workspace,
    )
    run = child_store.load_run(child_run_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["status"] = "completed"
    run["phase"] = "output_validated"
    run["outcome"] = "accepted"
    child_store.save_run(child_run_id, run, expected)

    from unittest.mock import patch

    with patch("top_down_planning.orchestrator.engine.RunEngine") as engine_cls:
        child_run = continue_child_sub_tdp(
            child_store,
            child_run_id,
            create_provider=lambda _cfg, _ws: StubProvider(),
            workspace=workspace,
        )
        engine_cls.assert_not_called()

    assert child_run["phase"] == "output_validated"
