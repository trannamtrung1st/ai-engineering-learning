"""Regression tests for code-review continued P0/P1 fixes."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.domain.models import Plan
from top_down_planning.domain.plan_tree import PLAN_ROOT_ITEM_ID
from top_down_planning.orchestrator.prepared_run_factory import PreparedRunFactory
from top_down_planning.orchestrator.prepared_unit_executor import PreparedUnitExecutor
from top_down_planning.package.execution_validation import (
    verify_merged_baseline_workspace_bytes,
    verify_package_context_snapshot_with_baseline,
)
from top_down_planning.package.lineage import (
    accepted_result_record,
    verify_upstream_wrapper_matches_live_delivery,
)
from top_down_planning.package.loader import ExecutionPackageError
from top_down_planning.persistence import FileRunStore
from tests.helpers import accept_child_run, bind_evidence_snapshot
from tests.unit.test_sub_tdp_content_bound_baseline import (
    _accepted_wrapper_for_shared,
    _build_package,
    _create_and_accept_shared_writer,
    _plan_with_shared_resource,
)
from tests.support.run_builders import _item


def _plan_abc_chain(run_id: str) -> Plan:
    return Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Ship.",
        input_refs=[],
        items={
            PLAN_ROOT_ITEM_ID: _item(
                PLAN_ROOT_ITEM_ID,
                parent_id=None,
                order_key="0",
                title="Root",
                kind="aggregate",
            ),
            "item-a": _item("item-a", parent_id=PLAN_ROOT_ITEM_ID, order_key="1", title="A"),
            "item-b": _item(
                "item-b",
                parent_id=PLAN_ROOT_ITEM_ID,
                order_key="2",
                title="B",
                depends_on=["item-a"],
            ),
            "item-c": _item(
                "item-c",
                parent_id=PLAN_ROOT_ITEM_ID,
                order_key="3",
                title="C",
                depends_on=["item-b"],
            ),
        },
    )


def _build_abc_package(tmp_path: Path):
    from top_down_planning.config import resolve_config
    from top_down_planning.package.builder import ExecutionPackageBuilder
    from top_down_planning.package.loader import ExecutionPackageLoader
    from tests.helpers import create_run_kwargs, whole_plan_approval_record
    from tests.helpers import write_config

    workspace = tmp_path
    shared = workspace / "shared" / "state.json"
    shared.parent.mkdir(parents=True)
    shared.write_text('{"version": 1}\n', encoding="utf-8")
    config = resolve_config(
        write_config(
            tmp_path / "abc-cfg.yaml",
            """
run:
  output_goal: Ship.
agent_context:
  roles:
    producer:
      resources:
        - shared/
    reviewer:
      resources:
        - shared/
