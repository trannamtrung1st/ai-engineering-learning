"""Tests for prepared parent Sub-TDP orchestrator."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from core_tools.provider import StubProvider
from top_down_planning.domain.run_kind import RUN_KIND_PARENT_EXECUTION
from top_down_planning.orchestrator.phases import PRODUCTION, SUB_TDPS
from top_down_planning.orchestrator.prepared_run_factory import PreparedRunFactory
from top_down_planning.orchestrator.sub_tdps import SubTdpsPhaseOrchestrator
from top_down_planning.orchestrator.sub_tdp_child_driver import continue_child_sub_tdp
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.sub_tdp_state import (
    initial_sub_tdp_state_from_package,
    load_sub_tdp_state,
    merge_sub_tdp_state_into_production,
)
from tests.helpers import accept_child_run, create_run_kwargs
from tests.unit.test_prepared_runs import _built_package


def _setup_parent_execution(
    tmp_path: Path,
    *,
    run_id: str = "run-20260101T000801-000801",
):
    store, _, package = _built_package(tmp_path)
    config = create_run_kwargs(tmp_path)["resolved_config"]
    parent_id = PreparedRunFactory().create_parent_run(
        store,
        package,
        resolved_config=config,
        invocation={"command": "execute", "observability": {}},
    )
    production = store.load_production(parent_id)
    units = [
        __import__(
            "top_down_planning.domain.sub_tdp_units",
            fromlist=["SubTdpUnit"],
        ).SubTdpUnit(
            plan_item_id=unit.unit_id,
            title=unit.title,
            outcome="",
            directory=unit.plan_file.parent.name,
            ordinal=unit.ordinal,
        )
        for unit in sorted(package.units.values(), key=lambda item: item.ordinal)
    ]
    state = initial_sub_tdp_state_from_package(
        package.manifest,
        manifest_path=str(package.manifest_path),
        units=units,
        package_units=package.units,
    )
    merged = merge_sub_tdp_state_into_production(production, state)
    expected_revision = int(production["revision"])
    merged["revision"] = expected_revision + 1
    store.save_production(parent_id, merged, expected_revision)
    return store, package, parent_id, config


def test_sub_tdps_orchestrator_completes_child_and_synthesizes(tmp_path: Path) -> None:
    store, package, parent_id, _config = _setup_parent_execution(tmp_path)

    def _stub_continue_child(
        child_store: FileRunStore,
        child_run_id: str,
        *,
        create_provider,
        workspace: Path,
        observability=None,
    ):
        from top_down_planning.orchestrator.sub_tdp_child_driver import PreparedChildResult

        child_run = accept_child_run(
            child_store, child_run_id, claim_assessment="Child goal met."
        )
        return PreparedChildResult.from_run(child_run, ok=True)

    with patch(
        "top_down_planning.orchestrator.prepared_unit_executor.continue_child_sub_tdp",
        side_effect=_stub_continue_child,
    ):
        result = SubTdpsPhaseOrchestrator(
            store,
            parent_id,
            StubProvider(),
        ).run()

    assert result.ok is True
    # Synthesis enters parent integration production before whole-output review.
    from top_down_planning.orchestrator.phases import PRODUCTION

    assert result.phase == PRODUCTION
    parent_run = store.load_run(parent_id)
    assert parent_run.get("run_kind") == RUN_KIND_PARENT_EXECUTION
    assert parent_run["phase"] == PRODUCTION
    production = store.load_production(parent_id)
    assert production.get("completion_claim") is not None
    assert production["completion_claim"]["status"] == "integration_pending"
    state = load_sub_tdp_state(production)
    assert state is not None
    assert state["status"] == "completed"


def test_sub_tdps_orchestrator_rejects_stale_orchestration_state(tmp_path: Path) -> None:
    store, _package, parent_id, _config = _setup_parent_execution(tmp_path)
    production = store.load_production(parent_id)
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
    store.save_production(parent_id, production, expected)

    from top_down_planning.orchestrator.errors import ProviderRunError

    import pytest

    with pytest.raises(ProviderRunError, match="does not match"):
        SubTdpsPhaseOrchestrator(store, parent_id, StubProvider()).run()


def test_continue_child_sub_tdp_applies_resume_when_paused(tmp_path: Path) -> None:
    from unittest.mock import MagicMock

    store, package, _parent_id, config = _setup_parent_execution(tmp_path)
    unit = package.units["item-foundation"]
    child_id = PreparedRunFactory().create_child_run(
        store,
        package,
        unit,
        resolved_config=config,
        invocation={"command": "execute", "observability": {}},
    )
    run = store.load_run(child_id)
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
    store.save_run(child_id, run, expected)

    resume_plan = MagicMock()
    engine_result = MagicMock(ok=True)

    def _engine_continue(_run_id: str, **kwargs: object) -> MagicMock:
        run = store.load_run(child_id)
        expected_revision = int(run["revision"])
        run = dict(run)
        run["revision"] = expected_revision + 1
        run["status"] = "completed"
        run["phase"] = "output_validated"
        run["outcome"] = "accepted"
        run["stop"] = None
        store.save_run(child_id, run, expected_revision)
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
                    store,
                    child_id,
                    create_provider=lambda _cfg, _ws: StubProvider(),
                    workspace=tmp_path,
                )

    prepare_mock.assert_called_once()
    apply_mock.assert_called_once()
    assert child_run.ok is True
    assert child_run.run["phase"] == "output_validated"


def test_continue_child_sub_tdp_skips_already_terminal_child(tmp_path: Path) -> None:
    store, package, _parent_id, config = _setup_parent_execution(tmp_path)
    unit = package.units["item-foundation"]
    child_id = PreparedRunFactory().create_child_run(
        store,
        package,
        unit,
        resolved_config=config,
        invocation={"command": "execute", "observability": {}},
    )
    run = store.load_run(child_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["status"] = "completed"
    run["phase"] = "output_validated"
    run["outcome"] = "accepted"
    store.save_run(child_id, run, expected)

    with patch("top_down_planning.orchestrator.engine.RunEngine") as engine_cls:
        child_run = continue_child_sub_tdp(
            store,
            child_id,
            create_provider=lambda _cfg, _ws: StubProvider(),
            workspace=tmp_path,
        )
        engine_cls.assert_not_called()

    assert child_run.ok is True
    assert child_run.run["phase"] == "output_validated"
