"""Regression tests for Sub-TDP code-review blockers (P0/P1)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from core_tools.provider import StubProvider

from top_down_planning.domain.production import completion_claim_asserts_goal_met
from top_down_planning.domain.run_kind import RUN_KIND_PARENT_EXECUTION
from top_down_planning.observability import map_audit_event
from top_down_planning.orchestrator.phases import PRODUCTION, WHOLE_OUTPUT_REVIEW
from top_down_planning.orchestrator.prepared_run_factory import PreparedRunFactory
from top_down_planning.orchestrator.production import (
    ProductionPhaseOrchestrator,
    build_producer_context_manifest,
)
from top_down_planning.orchestrator.sub_tdp_child_driver import (
    PreparedChildResult,
    continue_child_sub_tdp,
)
from top_down_planning.orchestrator.sub_tdps import SubTdpsPhaseOrchestrator
from top_down_planning.package.lineage import (
    accepted_result_digest,
    accepted_result_record,
    upstream_accepted_result_binding,
)
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.digests import compute_config_execution_digest
from top_down_planning.persistence.sub_tdp_state import load_sub_tdp_state
from tests.helpers import accept_child_run, apply_production
from tests.unit.test_prepared_runs import _built_package
from tests.unit.test_sub_tdp_orchestrator import _setup_parent_execution


def _accept_child(child_store: FileRunStore, child_run_id: str) -> dict:
    return accept_child_run(child_store, child_run_id, claim_assessment="Child goal met.")


def test_sub_tdps_synthesis_enters_production_not_whole_output_review(
    tmp_path: Path,
) -> None:
    """After children complete, parent must integrate before whole-output review."""

    store, _package, parent_id, _config = _setup_parent_execution(tmp_path)

    def _stub_continue_child(
        child_store: FileRunStore,
        child_run_id: str,
        *,
        create_provider,
        workspace: Path,
        observability=None,
    ) -> PreparedChildResult:
        child_run = _accept_child(child_store, child_run_id)
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
    assert result.phase == PRODUCTION
    parent_run = store.load_run(parent_id)
    assert parent_run["phase"] == PRODUCTION
    production = store.load_production(parent_id)
    claim = production["completion_claim"]
    assert claim["status"] == "integration_pending"
    assert claim["goal_met"] is False
    assert not completion_claim_asserts_goal_met(claim)


def test_production_does_not_complete_on_integration_pending_claim(
    tmp_path: Path,
) -> None:
    store, package, parent_id, config = _setup_parent_execution(tmp_path)
    production = store.load_production(parent_id)
    production = dict(production)
    expected = int(production["revision"])
    production["revision"] = expected + 1
    production["completion_claim"] = {
        "goal_met": False,
        "status": "integration_pending",
        "goal_assessment": "Children collected; integration pending.",
    }
    plan = store.load_plan_model(parent_id)
    production["dispositions"] = {
        item_id: "completed"
        for item_id, item in plan.items.items()
        if item.kind == "work"
    }
    store.save_production(parent_id, production, expected)

    run = store.load_run(parent_id)
    expected_run = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_run + 1
    run["phase"] = PRODUCTION
    store.save_run(parent_id, run, expected_run)

    orch = ProductionPhaseOrchestrator(store, parent_id, StubProvider())
    assert orch._has_completion_claim() is False

    # goal_met claim should complete the production gate
    production = store.load_production(parent_id)
    expected = int(production["revision"])
    production = dict(production)
    production["revision"] = expected + 1
    production["completion_claim"] = {
        "goal_met": True,
        "goal_assessment": "Integrated and goal met.",
    }
    store.save_production(parent_id, production, expected)
    assert orch._has_completion_claim() is True


def test_whole_output_review_requires_goal_met_claim(tmp_path: Path) -> None:
    from top_down_planning.orchestrator.errors import ProviderRunError
    from top_down_planning.orchestrator.whole_output_review import (
        WholeOutputReviewOrchestrator,
    )

    store, _package, parent_id, _config = _setup_parent_execution(tmp_path)
    production = store.load_production(parent_id)
    expected = int(production["revision"])
    production = dict(production)
    production["revision"] = expected + 1
    production["completion_claim"] = {
        "goal_met": False,
        "status": "integration_pending",
        "goal_assessment": "not yet",
    }
    store.save_production(parent_id, production, expected)

    run = store.load_run(parent_id)
    expected_run = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_run + 1
    run["phase"] = WHOLE_OUTPUT_REVIEW
    store.save_run(parent_id, run, expected_run)

    with pytest.raises(ProviderRunError, match="goal_met"):
        WholeOutputReviewOrchestrator(store, parent_id, StubProvider()).run()


def test_producer_manifest_includes_prepared_execution_for_child(
    tmp_path: Path,
) -> None:
    store, package, _parent_id, config = _setup_parent_execution(tmp_path)
    unit = package.units["item-foundation"]
    child_id = PreparedRunFactory().create_child_run(
        store,
        package,
        unit,
        resolved_config=config,
        invocation={"command": "execute", "observability": {}},
    )
    # Bind prepared-execution fields the same way PreparedUnitExecutor does.
    from top_down_planning.orchestrator.prepared_unit_executor import PreparedUnitExecutor

    PreparedUnitExecutor._ensure_child_package_bindings(
        store,
        child_id,
        package=package,
        unit_id=unit.unit_id,
        upstream=[],
        baseline=[],
    )
    # Inject one upstream attestation for manifest coverage.
    run = store.load_run(child_id)
    expected = int(run["revision"])
    binding = dict(run.get("package_binding") or {})
    binding["upstream_accepted_results"] = [
        upstream_accepted_result_binding(
            {
                "schema_version": 1,
                "package_id": package.manifest.get("package_id"),
                "package_digest": package.manifest.get("package_digest"),
                "unit_id": "item-upstream",
                "unit_plan_digest": "c" * 64,
                "assigned_subtree_digest": "b" * 64,
                "child_run_id": "run-up",
                "output_revision": 1,
                "output_digest": "a" * 64,
                "whole_output_review_id": "review-up-1",
                "whole_output_review_digest": "r" * 64,
                "outcome": "accepted",
                "evidence_digest": "d" * 64,
                "output_refs": [],
                "contributions": [],
                "workspace_changes": {},
                "baseline_context_snapshot_digest": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "baseline_accepted_result_digests": [],
                "final_context_snapshot_digest": "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
                "completion_assessment": "upstream done",
            },
            upstream_contract_digest="b" * 64,
        )
    ]
    run = dict(run)
    run["package_binding"] = binding
    run["revision"] = expected + 1
    store.save_run(child_id, run, expected)

    manifest = build_producer_context_manifest(
        child_id,
        store.load_run(child_id),
        config,
        store.load_plan_model(child_id),
        production=store.load_production(child_id),
        store=store,
    )
    prepared = manifest.get("prepared_execution")
    assert isinstance(prepared, dict)
    assert prepared["unit_id"] == "item-foundation"
    assert prepared["package_id"] == package.manifest.get("package_id")
    assert isinstance(prepared["external_prerequisites"], list)
    assert len(prepared["upstream_accepted_results"]) == 1
    upstream = prepared["upstream_accepted_results"][0]
    assert upstream["output_digest"] == "a" * 64
    assert upstream["upstream_contract_digest"] == "b" * 64
    assert upstream["package_id"] == package.manifest.get("package_id")


def test_map_audit_event_maps_paused_failed_cancelled_child_events() -> None:
    for event_type, category in [
        ("sub_tdp_child_paused", "sub-tdp:paused"),
        ("sub_tdp_child_failed", "sub-tdp:failed"),
        ("sub_tdp_child_cancelled", "sub-tdp:cancelled"),
    ]:
        mapped = map_audit_event(
            {
                "type": event_type,
                "run_id": "run-parent",
                "child_run_id": "run-child",
                "unit_id": "item-a",
            }
        )
        assert mapped is not None
        assert mapped.category == category


def test_continue_child_returns_structured_result_on_rejection(tmp_path: Path) -> None:
    store, package, _parent_id, config = _setup_parent_execution(tmp_path)
    unit = package.units["item-foundation"]
    child_id = PreparedRunFactory().create_child_run(
        store,
        package,
        unit,
        resolved_config=config,
        invocation={"command": "execute", "observability": {}},
    )

    engine_result = MagicMock(ok=True, cancelled=False)

    def _engine_continue(_run_id: str, **kwargs: object) -> MagicMock:
        run = store.load_run(child_id)
        expected_revision = int(run["revision"])
        run = dict(run)
        run["revision"] = expected_revision + 1
        run["status"] = "completed"
        run["phase"] = "output_validated"
        run["outcome"] = "rejected"
        run["stop"] = None
        store.save_run(child_id, run, expected_revision)
        return engine_result

    with patch("top_down_planning.orchestrator.engine.RunEngine") as engine_cls:
        engine_cls.return_value.continue_run.side_effect = _engine_continue
        result = continue_child_sub_tdp(
            store,
            child_id,
            create_provider=lambda _cfg, _ws: StubProvider(),
            workspace=tmp_path,
        )

    assert isinstance(result, PreparedChildResult)
    assert result.ok is False
    assert result.cancelled is False
    assert result.outcome == "rejected"
    assert result.status == "completed"


def test_continue_child_propagates_cancellation(tmp_path: Path) -> None:
    store, package, _parent_id, config = _setup_parent_execution(tmp_path)
    unit = package.units["item-foundation"]
    child_id = PreparedRunFactory().create_child_run(
        store,
        package,
        unit,
        resolved_config=config,
        invocation={"command": "execute", "observability": {}},
    )

    engine_result = MagicMock(ok=False, cancelled=True, reason="cancelled by user")

    def _engine_continue(_run_id: str, **kwargs: object) -> MagicMock:
        run = store.load_run(child_id)
        expected_revision = int(run["revision"])
        run = dict(run)
        run["revision"] = expected_revision + 1
        run["status"] = "paused"
        run["phase"] = "production"
        run["stop"] = {
            "code": "user_cancelled",
            "category": "operational",
            "phase": "production",
            "message": "cancelled by user",
        }
        store.save_run(child_id, run, expected_revision)
        return engine_result

    with patch("top_down_planning.orchestrator.engine.RunEngine") as engine_cls:
        engine_cls.return_value.continue_run.side_effect = _engine_continue
        result = continue_child_sub_tdp(
            store,
            child_id,
            create_provider=lambda _cfg, _ws: StubProvider(),
            workspace=tmp_path,
        )

    assert isinstance(result, PreparedChildResult)
    assert result.cancelled is True
    assert result.ok is False
    assert result.status == "paused"


def test_accepted_result_digest_binds_full_attestation(tmp_path: Path) -> None:
    store, package, _parent_id, config = _setup_parent_execution(tmp_path)
    unit = package.units["item-foundation"]
    child_id = PreparedRunFactory().create_child_run(
        store,
        package,
        unit,
        resolved_config=config,
        invocation={"command": "execute", "observability": {}},
    )
    child_run = _accept_child(store, child_id)
    child_production = store.load_production(child_id)
    record = accepted_result_record(
        child_run=child_run,
        child_production=child_production,
        unit_id=unit.unit_id,
        unit_plan_digest=unit.plan_digest,
        package_id=str(package.manifest.get("package_id") or ""),
        package_digest=str(package.manifest.get("package_digest") or ""),
        assigned_subtree_digest=unit.assigned_subtree_digest,
    )
    assert record["schema_version"] == 1
    assert record["package_id"]
    assert record["outcome"] == "accepted"
    digest = accepted_result_digest(record)
    assert len(digest) == 64
    assert digest != record["output_digest"]


def test_package_validation_checks_config_execution_digest(tmp_path: Path) -> None:
    from top_down_planning.package.execution_validation import (
        validate_resolved_config_against_package,
    )
    from top_down_planning.package.loader import ExecutionPackageError, ExecutionPackageLoader

    store, package_dir, package = _built_package(tmp_path)
    resolved = dict(package.resolved_config)
    # Mutate limits so execution digest drifts while contract digests may still match.
    limits = dict(resolved.get("limits") or {})
    production_limits = dict(limits.get("production") or {})
    production_limits["max_batches"] = int(production_limits.get("max_batches") or 10) + 7
    limits["production"] = production_limits
    resolved["limits"] = limits
    assert compute_config_execution_digest(resolved) != compute_config_execution_digest(
        package.resolved_config
    )
    with pytest.raises(ExecutionPackageError, match="config_execution"):
        validate_resolved_config_against_package(
            resolved,
            package,
            workspace=package.workspace_path,
        )


def test_ensure_state_requires_package_lineage(tmp_path: Path) -> None:
    store, package, parent_id, _config = _setup_parent_execution(tmp_path)
    production = store.load_production(parent_id)
    state = load_sub_tdp_state(production)
    assert state is not None
    state = dict(state)
    state["package_id"] = ""
    state["package_digest"] = ""
    orch = SubTdpsPhaseOrchestrator(store, parent_id, StubProvider())
    with pytest.raises(ValueError, match="package_id"):
        orch._ensure_state_matches_package(state, package)


def test_child_started_not_resumed_on_first_drive(tmp_path: Path) -> None:
    store, package, parent_id, config = _setup_parent_execution(tmp_path)
    events: list[str] = []

    def _stub_continue_child(
        child_store: FileRunStore,
        child_run_id: str,
        *,
        create_provider,
        workspace: Path,
        observability=None,
    ) -> PreparedChildResult:
        # Pause after first child so we can inspect started vs resumed.
        run = child_store.load_run(child_run_id)
        expected = int(run["revision"])
        run = dict(run)
        run["revision"] = expected + 1
        run["status"] = "paused"
        run["phase"] = "production"
        run["stop"] = {
            "code": "provider_turn_failed",
            "category": "operational",
            "phase": "production",
            "message": "pause",
        }
        child_store.save_run(child_run_id, run, expected)
        return PreparedChildResult.from_run(
            child_store.load_run(child_run_id),
            ok=False,
            cancelled=False,
            reason="pause",
        )

    original_append = store.append_event

    def _capture_event(run_id: str, event: dict) -> None:
        events.append(str(event.get("type") or ""))
        return original_append(run_id, event)

    with (
        patch.object(store, "append_event", side_effect=_capture_event),
        patch(
            "top_down_planning.orchestrator.prepared_unit_executor.continue_child_sub_tdp",
            side_effect=_stub_continue_child,
        ),
    ):
        result = SubTdpsPhaseOrchestrator(
            store,
            parent_id,
            StubProvider(),
        ).run()

    assert result.ok is False
    assert "sub_tdp_child_started" in events
    assert "sub_tdp_child_resumed" not in events
    assert "sub_tdp_child_paused" in events
    assert "sub_tdp_child_completed" not in events