""",
        ),
        cwd=workspace,
    )
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T008001-008001"
    plan = _plan_abc_chain(run_id)
    kwargs = create_run_kwargs(workspace, resolved_config=config)
    store.create_run(run_id, plan=plan, phase="plan_validated", **kwargs)
    store.save_review(run_id, whole_plan_approval_record(store, run_id))
    output_dir = tmp_path / "pkg-abc"
    ExecutionPackageBuilder().build_from_planning_run(store, run_id, output_dir=output_dir)
    package = ExecutionPackageLoader().load(output_dir, verify_workspace=False)
    return store, package


def test_historical_wrapper_delivery_ok_when_workspace_superseded(tmp_path: Path) -> None:
    """Historical baseline wrappers validate delivery without per-child workspace bytes."""

    store, package = _build_package(tmp_path, dependent=True)
    config = package.resolved_config
    factory = PreparedRunFactory()
    shared = Path(package.workspace_path) / "shared" / "state.json"

    child_a = factory.create_child_run(
        store, package, package.units["item-a"], resolved_config=config,
        invocation={"command": "execute"},
    )
    shared.write_text('{"writer": "a"}\n', encoding="utf-8")
    accept_child_run(
        store, child_a,
        outputs=[{"id": "out-a", "type": "artifact", "ref": "shared/state.json"}],
        contributions=[{"item_id": "item-a", "output_refs": ["out-a"], "summary": "A"}],
    )
    wrapper_a, _ = _accepted_wrapper_for_shared(store, package, child_a, unit_id="item-a")

    child_b = factory.create_child_run(
        store, package, package.units["item-b"], resolved_config=config,
        invocation={"command": "execute"}, upstream_accepted_results=[wrapper_a],
    )
    shared.write_text('{"writer": "b"}\n', encoding="utf-8")
    accept_child_run(
        store, child_b,
        outputs=[{"id": "out-b", "type": "artifact", "ref": "shared/state.json"}],
        contributions=[{"item_id": "item-b", "output_refs": ["out-b"], "summary": "B"}],
    )
    wrapper_b, _ = _accepted_wrapper_for_shared(store, package, child_b, unit_id="item-b")

    verify_upstream_wrapper_matches_live_delivery(store, wrapper_a)
    verify_upstream_wrapper_matches_live_delivery(store, wrapper_b)

    expected_snapshot = str(
        (package.manifest.get("context") or {}).get("context_snapshot_digest") or ""
    )
    verify_merged_baseline_workspace_bytes(
        [wrapper_a, wrapper_b],
        workspace=Path(package.workspace_path),
        initial_snapshot_digest=expected_snapshot,
        resolved_config=package.resolved_config,
        unit_depends_on={uid: list(u.depends_on) for uid, u in package.units.items()},
    )


def test_merged_baseline_rejects_workspace_tamper(tmp_path: Path) -> None:
    store, package = _build_package(tmp_path)
    child_id = _create_and_accept_shared_writer(
        store, package, unit_id="item-a", content='{"version": 2}\n'
    )
    wrapper, _ = _accepted_wrapper_for_shared(store, package, child_id, unit_id="item-a")
    shared = Path(package.workspace_path) / "shared" / "state.json"
    shared.write_text('{"tampered": true}\n', encoding="utf-8")
    expected_snapshot = str(
        (package.manifest.get("context") or {}).get("context_snapshot_digest") or ""
    )
    with pytest.raises(ExecutionPackageError, match="do not match accepted sha256"):
        verify_merged_baseline_workspace_bytes(
            [wrapper],
            workspace=Path(package.workspace_path),
            initial_snapshot_digest=expected_snapshot,
            resolved_config=package.resolved_config,
            unit_depends_on={uid: list(u.depends_on) for uid, u in package.units.items()},
        )


def test_three_child_chain_creates_after_ordered_overwrites(tmp_path: Path) -> None:
    store, package = _build_abc_package(tmp_path)
    config = package.resolved_config
    factory = PreparedRunFactory()
    shared = Path(package.workspace_path) / "shared" / "state.json"

    child_a = factory.create_child_run(
        store, package, package.units["item-a"], resolved_config=config,
        invocation={"command": "execute"},
    )
    shared.write_text('{"step": "a"}\n', encoding="utf-8")
    accept_child_run(
        store, child_a,
        outputs=[{"id": "out-a", "type": "artifact", "ref": "shared/state.json"}],
        contributions=[{"item_id": "item-a", "output_refs": ["out-a"], "summary": "A"}],
    )
    wrapper_a, _ = _accepted_wrapper_for_shared(store, package, child_a, unit_id="item-a")

    child_b = factory.create_child_run(
        store, package, package.units["item-b"], resolved_config=config,
        invocation={"command": "execute"}, upstream_accepted_results=[wrapper_a],
    )
    shared.write_text('{"step": "b"}\n', encoding="utf-8")
    accept_child_run(
        store, child_b,
        outputs=[{"id": "out-b", "type": "artifact", "ref": "shared/state.json"}],
        contributions=[{"item_id": "item-b", "output_refs": ["out-b"], "summary": "B"}],
    )
    wrapper_b, _ = _accepted_wrapper_for_shared(store, package, child_b, unit_id="item-b")

    child_c = factory.create_child_run(
        store, package, package.units["item-c"], resolved_config=config,
        invocation={"command": "execute"},
        workspace_baseline_results=[wrapper_a, wrapper_b],
        upstream_accepted_results=[wrapper_b],
    )
    assert child_c


def test_explicit_baseline_overwrite_orders_by_snapshot_lineage(tmp_path: Path) -> None:
    """item-z then item-a overwrite composes when --baseline supplies lineage only."""

    from top_down_planning.config import resolve_config
    from top_down_planning.package.builder import ExecutionPackageBuilder
    from top_down_planning.package.loader import ExecutionPackageLoader
    from tests.helpers import create_run_kwargs, whole_plan_approval_record
    from tests.helpers import write_config

    workspace = tmp_path
    shared = workspace / "shared" / "state.json"
    shared.parent.mkdir(parents=True)
    shared.write_text('{"version": 1}\n', encoding="utf-8")
    config = resolve_config(
        write_config(
            tmp_path / "cfg.yaml",
            """
run:
  output_goal: Ship.
agent_context:
  roles:
    producer:
      resources:
        - shared/
