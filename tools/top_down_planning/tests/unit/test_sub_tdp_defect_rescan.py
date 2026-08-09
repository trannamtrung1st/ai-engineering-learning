"""Failing-reproduction tests for Sub-TDP defect rescan (stop codes, pause, attach, WOR)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.persistence import PersistenceError
from core_tools.provider import StubProvider
from top_down_planning.domain.run_kind import RUN_KIND_PARENT_EXECUTION
from top_down_planning.domain.run_lifecycle import (
    PAUSED_STOP_CODES,
    validate_stop_record,
)
from top_down_planning.orchestrator.errors import ProviderRunError
from top_down_planning.orchestrator.phases import SUB_TDPS, WHOLE_OUTPUT_REVIEW
from top_down_planning.orchestrator.prepared_unit_executor import PreparedUnitExecutor
from top_down_planning.orchestrator.resume_stop_validators import (
    validate_stop_for_resume_apply,
)
from top_down_planning.orchestrator.sub_tdp_child_driver import PreparedChildResult
from top_down_planning.orchestrator.sub_tdps import SubTdpsPhaseOrchestrator
from top_down_planning.orchestrator.whole_output_review import (
    SubTdpWholeOutputReviewAdapter,
    WholeOutputReviewOrchestrator,
)
from top_down_planning.package.lineage import accepted_result_digest
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.sub_tdp_state import load_sub_tdp_state
from tests.conftest import run_cli
from tests.helpers import (
    accept_child_run,
    create_run_kwargs,
    decorate_sub_tdp_v2_package,
    goal_met_completion_claim,
    mirrored_production_batch,
    whole_plan_approval_record,
)
from tests.unit.test_prepared_runs import _built_package
from tests.unit.test_sub_tdp_attach_cli import _parent_with_orchestration
from tests.unit.test_sub_tdp_orchestrator import _setup_parent_execution


@pytest.mark.parametrize(
    "code",
    [
        "sub_tdp_dependency_unmet",
        "sub_tdp_child_failed",
        "sub_tdp_child_paused",
    ],
)
def test_sub_tdp_operational_stop_codes_are_valid_paused_codes(code: str) -> None:
    assert code in PAUSED_STOP_CODES
    validate_stop_record(
        {
            "code": code,
            "category": "operational",
            "phase": SUB_TDPS,
            "message": "pause",
            "role": None,
            "details": {},
        },
        expected_category="operational",
    )


def test_resume_apply_accepts_sub_tdp_child_failed_stop(tmp_path: Path) -> None:
    store, package, parent_id, _config = _setup_parent_execution(tmp_path)
    run = store.load_run(parent_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["status"] = "paused"
    run["phase"] = SUB_TDPS
    run["stop"] = {
        "code": "sub_tdp_child_failed",
        "category": "operational",
        "phase": SUB_TDPS,
        "message": "child failed",
        "role": None,
        "details": {},
    }
    store.save_run(parent_id, run, expected)
    # Must not raise — resume apply must recognize the stop code.
    validate_stop_for_resume_apply(
        store, parent_id, store.load_run(parent_id), run["stop"]
    )


def test_child_pause_pauses_parent_with_valid_stop(tmp_path: Path) -> None:
    store, package, parent_id, config = _setup_parent_execution(tmp_path)

    def _stub_continue_child(
        child_store: FileRunStore,
        child_run_id: str,
        *,
        create_provider,
        workspace: Path,
        observability=None,
    ) -> PreparedChildResult:
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
            "role": None,
            "details": {},
        }
        child_store.save_run(child_run_id, run, expected)
        return PreparedChildResult.from_run(
            child_store.load_run(child_run_id),
            ok=False,
            cancelled=False,
            reason="pause",
        )

    with patch(
        "top_down_planning.orchestrator.prepared_unit_executor.continue_child_sub_tdp",
        side_effect=_stub_continue_child,
    ):
        result = SubTdpsPhaseOrchestrator(
            store, parent_id, StubProvider()
        ).run()

    assert result.ok is False
    parent = store.load_run(parent_id)
    assert parent["status"] == "paused"
    assert parent["stop"]["code"] == "sub_tdp_child_paused"
    # Round-trip load must succeed (lifecycle-valid stop).
    validate_stop_record(parent["stop"], expected_category="operational")


def test_child_failure_fails_parent_permanently(tmp_path: Path) -> None:
    store, package, parent_id, config = _setup_parent_execution(tmp_path)

    def _stub_continue_child(
        child_store: FileRunStore,
        child_run_id: str,
        *,
        create_provider,
        workspace: Path,
        observability=None,
    ) -> PreparedChildResult:
        run = child_store.load_run(child_run_id)
        expected = int(run["revision"])
        run = dict(run)
        run["revision"] = expected + 1
        run["status"] = "failed"
        run["phase"] = "production"
        run["outcome"] = None
        run["stop"] = {
            "code": "orchestrator_invariant_failure",
            "category": "invariant",
            "phase": "production",
            "message": "boom",
            "role": None,
            "details": {},
        }
        child_store.save_run(child_run_id, run, expected)
        return PreparedChildResult.from_run(
            child_store.load_run(child_run_id),
            ok=False,
            cancelled=False,
            reason="boom",
        )

    with patch(
        "top_down_planning.orchestrator.prepared_unit_executor.continue_child_sub_tdp",
        side_effect=_stub_continue_child,
    ):
        result = SubTdpsPhaseOrchestrator(
            store, parent_id, StubProvider()
        ).run()

    assert result.ok is False
    parent = store.load_run(parent_id)
    assert parent["status"] == "failed"
    assert parent["stop"]["code"] == "sub_tdp_unit_permanently_failed"
    validate_stop_record(parent["stop"], expected_category="invariant")


def test_resume_after_failed_child_terminates_parent_not_running_dead_end(
    tmp_path: Path,
) -> None:
    """P0#4: resume must not leave parent running after a noncontinuable failed unit."""

    from top_down_planning.domain.run_lifecycle import StopRecord
    from top_down_planning.orchestrator.run_transitions import pause_run
    from top_down_planning.persistence.sub_tdp_state import (
        UNIT_STATUS_FAILED,
        load_sub_tdp_state,
        merge_sub_tdp_state_into_production,
    )

    store, package, parent_id, _config = _setup_parent_execution(tmp_path)
    production = store.load_production(parent_id)
    state = load_sub_tdp_state(production)
    assert state is not None
    unit = state["units"][0]
    unit["status"] = UNIT_STATUS_FAILED
    unit["child_run_id"] = "child-failed-1"
    state["status"] = "failed"
    state["active_unit_id"] = None
    merged = merge_sub_tdp_state_into_production(production, state)
    expected = int(production["revision"])
    merged["revision"] = expected + 1
    store.save_production(parent_id, merged, expected)

    pause_run(
        store,
        parent_id,
        stop=StopRecord(
            code="sub_tdp_child_failed",
            category="operational",
            phase=SUB_TDPS,
            message="child Sub-TDP failed",
        ),
        revoke_phase=SUB_TDPS,
        event_type="run_paused",
    )

    # Simulate resume apply clearing pause into running before orchestrator re-enters.
    run = store.load_run(parent_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["status"] = "running"
    run["stop"] = None
    store.save_run(parent_id, run, expected)

    result = SubTdpsPhaseOrchestrator(store, parent_id, StubProvider()).run()

    assert result.ok is False
    parent = store.load_run(parent_id)
    assert parent["status"] == "failed"
    assert parent["status"] != "running"
    assert parent["stop"]["code"] == "sub_tdp_unit_permanently_failed"


def test_attach_rejects_package_digest_mismatch_vs_parent_binding(
    tmp_path: Path,
) -> None:
    store, parent_id, package, config = _parent_with_orchestration(tmp_path)
    child_id = PreparedUnitExecutor().create_or_load_child_run(
        store,
        package,
        "item-foundation",
        resolved_config=config,
        invocation={"command": "execute"},
        parent_run_id=parent_id,
    )
    accept_child_run(store, child_id)

    run = store.load_run(parent_id)
    expected = int(run["revision"])
    run = dict(run)
    binding = dict(run.get("package_binding") or {})
    binding["package_digest"] = "0" * 64
    run["package_binding"] = binding
    run["revision"] = expected + 1
    store.save_run(parent_id, run, expected)

    result = run_cli(
        [
            "sub-tdp",
            "attach",
            "--parent",
            parent_id,
            "--child",
            child_id,
            "--runs-dir",
            str(store.root),
            "--stream-json",
        ]
    )
    assert result.exit_code != 0
    assert "package" in (result.stderr + result.stdout).lower() or "digest" in (
        result.stderr + result.stdout
    ).lower()


def test_attach_rejects_live_child_owner(tmp_path: Path) -> None:
    import json
    import os
    from datetime import UTC, datetime

    from top_down_planning.domain.run_ownership import ResumeLockRecord, resume_lock_path

    store, parent_id, package, config = _parent_with_orchestration(tmp_path)
    child_id = PreparedUnitExecutor().create_or_load_child_run(
        store,
        package,
        "item-foundation",
        resolved_config=config,
        invocation={"command": "execute"},
        parent_run_id=parent_id,
    )
    accept_child_run(store, child_id)
    child_dir = store.run_dir(child_id)
    # On-disk lock held by this PID but not via run_ownership() nested context —
    # attach must refuse concurrent child ownership.
    acquired = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    lock = ResumeLockRecord(
        run_id=child_id,
        pid=os.getpid(),
        owner_token="foreign-token",
        acquired_at=acquired,
    )
    resume_lock_path(child_dir).write_text(json.dumps(lock.to_dict()), encoding="utf-8")

    result = run_cli(
        [
            "sub-tdp",
            "attach",
            "--parent",
            parent_id,
            "--child",
            child_id,
            "--runs-dir",
            str(store.root),
            "--stream-json",
        ]
    )
    assert result.exit_code != 0
    assert "sub_tdp_attach_rejected" in (result.stderr + result.stdout)
    resume_lock_path(child_dir).unlink(missing_ok=True)



def test_wor_parent_execution_without_sub_tdps_fails_closed(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000920-000920"
    workspace = tmp_path
    config = create_run_kwargs(workspace)["resolved_config"]
    kwargs = create_run_kwargs(workspace, resolved_config=config)
    from top_down_planning.domain.models import Plan, PlanItem, Scope
    from top_down_planning.domain.plan_tree import PLAN_ROOT_ITEM_ID
    from top_down_planning.orchestrator.phases import PLAN_VALIDATED

    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Ship.",
        items={
            PLAN_ROOT_ITEM_ID: PlanItem(
                id=PLAN_ROOT_ITEM_ID,
                parent_id=None,
                order_key="0000000000",
                title="Root",
                kind="aggregate",
            ),
            "item-a": PlanItem(
                id="item-a",
                parent_id=PLAN_ROOT_ITEM_ID,
                order_key="0000000000",
                title="A",
                outcome="A",
                kind="work",
                scope=Scope(includes=["a"]),
            ),
        },
    )
    store.create_run(
        run_id,
        plan=plan,
        phase=PLAN_VALIDATED,
        workspace=str(workspace),
        invocation={"command": "execute", "observability": {}},
        run_extras={"run_kind": RUN_KIND_PARENT_EXECUTION},
        **{k: v for k, v in kwargs.items() if k not in {"workspace", "invocation"}},
    )
    store.save_review(run_id, whole_plan_approval_record(store, run_id))
    run = store.load_run(run_id)
    expected = int(run["revision"])
    run = dict(run)
    run["phase"] = WHOLE_OUTPUT_REVIEW
    run["revision"] = expected + 1
    store.save_run(run_id, run, expected)

    with pytest.raises(ProviderRunError, match="sub_tdps"):
        WholeOutputReviewOrchestrator(store, run_id, StubProvider())


def test_wor_fails_closed_when_unit_not_completed(tmp_path: Path) -> None:
    store, package, parent_id, config = _setup_parent_execution(tmp_path)
    production = store.load_production(parent_id)
    state = load_sub_tdp_state(production)
    assert state is not None
    decorate_sub_tdp_v2_package(state)
    state["units"][0]["status"] = "paused"
    state["units"][0]["child_run_id"] = "run-placeholder"
    plan_model = store.load_plan_model(parent_id)
    work_item_ids = [
        item_id for item_id, item in plan_model.items.items() if item.kind == "work"
    ]
    batch, evidence = mirrored_production_batch(
        item_id=work_item_ids[0],
        batch_id="batch-wor-gate",
        store=store,
        run_id=parent_id,
    )
    batch["plan_items"] = work_item_ids
    for item_id in work_item_ids[1:]:
        batch["result"]["dispositions"][item_id] = {
            "disposition": "completed",
            "evidence": "done",
        }
    expected_prod = int(production["revision"])
    production = dict(production)
    production["revision"] = expected_prod + 1
    production["sub_tdps"] = state
    production["batches"] = [batch]
    production["output_evidence"] = [evidence]
    production["dispositions"] = {item_id: "completed" for item_id in work_item_ids}
    production["output_revision"] = int(production.get("output_revision") or 0) + 1
    production["completion_claim"] = goal_met_completion_claim(
        production,
        goal_assessment="Integrated; goal met.",
        plan_revision=int(plan_model.revision),
    )
    store.save_production(parent_id, production, expected_prod)

    run = store.load_run(parent_id)
    expected = int(run["revision"])
    run = dict(run)
    run["phase"] = WHOLE_OUTPUT_REVIEW
    run["revision"] = expected + 1
    store.save_run(parent_id, run, expected)

    adapter = SubTdpWholeOutputReviewAdapter(store, parent_id)
    adapter.preflight(None)
    loop = adapter.new_loop("review-whole-output-01")
    with pytest.raises(ProviderRunError, match="not completed|incomplete"):
        adapter.build_review_package(
            store.load_run(parent_id),
            store.load_resolved_config(parent_id),
            loop,
        )


def test_prepare_resume_rejects_completed_unit_missing_accepted_result(
    tmp_path: Path,
) -> None:
    store, package, parent_id, config = _setup_parent_execution(tmp_path)
    production = store.load_production(parent_id)
    state = load_sub_tdp_state(production)
    assert state is not None
    unit = state["units"][0]
    unit["status"] = "completed"
    unit["child_run_id"] = "run-20260101T000930-000930"
    unit.pop("accepted_result", None)
    unit.pop("accepted_result_digest", None)
    expected_prod = int(production["revision"])
    production = dict(production)
    production["revision"] = expected_prod + 1
    production["sub_tdps"] = state
    with pytest.raises(PersistenceError, match="accepted_result"):
        store.save_production(parent_id, production, expected_prod)


def test_synthesis_fails_when_completed_unit_missing_child_run_id(
    tmp_path: Path,
) -> None:
    store, package, parent_id, config = _setup_parent_execution(tmp_path)
    from top_down_planning.domain.sub_tdp_units import SubTdpUnit
    from top_down_planning.package.lineage import accepted_result_record
    from top_down_planning.orchestrator.prepared_unit_executor import PreparedUnitExecutor

    child_id = PreparedUnitExecutor().create_or_load_child_run(
        store,
        package,
        "item-foundation",
        resolved_config=config,
        invocation={"command": "execute"},
        parent_run_id=parent_id,
    )
    accept_child_run(store, child_id)
    child_run = store.load_run(child_id)
    child_production = store.load_production(child_id)
    unit = package.units["item-foundation"]
    accepted = accepted_result_record(
        child_run=child_run,
        child_production=child_production,
        unit_id="item-foundation",
        unit_plan_digest=unit.plan_digest,
        package_id=str(package.manifest.get("package_id") or ""),
        package_digest=str(package.manifest.get("package_digest") or ""),
        assigned_subtree_digest=unit.assigned_subtree_digest,
    )

    production = store.load_production(parent_id)
    state = load_sub_tdp_state(production)
    assert state is not None
    # Attestation keys off accepted_result.child_run_id; unit_record.child_run_id empty.
    for urec in state["units"]:
        urec["status"] = "completed"
        urec["child_run_id"] = ""
        urec["accepted_result"] = dict(accepted)
        urec["accepted_result_digest"] = accepted_result_digest(accepted)
    expected_prod = int(production["revision"])
    production = dict(production)
    production["revision"] = expected_prod + 1
    production["sub_tdps"] = state
    store.save_production(parent_id, production, expected_prod)

    units = [
        SubTdpUnit(
            plan_item_id=u.unit_id,
            title=u.title,
            outcome="",
            directory=u.plan_file.parent.name,
            ordinal=u.ordinal,
        )
        for u in sorted(package.units.values(), key=lambda item: item.ordinal)
    ]
    orch = SubTdpsPhaseOrchestrator(store, parent_id, StubProvider())
    with pytest.raises(ProviderRunError, match="child_run_id|attestation|completed"):
        orch._synthesize_and_transition(
            store.load_plan_model(parent_id),
            store.load_production(parent_id),
            state,
            units,
            store,
        )


def test_attestation_rejects_unit_id_mismatch() -> None:
    from top_down_planning.package.lineage import (
        accepted_result_digest,
        verify_accepted_result_attestation,
    )

    accepted = {
        "schema_version": 1,
        "package_id": "pkg",
        "package_digest": "p" * 64,
        "unit_id": "item-other",
        "unit_plan_digest": "u" * 64,
        "assigned_subtree_digest": "s" * 64,
        "child_run_id": "run-a",
        "output_revision": 1,
        "output_digest": "a" * 64,
        "whole_output_review_id": "review-1",
        "whole_output_review_digest": "r" * 64,
        "outcome": "accepted",
        "evidence_digest": "e" * 64,
        "output_refs": [],
        "contributions": [],
        "workspace_changes": {},
        "baseline_context_snapshot_digest": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "final_context_snapshot_digest": "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
        "completion_assessment": "done",
    }
    unit = {
        "plan_item_id": "item-a",
        "child_run_id": "run-a",
        "unit_plan_digest": "u" * 64,
        "accepted_result": accepted,
        "accepted_result_digest": accepted_result_digest(accepted),
    }
    with pytest.raises(ValueError, match="unit_id"):
        verify_accepted_result_attestation(unit)


def test_loader_rejects_missing_inherited_approved_digests(tmp_path: Path) -> None:
    import json

    from top_down_planning.package.builder import digest_review_record
    from top_down_planning.package.loader import ExecutionPackageError, ExecutionPackageLoader

    _store, _package_dir, package = _built_package(tmp_path)
    approval_path = package.manifest_path.parent / "parent" / "inherited_plan_approval.json"
    attestation = json.loads(approval_path.read_text(encoding="utf-8"))
    attestation.pop("approved_digests", None)
    approval_path.write_text(json.dumps(attestation), encoding="utf-8")
    manifest_path = package.manifest_path
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["planning_run"]["inherited_plan_approval"] = attestation
    manifest["planning_run"]["whole_plan_review_digest"] = digest_review_record(
        attestation
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ExecutionPackageError, match="approved_digests"):
        ExecutionPackageLoader().load_from_manifest(
            manifest_path, verify_workspace=False
        )


def test_attestation_rejects_unit_child_run_id_mismatch() -> None:
    from top_down_planning.package.lineage import (
        accepted_result_digest,
        verify_accepted_result_attestation,
    )

    accepted = {
        "schema_version": 1,
        "package_id": "pkg",
        "package_digest": "p" * 64,
        "unit_id": "item-a",
        "unit_plan_digest": "u" * 64,
        "assigned_subtree_digest": "s" * 64,
        "child_run_id": "run-accepted-child",
        "output_revision": 1,
        "output_digest": "a" * 64,
        "whole_output_review_id": "review-1",
        "whole_output_review_digest": "r" * 64,
        "outcome": "accepted",
        "evidence_digest": "e" * 64,
        "output_refs": [],
        "contributions": [],
        "workspace_changes": {},
        "baseline_context_snapshot_digest": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "final_context_snapshot_digest": "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
        "completion_assessment": "done",
    }
    unit = {
        "plan_item_id": "item-a",
        "child_run_id": "run-other-child",
        "accepted_result": accepted,
        "accepted_result_digest": accepted_result_digest(accepted),
    }
    with pytest.raises(ValueError, match="child_run_id"):
        verify_accepted_result_attestation(unit)


def test_attach_rejects_empty_package_binding_digest(tmp_path: Path) -> None:
    store, parent_id, package, config = _parent_with_orchestration(tmp_path)
    child_id = PreparedUnitExecutor().create_or_load_child_run(
        store,
        package,
        "item-foundation",
        resolved_config=config,
        invocation={"command": "execute"},
        parent_run_id=parent_id,
    )
    accept_child_run(store, child_id)
    run = store.load_run(parent_id)
    expected = int(run["revision"])
    run = dict(run)
    binding = dict(run.get("package_binding") or {})
    binding["package_digest"] = ""
    run["package_binding"] = binding
    run["revision"] = expected + 1
    store.save_run(parent_id, run, expected)

    result = run_cli(
        [
            "sub-tdp",
            "attach",
            "--parent",
            parent_id,
            "--child",
            child_id,
            "--runs-dir",
            str(store.root),
            "--stream-json",
        ]
    )
    assert result.exit_code != 0


def test_integration_producer_requires_store_for_child_delivery(
    tmp_path: Path,
) -> None:
    from top_down_planning.orchestrator.production import build_producer_context_manifest
    from top_down_planning.orchestrator.prepared_run_factory import PreparedRunFactory
    from top_down_planning.orchestrator.phases import PRODUCTION
    from top_down_planning.domain.sub_tdp_units import SubTdpUnit
    from top_down_planning.persistence.sub_tdp_state import (
        initial_sub_tdp_state_from_package,
        merge_sub_tdp_state_into_production,
    )

    store, _, package = _built_package(tmp_path)
    config = create_run_kwargs(tmp_path)["resolved_config"]
    parent_id = PreparedRunFactory().create_parent_run(
        store,
        package,
        resolved_config=config,
        invocation={"command": "execute"},
    )
    child_id = PreparedUnitExecutor().create_or_load_child_run(
        store,
        package,
        "item-foundation",
        resolved_config=config,
        invocation={"command": "execute"},
        parent_run_id=parent_id,
    )
    accept_child_run(store, child_id)
    units = [
        SubTdpUnit(
            plan_item_id=u.unit_id,
            title=u.title,
            outcome="",
            directory=u.plan_file.parent.name,
            ordinal=u.ordinal,
        )
        for u in sorted(package.units.values(), key=lambda item: item.ordinal)
    ]
    production = store.load_production(parent_id)
    state = initial_sub_tdp_state_from_package(
        package.manifest,
        manifest_path=str(package.manifest_path),
        units=units,
        package_units=package.units,
    )
    for urec in state["units"]:
        if urec["plan_item_id"] == "item-foundation":
            urec["status"] = "completed"
            urec["child_run_id"] = child_id
            from top_down_planning.package.lineage import accepted_result_record

            unit = package.units["item-foundation"]
            accepted = accepted_result_record(
                child_run=store.load_run(child_id),
                child_production=store.load_production(child_id),
                unit_id="item-foundation",
                unit_plan_digest=unit.plan_digest,
                package_id=str(package.manifest.get("package_id") or ""),
                package_digest=str(package.manifest.get("package_digest") or ""),
                assigned_subtree_digest=unit.assigned_subtree_digest,
            )
            urec["accepted_result"] = accepted
            urec["accepted_result_digest"] = accepted_result_digest(accepted)
    state["status"] = "completed"
    state["integration_pending"] = True
    merged = merge_sub_tdp_state_into_production(production, state)
    expected_prod = int(production["revision"])
    merged["revision"] = expected_prod + 1
    merged["completion_claim"] = {
        "goal_met": False,
        "goal_assessment": "integration pending",
        "status": "integration_pending",
    }
    store.save_production(parent_id, merged, expected_prod)

    run = store.load_run(parent_id)
    expected = int(run["revision"])
    run = dict(run)
    run["phase"] = PRODUCTION
    run["revision"] = expected + 1
    store.save_run(parent_id, run, expected)

    with pytest.raises(ProviderRunError, match="store"):
        build_producer_context_manifest(
            parent_id,
            store.load_run(parent_id),
            config,
            store.load_plan_model(parent_id),
            production=store.load_production(parent_id),
            # store intentionally omitted
        )


def test_integration_producer_includes_all_completed_units(tmp_path: Path) -> None:
    from top_down_planning.orchestrator.production import build_producer_context_manifest
    from top_down_planning.orchestrator.prepared_run_factory import PreparedRunFactory
    from top_down_planning.orchestrator.phases import PRODUCTION
    from top_down_planning.domain.sub_tdp_units import SubTdpUnit
    from top_down_planning.package.loader import ExecutionPackageLoader
    from top_down_planning.persistence.sub_tdp_state import (
        initial_sub_tdp_state_from_package,
        merge_sub_tdp_state_into_production,
    )
    from top_down_planning.package.lineage import accepted_result_record
    from tests.unit.test_sub_tdp_defect_pass import _build_package

    store, output_dir, _plan = _build_package(tmp_path)
    package = ExecutionPackageLoader().load(output_dir, verify_workspace=False)
    config = create_run_kwargs(tmp_path)["resolved_config"]
    parent_id = PreparedRunFactory().create_parent_run(
        store,
        package,
        resolved_config=config,
        invocation={"command": "execute"},
    )
    units = [
        SubTdpUnit(
            plan_item_id=u.unit_id,
            title=u.title,
            outcome="",
            directory=u.plan_file.parent.name,
            ordinal=u.ordinal,
        )
        for u in sorted(package.units.values(), key=lambda item: item.ordinal)
    ]
    assert len(units) >= 2
    production = store.load_production(parent_id)
    state = initial_sub_tdp_state_from_package(
        package.manifest,
        manifest_path=str(package.manifest_path),
        units=units,
        package_units=package.units,
    )
    child_ids: list[str] = []
    # Accept in dependency order (item-a before item-b).
    for urec in sorted(state["units"], key=lambda u: u["plan_item_id"]):
        plan_item_id = urec["plan_item_id"]
        upstream = None
        if plan_item_id == "item-b" and child_ids:
            upstream = {"item-a": child_ids[0]}
        child_id = PreparedUnitExecutor().create_or_load_child_run(
            store,
            package,
            plan_item_id,
            resolved_config=config,
            invocation={"command": "execute"},
            parent_run_id=parent_id,
            explicit_upstream=upstream,
            explicit_upstream_only=bool(upstream),
        )
        accept_child_run(store, child_id)
        child_ids.append(child_id)
        unit = package.units[plan_item_id]
        accepted = accepted_result_record(
            child_run=store.load_run(child_id),
            child_production=store.load_production(child_id),
            unit_id=plan_item_id,
            unit_plan_digest=unit.plan_digest,
            package_id=str(package.manifest.get("package_id") or ""),
            package_digest=str(package.manifest.get("package_digest") or ""),
            assigned_subtree_digest=unit.assigned_subtree_digest,
        )
        urec["status"] = "completed"
        urec["child_run_id"] = child_id
        urec["accepted_result"] = accepted
        urec["accepted_result_digest"] = accepted_result_digest(accepted)
    state["status"] = "completed"
    state["integration_pending"] = True
    merged = merge_sub_tdp_state_into_production(production, state)
    expected_prod = int(production["revision"])
    merged["revision"] = expected_prod + 1
    merged["completion_claim"] = {
        "goal_met": False,
        "goal_assessment": "integration pending",
        "status": "integration_pending",
    }
    store.save_production(parent_id, merged, expected_prod)

    run = store.load_run(parent_id)
    expected = int(run["revision"])
    run = dict(run)
    run["phase"] = PRODUCTION
    run["revision"] = expected + 1
    store.save_run(parent_id, run, expected)

    manifest = build_producer_context_manifest(
        parent_id,
        store.load_run(parent_id),
        config,
        store.load_plan_model(parent_id),
        production=store.load_production(parent_id),
        store=store,
    )
    prepared = manifest["prepared_execution"]
    upstream = prepared["upstream_accepted_results"]
    assert len(upstream) == len(units)
    assert {entry["child_run_id"] for entry in upstream} == set(child_ids)