""",
        ),
        cwd=workspace,
    )
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T008002-008002"
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Ship.",
        input_refs=[],
        items={
            PLAN_ROOT_ITEM_ID: _item(
                PLAN_ROOT_ITEM_ID, parent_id=None, order_key="0", title="Root", kind="aggregate",
            ),
            "item-z": _item("item-z", parent_id=PLAN_ROOT_ITEM_ID, order_key="9", title="Z"),
            "item-a": _item("item-a", parent_id=PLAN_ROOT_ITEM_ID, order_key="1", title="A"),
        },
    )
    kwargs = create_run_kwargs(workspace, resolved_config=config)
    store.create_run(run_id, plan=plan, phase="plan_validated", **kwargs)
    store.save_review(run_id, whole_plan_approval_record(store, run_id))
    output_dir = tmp_path / "pkg"
    ExecutionPackageBuilder().build_from_planning_run(store, run_id, output_dir=output_dir)
    package = ExecutionPackageLoader().load(output_dir, verify_workspace=False)
    executor = PreparedUnitExecutor()

    child_z = executor.create_or_load_child_run(
        store, package, "item-z", resolved_config=config, invocation={"command": "execute"},
    )
    shared.write_text('{"writer": "z"}\n', encoding="utf-8")
    accept_child_run(
        store, child_z,
        outputs=[{"id": "out-z", "type": "artifact", "ref": "shared/state.json"}],
        contributions=[{"item_id": "item-z", "output_refs": ["out-z"], "summary": "Z"}],
    )
    wrapper_z, _ = _accepted_wrapper_for_shared(store, package, child_z, unit_id="item-z")

    child_a = executor.create_or_load_child_run(
        store, package, "item-a", resolved_config=config,
        invocation={"command": "execute"},
        explicit_baseline_run_ids=[child_z],
        explicit_upstream_only=True,
    )
    shared.write_text('{"writer": "a"}\n', encoding="utf-8")
    accept_child_run(
        store, child_a,
        outputs=[{"id": "out-a", "type": "artifact", "ref": "shared/state.json"}],
        contributions=[{"item_id": "item-a", "output_refs": ["out-a"], "summary": "A"}],
    )
    wrapper_a, _ = _accepted_wrapper_for_shared(store, package, child_a, unit_id="item-a")

    binding = verify_package_context_snapshot_with_baseline(
        package,
        store=store,
        baseline_wrappers=[wrapper_z, wrapper_a],
    )
    assert isinstance(binding, dict)


def test_sync_run_production_digests_rebases_resource_snapshot(tmp_path: Path) -> None:
    """Production digest sync rebases context_snapshot when resource bytes change."""

    from top_down_planning.config import resolve_config
    from top_down_planning.config.context_digests import sync_run_production_digests
    from top_down_planning.orchestrator.phases import PRODUCTION
    from top_down_planning.package.builder import ExecutionPackageBuilder
    from top_down_planning.package.loader import ExecutionPackageLoader
    from tests.helpers import apply_production, create_run_kwargs, whole_plan_approval_record
    from tests.helpers import write_config

    workspace = tmp_path
    shared = workspace / "shared" / "state.json"
    shared.parent.mkdir(parents=True)
    shared.write_text('{"version": 1}\n', encoding="utf-8")
    config = resolve_config(
        write_config(
            tmp_path / "wcfg.yaml",
            """
run:
  output_goal: Ship unit.
agent_context:
  roles:
    producer:
      resources:
        - shared/
""",
        ),
        cwd=workspace,
    )
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T008003-008003"
    plan = _plan_with_shared_resource(run_id, dependent=False)
    kwargs = create_run_kwargs(workspace, resolved_config=config)
    store.create_run(run_id, plan=plan, phase="plan_validated", **kwargs)
    store.save_review(run_id, whole_plan_approval_record(store, run_id))
    output_dir = tmp_path / "pkg"
    ExecutionPackageBuilder().build_from_planning_run(store, run_id, output_dir=output_dir)
    package = ExecutionPackageLoader().load(output_dir, verify_workspace=False)

    child_id = PreparedUnitExecutor().create_or_load_child_run(
        store, package, "item-a", resolved_config=config, invocation={"command": "execute"},
    )
    run = store.load_run(child_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["phase"] = PRODUCTION
    run["status"] = "running"
    run["outcome"] = None
    store.save_run(child_id, run, expected)

    pre_snapshot = store.load_run(child_id)["digests"]["context_snapshot"]
    shared.write_text('{"version": 2}\n', encoding="utf-8")
    apply_production(
        store,
        child_id,
        {
            "production_revision": int(store.load_production(child_id)["revision"]),
            "plan_items": ["item-a"],
            "dispositions": {
                "item-a": {"disposition": "completed", "evidence": "wrote state"},
            },
            "outputs": [
                {"id": "out-a", "type": "artifact", "ref": "shared/state.json"},
            ],
            "contributions": [
                {
                    "item_id": "item-a",
                    "output_refs": ["out-a"],
                    "summary": "batch",
                },
            ],
            "summary": "production batch",
        },
        handler="apply",
        phase=PRODUCTION,
    )()

    sync_run_production_digests(store, child_id)
    post_snapshot = store.load_run(child_id)["digests"]["context_snapshot"]
    assert post_snapshot != pre_snapshot


def test_child_b_production_pause_resume_via_apply_resume(tmp_path: Path) -> None:
    """Paused child B in production resumes after overwriting upstream shared path."""

    from top_down_planning.orchestrator.apply_resume import apply_resume_plan_atomically
    from top_down_planning.orchestrator.phases import PRODUCTION
    from top_down_planning.orchestrator.prepare_resume import prepare_resume
    from tests.helpers import apply_production

    store, package = _build_package(tmp_path, dependent=True)
    config = package.resolved_config
    factory = PreparedRunFactory()
    shared = Path(package.workspace_path) / "shared" / "state.json"

    child_a = factory.create_child_run(
        store, package, package.units["item-a"], resolved_config=config,
        invocation={"command": "execute"},
    )
    shared.write_text('{"writer": "a"}\n', encoding="utf-8")
    accept_child_run(
        store, child_a,
        outputs=[{"id": "out-a", "type": "artifact", "ref": "shared/state.json"}],
        contributions=[{"item_id": "item-a", "output_refs": ["out-a"], "summary": "A"}],
    )

    child_b = PreparedUnitExecutor().create_or_load_child_run(
        store, package, "item-b", resolved_config=config,
        invocation={"command": "execute"},
        explicit_upstream={"item-a": child_a},
        explicit_upstream_only=True,
    )
    run = store.load_run(child_b)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["phase"] = PRODUCTION
    store.save_run(child_b, run, expected)

    shared.write_text('{"writer": "b"}\n', encoding="utf-8")
    apply_production(
        store,
        child_b,
        {
            "production_revision": int(store.load_production(child_b)["revision"]),
            "plan_items": ["item-b"],
            "dispositions": {"item-b": {"disposition": "completed", "evidence": "B wrote"}},
            "outputs": [{"id": "out-b", "type": "artifact", "ref": "shared/state.json"}],
            "contributions": [
                {"item_id": "item-b", "output_refs": ["out-b"], "summary": "B batch"},
            ],
            "summary": "production batch",
        },
        handler="apply",
        phase=PRODUCTION,
    )()

    run = store.load_run(child_b)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["status"] = "paused"
    run["stop"] = {
        "code": "user_cancelled",
        "category": "operational",
        "phase": PRODUCTION,
        "message": "paused mid-production",
        "role": None,
        "details": {},
    }
    store.save_run(child_b, run, expected)

    invocation = store.load_invocation(child_b)
    plan = prepare_resume(store, child_b, config)
    result = apply_resume_plan_atomically(
        store,
        plan,
        resolved_config=config,
        invocation=invocation,
    )
    assert result["ok"] is True
    assert store.load_run(child_b)["status"] == "running"
    assert store.load_run(child_b)["stop"] is None


def test_parent_resume_ab_chain_after_b_overwrites_a(tmp_path: Path) -> None:
    """Parent resume authorizes merged A then B overwrite on shared resource."""

    from top_down_planning.domain.sub_tdp_units import SubTdpUnit
    from top_down_planning.orchestrator.apply_resume import apply_resume_plan_atomically
    from top_down_planning.orchestrator.phases import SUB_TDPS
    from top_down_planning.orchestrator.prepare_resume import prepare_resume
    from top_down_planning.package.lineage import accepted_result_digest, accepted_result_record
    from top_down_planning.persistence.sub_tdp_state import (
        initial_sub_tdp_state_from_package,
        merge_sub_tdp_state_into_production,
    )

    store, package = _build_package(tmp_path, dependent=True)
    config = package.resolved_config
    factory = PreparedRunFactory()
    shared = Path(package.workspace_path) / "shared" / "state.json"
    parent_id = factory.create_parent_run(
        store, package, resolved_config=config, invocation={"command": "execute"},
    )

    child_a = factory.create_child_run(
        store, package, package.units["item-a"], resolved_config=config,
        invocation={"command": "execute"},
    )
    shared.write_text('{"writer": "a"}\n', encoding="utf-8")
    accept_child_run(
        store, child_a,
        outputs=[{"id": "out-a", "type": "artifact", "ref": "shared/state.json"}],
        contributions=[{"item_id": "item-a", "output_refs": ["out-a"], "summary": "A"}],
    )

    child_b = PreparedUnitExecutor().create_or_load_child_run(
        store, package, "item-b", resolved_config=config,
        invocation={"command": "execute"},
        explicit_upstream={"item-a": child_a},
        explicit_upstream_only=True,
    )
    shared.write_text('{"writer": "b"}\n', encoding="utf-8")
    accept_child_run(
        store, child_b,
        outputs=[{"id": "out-b", "type": "artifact", "ref": "shared/state.json"}],
        contributions=[{"item_id": "item-b", "output_refs": ["out-b"], "summary": "B"}],
    )

    run = store.load_run(parent_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["phase"] = SUB_TDPS
    run["status"] = "paused"
    run["stop"] = {
        "code": "sub_tdps_awaiting_children",
        "category": "operational",
        "phase": SUB_TDPS,
        "message": "waiting",
        "role": None,
        "details": {},
    }
    store.save_run(parent_id, run, expected)

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
    parent_binding = store.load_run(parent_id).get("package_binding") or {}
    state = initial_sub_tdp_state_from_package(
        package.manifest,
        manifest_path=str(parent_binding.get("manifest_path") or package.manifest_path),
        units=units,
        package_units=package.units,
    )
    for idx, (child_id, unit_id) in enumerate([(child_a, "item-a"), (child_b, "item-b")]):
        unit = package.units[unit_id]
        accepted = accepted_result_record(
            child_run=store.load_run(child_id),
            child_production=store.load_production(child_id),
            unit_id=unit_id,
            unit_plan_digest=unit.plan_digest,
            package_id=str(package.manifest.get("package_id") or ""),
            package_digest=str(package.manifest.get("package_digest") or ""),
            assigned_subtree_digest=unit.assigned_subtree_digest,
        )
        state["units"][idx]["child_run_id"] = child_id
        state["units"][idx]["status"] = "completed"
        state["units"][idx]["accepted_result"] = accepted
        state["units"][idx]["accepted_result_digest"] = accepted_result_digest(accepted)
    merged = merge_sub_tdp_state_into_production(production, state)
    expected_revision = int(production["revision"])
    merged["revision"] = expected_revision + 1
    store.save_production(parent_id, merged, expected_revision)

    invocation = store.load_invocation(parent_id)
    plan = prepare_resume(store, parent_id, config)
    result = apply_resume_plan_atomically(
        store,
        plan,
        resolved_config=config,
        invocation=invocation,
    )
    assert result["ok"] is True
    assert store.load_run(parent_id)["status"] == "running"


def test_parent_resume_two_no_change_children_with_matching_snapshots(
    tmp_path: Path,
) -> None:
    """Two accepted children with baseline=final=S0 must not cycle during parent auth."""

    from top_down_planning.domain.sub_tdp_units import SubTdpUnit
    from top_down_planning.orchestrator.apply_resume import apply_resume_plan_atomically
    from top_down_planning.orchestrator.phases import SUB_TDPS
    from top_down_planning.orchestrator.prepare_resume import (
        collect_parent_sub_tdp_authorized_workspace_changes,
        prepare_resume,
        verify_parent_sub_tdp_workspace_matches_accepted,
    )
    from top_down_planning.orchestrator.whole_output_review import WholeOutputReviewOrchestrator
    from top_down_planning.package.lineage import accepted_result_digest, accepted_result_record
    from top_down_planning.persistence.sub_tdp_state import (
        initial_sub_tdp_state_from_package,
        merge_sub_tdp_state_into_production,
    )
    from core_tools.provider import StubProvider

    store, package = _build_package(tmp_path, dependent=False)
    config = package.resolved_config
    parent_id = PreparedRunFactory().create_parent_run(
        store, package, resolved_config=config, invocation={"command": "execute"},
    )
    child_a = PreparedUnitExecutor().create_or_load_child_run(
        store, package, "item-a", resolved_config=config,
        invocation={"command": "execute"}, parent_run_id=parent_id,
    )
    accept_child_run(store, child_a)
    child_b = PreparedUnitExecutor().create_or_load_child_run(
        store, package, "item-b", resolved_config=config,
        invocation={"command": "execute"}, parent_run_id=parent_id,
    )
    accept_child_run(store, child_b)

    package_initial = str(
        (package.manifest.get("context") or {}).get("context_snapshot_digest") or ""
    )
    assert package_initial
    for child_id, unit_id in [(child_a, "item-a"), (child_b, "item-b")]:
        unit = package.units[unit_id]
        accepted = accepted_result_record(
            child_run=store.load_run(child_id),
            child_production=store.load_production(child_id),
            unit_id=unit_id,
            unit_plan_digest=unit.plan_digest,
            package_id=str(package.manifest.get("package_id") or ""),
            package_digest=str(package.manifest.get("package_digest") or ""),
            assigned_subtree_digest=unit.assigned_subtree_digest,
        )
        assert accepted["baseline_context_snapshot_digest"] == package_initial
        assert accepted["final_context_snapshot_digest"] == package_initial

    run = store.load_run(parent_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["phase"] = SUB_TDPS
    run["status"] = "paused"
    run["stop"] = {
        "code": "sub_tdps_awaiting_children",
        "category": "operational",
        "phase": SUB_TDPS,
        "message": "waiting",
        "role": None,
        "details": {},
    }
    store.save_run(parent_id, run, expected)

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
    parent_binding = store.load_run(parent_id).get("package_binding") or {}
    state = initial_sub_tdp_state_from_package(
        package.manifest,
        manifest_path=str(parent_binding.get("manifest_path") or package.manifest_path),
        units=units,
        package_units=package.units,
    )
    for idx, (child_id, unit_id) in enumerate([(child_a, "item-a"), (child_b, "item-b")]):
        unit = package.units[unit_id]
        accepted = accepted_result_record(
            child_run=store.load_run(child_id),
            child_production=store.load_production(child_id),
            unit_id=unit_id,
            unit_plan_digest=unit.plan_digest,
            package_id=str(package.manifest.get("package_id") or ""),
            package_digest=str(package.manifest.get("package_digest") or ""),
            assigned_subtree_digest=unit.assigned_subtree_digest,
        )
        state["units"][idx]["child_run_id"] = child_id
        state["units"][idx]["status"] = "completed"
        state["units"][idx]["accepted_result"] = accepted
        state["units"][idx]["accepted_result_digest"] = accepted_result_digest(accepted)
    merged = merge_sub_tdp_state_into_production(production, state)
    expected_revision = int(production["revision"])
    merged["revision"] = expected_revision + 1
    store.save_production(parent_id, merged, expected_revision)

    production = store.load_production(parent_id)
    collect_parent_sub_tdp_authorized_workspace_changes(
        store,
        production=production,
        workspace=Path(package.workspace_path),
    )
    verify_parent_sub_tdp_workspace_matches_accepted(
        store,
        production=production,
        workspace=Path(package.workspace_path),
    )

    invocation = store.load_invocation(parent_id)
    plan = prepare_resume(store, parent_id, config)
    assert plan.validation.context_binding_valid is True
    result = apply_resume_plan_atomically(
        store,
        plan,
        resolved_config=config,
        invocation=invocation,
    )
    assert result["ok"] is True

    # WOR entry re-verifies parent sub-TDP workspace auth before review starts.
    WholeOutputReviewOrchestrator(store, parent_id, StubProvider())


def test_parent_integration_overlay_supersedes_child_workspace_hash(
    tmp_path: Path,
) -> None:
    """Parent integration production evidence overlays child closure on shared paths."""

    from top_down_planning.orchestrator.prepare_resume import (
        verify_parent_sub_tdp_workspace_matches_accepted,
    )
    from top_down_planning.package.lineage import accepted_result_digest, accepted_result_record
    from top_down_planning.persistence.sub_tdp_state import (
        initial_sub_tdp_state_from_package,
        merge_sub_tdp_state_into_production,
    )

    store, package = _build_package(tmp_path, dependent=False)
    config = package.resolved_config
    shared = Path(package.workspace_path) / "shared" / "state.json"
    parent_id = PreparedRunFactory().create_parent_run(
        store, package, resolved_config=config, invocation={"command": "execute"},
    )
    child_id = PreparedUnitExecutor().create_or_load_child_run(
        store, package, "item-a", resolved_config=config,
        invocation={"command": "execute"}, parent_run_id=parent_id,
    )
    shared.write_text('{"version": 2}\n', encoding="utf-8")
    accept_child_run(
        store, child_id,
        outputs=[{"id": "out-a", "type": "artifact", "ref": "shared/state.json"}],
        contributions=[{"item_id": "item-a", "output_refs": ["out-a"], "summary": "A"}],
    )

    production = store.load_production(parent_id)
    parent_binding = store.load_run(parent_id).get("package_binding") or {}
    from top_down_planning.domain.sub_tdp_units import SubTdpUnit

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
    state = initial_sub_tdp_state_from_package(
        package.manifest,
        manifest_path=str(parent_binding.get("manifest_path") or package.manifest_path),
        units=units,
        package_units=package.units,
    )
    unit = package.units["item-a"]
    accepted = accepted_result_record(
        child_run=store.load_run(child_id),
        child_production=store.load_production(child_id),
        unit_id="item-a",
        unit_plan_digest=unit.plan_digest,
        package_id=str(package.manifest.get("package_id") or ""),
        package_digest=str(package.manifest.get("package_digest") or ""),
        assigned_subtree_digest=unit.assigned_subtree_digest,
    )
    state["units"][0]["child_run_id"] = child_id
    state["units"][0]["status"] = "completed"
    state["units"][0]["accepted_result"] = accepted
    state["units"][0]["accepted_result_digest"] = accepted_result_digest(accepted)
    merged = merge_sub_tdp_state_into_production(production, state)
    expected_revision = int(production["revision"])
    merged["revision"] = expected_revision + 1
    store.save_production(parent_id, merged, expected_revision)

    from core_tools.persistence import digest_file

    shared.write_text('{"version": 99}\n', encoding="utf-8")
    production = store.load_production(parent_id)
    batch_id = "batch-parent-overlay"
    overlay_evidence, nested_overlay = bind_evidence_snapshot(
        store,
        parent_id,
        {
            "id": "out-parent-overlay",
            "type": "artifact",
            "ref": "shared/state.json",
            "media_type": "application/json",
            "captured_at": "2026-01-01T00:00:00Z",
            "batch_id": batch_id,
        },
        content=shared.read_bytes(),
    )
    batches = list(production.get("batches") or [])
    batches.append(
        {
            "id": batch_id,
            "plan_items": ["item-a"],
            "status": "completed",
            "result": {
                "outputs": [nested_overlay],
                "contributions": [],
                "dispositions": {
                    "item-a": {
                        "disposition": "completed",
                        "evidence": "parent overlay",
                    }
                },
                "summary": "parent overlay",
            },
        }
    )
    evidence = list(production.get("output_evidence") or [])
    evidence.append(overlay_evidence)
    dispositions = dict(production.get("dispositions") or {})
    dispositions["item-a"] = "completed"
    expected_prod = int(production["revision"])
    production = dict(production)
    production["batches"] = batches
    production["output_evidence"] = evidence
    production["dispositions"] = dispositions
    production["output_revision"] = int(production.get("output_revision") or 0) + 1
    production["revision"] = expected_prod + 1
    store.save_production(parent_id, production, expected_prod)

    production = store.load_production(parent_id)
    paths = verify_parent_sub_tdp_workspace_matches_accepted(
        store,
        production=production,
        workspace=Path(package.workspace_path),
    )
    assert "shared/state.json" in paths


def test_baseline_auth_params_from_binding_loads_depends_on(tmp_path: Path) -> None:
    from top_down_planning.package.execution_validation import baseline_auth_params_from_binding

    store, package = _build_package(tmp_path, dependent=True)
    factory = PreparedRunFactory()
    child_a = factory.create_child_run(
        store, package, package.units["item-a"], resolved_config=package.resolved_config,
        invocation={"command": "execute"},
    )
    accept_child_run(store, child_a)
    wrapper_a, _ = _accepted_wrapper_for_shared(store, package, child_a, unit_id="item-a")
    child_b = factory.create_child_run(
        store, package, package.units["item-b"], resolved_config=package.resolved_config,
        invocation={"command": "execute"}, upstream_accepted_results=[wrapper_a],
    )
    binding = dict(store.load_run(child_b).get("package_binding") or {})
    initial_snapshot, unit_depends_on, resolved_config, package_units = (
        baseline_auth_params_from_binding(binding)
    )
    expected_snapshot = str(
        (package.manifest.get("context") or {}).get("context_snapshot_digest") or ""
    )
    assert initial_snapshot == expected_snapshot
    assert unit_depends_on.get("item-b") == ["item-a"]
    assert resolved_config == package.resolved_config
    assert "item-a" in package_units


def test_apply_resume_production_phase_blocks_unauthorized_resource_drift(
    tmp_path: Path,
) -> None:
    """Apply must reject configured-resource drift even when paused in production."""

    from top_down_planning.orchestrator.apply_resume import ApplyResumeError, apply_resume_plan_atomically
    from top_down_planning.orchestrator.phases import PRODUCTION
    from top_down_planning.orchestrator.prepare_resume import prepare_resume
    from tests.helpers import apply_production

    store, package = _build_package(tmp_path, dependent=True)
    config = package.resolved_config
    factory = PreparedRunFactory()
    shared = Path(package.workspace_path) / "shared" / "state.json"

    child_a = factory.create_child_run(
        store, package, package.units["item-a"], resolved_config=config,
        invocation={"command": "execute"},
    )
    shared.write_text('{"writer": "a"}\n', encoding="utf-8")
    accept_child_run(
        store, child_a,
        outputs=[{"id": "out-a", "type": "artifact", "ref": "shared/state.json"}],
        contributions=[{"item_id": "item-a", "output_refs": ["out-a"], "summary": "A"}],
    )

    child_b = PreparedUnitExecutor().create_or_load_child_run(
        store, package, "item-b", resolved_config=config,
        invocation={"command": "execute"},
        explicit_upstream={"item-a": child_a},
        explicit_upstream_only=True,
    )
    run = store.load_run(child_b)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["phase"] = PRODUCTION
    store.save_run(child_b, run, expected)

    shared.write_text('{"writer": "b"}\n', encoding="utf-8")
    apply_production(
        store,
        child_b,
        {
            "production_revision": int(store.load_production(child_b)["revision"]),
            "plan_items": ["item-b"],
            "dispositions": {"item-b": {"disposition": "completed", "evidence": "B wrote"}},
            "outputs": [{"id": "out-b", "type": "artifact", "ref": "shared/state.json"}],
            "contributions": [
                {"item_id": "item-b", "output_refs": ["out-b"], "summary": "B batch"},
            ],
            "summary": "production batch",
        },
        handler="apply",
        phase=PRODUCTION,
    )()

    run = store.load_run(child_b)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["status"] = "paused"
    run["stop"] = {
        "code": "user_cancelled",
        "category": "operational",
        "phase": PRODUCTION,
        "message": "paused mid-production",
        "role": None,
        "details": {},
    }
    store.save_run(child_b, run, expected)

    invocation = store.load_invocation(child_b)
    plan = prepare_resume(store, child_b, config)
    assert plan.validation.context_binding_valid is True

    # Unauthorized configured-resource drift between prepare and apply.
    (Path(package.workspace_path) / "shared" / "drift.json").write_text(
        "unauthorized\n", encoding="utf-8"
    )

    with pytest.raises(ApplyResumeError, match="not authorized|drift|context"):
        apply_resume_plan_atomically(
            store,
            plan,
            resolved_config=config,
            invocation=invocation,
        )


def test_baseline_wrapper_rejects_foreign_package_identity(tmp_path: Path) -> None:
    """Baseline-only wrappers must match the current prepared package contract."""

    from top_down_planning.package.lineage import (
        accepted_result_digest,
        verify_baseline_wrapper_matches_current_package,
    )

    store, package = _build_package(tmp_path)
    child_id = _create_and_accept_shared_writer(
        store, package, unit_id="item-a", content='{"version": 2}\n'
    )
    wrapper, _ = _accepted_wrapper_for_shared(
        store, package, child_id, unit_id="item-a"
    )
    forged = dict(wrapper)
    forged_accepted = dict(forged["accepted_result"])
    forged_accepted["package_digest"] = "0" * 64
    forged["accepted_result"] = forged_accepted
    forged["accepted_result_digest"] = accepted_result_digest(forged_accepted)
    with pytest.raises(ValueError, match="package_digest"):
        verify_baseline_wrapper_matches_current_package(
            forged,
            package_id=str(package.manifest.get("package_id") or ""),
            package_digest=str(package.manifest.get("package_digest") or ""),
            package_units=package.units,
        )


def test_apply_resume_at_apply_checks_baseline_package_identity(
    tmp_path: Path,
) -> None:
    """Child apply_resume invokes baseline package-identity validation."""

    from top_down_planning.orchestrator.apply_resume import apply_resume_plan_atomically
    from top_down_planning.orchestrator.phases import PRODUCTION
    from top_down_planning.orchestrator.prepare_resume import prepare_resume
    from top_down_planning.package.lineage import verify_baseline_wrapper_matches_current_package
    from tests.helpers import apply_production

    store, package = _build_package(tmp_path, dependent=True)
    config = package.resolved_config
    factory = PreparedRunFactory()
    shared = Path(package.workspace_path) / "shared" / "state.json"

    child_a = factory.create_child_run(
        store, package, package.units["item-a"], resolved_config=config,
        invocation={"command": "execute"},
    )
    shared.write_text('{"writer": "a"}\n', encoding="utf-8")
    accept_child_run(
        store, child_a,
        outputs=[{"id": "out-a", "type": "artifact", "ref": "shared/state.json"}],
        contributions=[{"item_id": "item-a", "output_refs": ["out-a"], "summary": "A"}],
    )

    child_b = PreparedUnitExecutor().create_or_load_child_run(
        store, package, "item-b", resolved_config=config,
        invocation={"command": "execute"},
        explicit_upstream={"item-a": child_a},
        explicit_upstream_only=True,
    )
    run = store.load_run(child_b)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["phase"] = PRODUCTION
    store.save_run(child_b, run, expected)

    shared.write_text('{"writer": "b"}\n', encoding="utf-8")
    apply_production(
        store,
        child_b,
        {
            "production_revision": int(store.load_production(child_b)["revision"]),
            "plan_items": ["item-b"],
            "dispositions": {"item-b": {"disposition": "completed", "evidence": "B wrote"}},
            "outputs": [{"id": "out-b", "type": "artifact", "ref": "shared/state.json"}],
            "contributions": [
                {"item_id": "item-b", "output_refs": ["out-b"], "summary": "B batch"},
            ],
            "summary": "production batch",
        },
        handler="apply",
        phase=PRODUCTION,
    )()

    run = store.load_run(child_b)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["status"] = "paused"
    run["stop"] = {
        "code": "user_cancelled",
        "category": "operational",
        "phase": PRODUCTION,
        "message": "paused",
        "role": None,
        "details": {},
    }
    store.save_run(child_b, run, expected)

    binding = dict(store.load_run(child_b).get("package_binding") or {})
    wrapper = binding["workspace_baseline_accepted_results"][0]
    verify_baseline_wrapper_matches_current_package(
        wrapper,
        package_id=str(binding.get("package_id") or ""),
        package_digest=str(binding.get("package_digest") or ""),
        package_units=package.units,
    )

    invocation = store.load_invocation(child_b)
    plan = prepare_resume(store, child_b, config)
    result = apply_resume_plan_atomically(
        store,
        plan,
        resolved_config=config,
        invocation=invocation,
    )
    assert result["ok"] is True
