"""Tests for Sub-TDP code review fixes (P0/P1 blockers and hardening)."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from top_down_planning.config import resolve_config
from top_down_planning.domain.models import Plan, PlanItem, Scope
from top_down_planning.domain.plan_tree import PLAN_ROOT_ITEM_ID
from top_down_planning.orchestrator.phases import SUB_TDPS
from top_down_planning.orchestrator.prepared_run_factory import PreparedRunFactory
from top_down_planning.orchestrator.prepared_unit_executor import PreparedUnitExecutor
from top_down_planning.package.builder import ExecutionPackageBuilder
from top_down_planning.package.lineage import (
    accepted_result_digest,
    accepted_result_record,
    validate_attach_dependency_consistency,
)
from top_down_planning.package.loader import ExecutionPackageError, ExecutionPackageLoader, LoadedExecutionPackage
from top_down_planning.package.store_persist import persist_package_in_store
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.sub_tdp_state import (
    initial_sub_tdp_state_from_package,
    merge_sub_tdp_state_into_production,
)
from tests.conftest import run_cli
from tests.helpers import accept_child_run, create_run_kwargs
from tests.unit.test_prepared_runs import _built_package
from tests.unit.test_production_auth_alignment import write_config
from tests.unit.test_sub_tdp_defect_pass import _build_package, _force_run_fields, _item


def _dependent_plan_with_resources(run_id: str) -> Plan:
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
        },
    )


def _build_package_with_shared_resource(tmp_path: Path) -> tuple[FileRunStore, Path, object]:
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
    reviewer:
      resources:
        - shared/
""",
        ),
        cwd=workspace,
    )
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T005001-005001"
    plan = _dependent_plan_with_resources(run_id)
    kwargs = create_run_kwargs(workspace, resolved_config=config)
    store.create_run(run_id, plan=plan, phase="plan_validated", **kwargs)
    from tests.helpers import whole_plan_approval_record

    store.save_review(run_id, whole_plan_approval_record(store, run_id))
    output_dir = tmp_path / "pkg"
    ExecutionPackageBuilder().build_from_planning_run(
        store, run_id, output_dir=output_dir
    )
    package = ExecutionPackageLoader().load(output_dir, verify_workspace=False)
    return store, output_dir, package


def test_child_b_starts_after_upstream_modifies_configured_resource(tmp_path: Path) -> None:
    """P0#1: resource drift authorized by accepted upstream child must not block child B."""

    store, _output_dir, package = _build_package_with_shared_resource(tmp_path)
    shared = tmp_path / "shared" / "state.json"

    child_a_id = PreparedUnitExecutor().create_or_load_child_run(
        store,
        package,
        "item-a",
        resolved_config=package.resolved_config,
        invocation={"command": "execute"},
    )
    shared.write_text('{"version": 2}\n', encoding="utf-8")
    accept_child_run(
        store,
        child_a_id,
        outputs=[{"id": "out-a", "type": "artifact", "ref": "shared/state.json"}],
        contributions=[
            {
                "item_id": "item-a",
                "output_refs": ["out-a"],
                "summary": "Updated shared state.",
            }
        ],
        claim_assessment="A done",
    )

    child_b_id = PreparedUnitExecutor().create_or_load_child_run(
        store,
        package,
        "item-b",
        resolved_config=package.resolved_config,
        invocation={"command": "execute"},
        explicit_upstream={"item-a": child_a_id},
        explicit_upstream_only=True,
    )
    assert child_b_id
    child_b = store.load_run(child_b_id)
    assert child_b["context_snapshot_binding"]["resource_digests"]["shared/state.json"]


def test_explicit_upstream_rejects_wrong_unit_run(tmp_path: Path) -> None:
    """P0#2: --upstream item-a=<run-for-item-b> must be rejected."""

    store, output_dir, _ = _build_package(tmp_path)
    package = ExecutionPackageLoader().load(output_dir, verify_workspace=False)
    child_a_id = PreparedUnitExecutor().create_or_load_child_run(
        store,
        package,
        "item-a",
        resolved_config=package.resolved_config,
        invocation={"command": "execute"},
    )
    accept_child_run(store, child_a_id)
    wrong_unit_run_id = PreparedUnitExecutor().create_or_load_child_run(
        store,
        package,
        "item-b",
        resolved_config=package.resolved_config,
        invocation={"command": "execute"},
        explicit_upstream={"item-a": child_a_id},
        explicit_upstream_only=True,
    )
    accept_child_run(store, wrong_unit_run_id)

    with pytest.raises(ExecutionPackageError, match="unit_id") as exc_info:
        PreparedUnitExecutor().create_or_load_child_run(
            store,
            package,
            "item-b",
            resolved_config=package.resolved_config,
            invocation={"command": "execute"},
            explicit_upstream={"item-a": wrong_unit_run_id},
            explicit_upstream_only=True,
        )
    assert exc_info.value.code == "sub_tdp_upstream_invalid"


def test_explicit_upstream_rejects_nonexistent_run(tmp_path: Path) -> None:
    store, output_dir, _ = _build_package(tmp_path)
    package = ExecutionPackageLoader().load(output_dir, verify_workspace=False)
    with pytest.raises(ExecutionPackageError, match="upstream") as exc_info:
        PreparedUnitExecutor().create_or_load_child_run(
            store,
            package,
            "item-b",
            resolved_config=package.resolved_config,
            invocation={"command": "execute"},
            explicit_upstream={"item-a": "run-20260101T120000-000001"},
            explicit_upstream_only=True,
        )
    assert exc_info.value.code == "sub_tdp_upstream_invalid"


def test_attach_rejects_child_built_against_different_upstream_result(tmp_path: Path) -> None:
    """P0#3: B produced against A1 cannot attach when parent has A2."""

    store, output_dir, _ = _build_package(tmp_path)
    package = ExecutionPackageLoader().load(output_dir, verify_workspace=False)
    config = package.resolved_config

    a1 = PreparedUnitExecutor().create_or_load_child_run(
        store, package, "item-a", resolved_config=config, invocation={"command": "execute"}
    )
    accept_child_run(store, a1, claim_assessment="A1")

    b_id = PreparedUnitExecutor().create_or_load_child_run(
        store,
        package,
        "item-b",
        resolved_config=config,
        invocation={"command": "execute"},
        explicit_upstream={"item-a": a1},
        explicit_upstream_only=True,
    )
    accept_child_run(store, b_id, claim_assessment="B against A1")

    a2 = PreparedUnitExecutor().create_or_load_child_run(
        store, package, "item-a", resolved_config=config, invocation={"command": "execute"}
    )
    accept_child_run(store, a2, claim_assessment="A2")
    a2_production = store.load_production(a2)
    a2_accepted = accepted_result_record(
        child_run=store.load_run(a2),
        child_production=a2_production,
        unit_id="item-a",
        unit_plan_digest=package.units["item-a"].plan_digest,
        package_id=str(package.manifest.get("package_id") or ""),
        package_digest=str(package.manifest.get("package_digest") or ""),
        assigned_subtree_digest=package.units["item-a"].assigned_subtree_digest,
    )
    a2_result_digest = accepted_result_digest(a2_accepted)
    a1_production = store.load_production(a1)
    a1_accepted = accepted_result_record(
        child_run=store.load_run(a1),
        child_production=a1_production,
        unit_id="item-a",
        unit_plan_digest=package.units["item-a"].plan_digest,
        package_id=str(package.manifest.get("package_id") or ""),
        package_digest=str(package.manifest.get("package_digest") or ""),
        assigned_subtree_digest=package.units["item-a"].assigned_subtree_digest,
    )
    assert accepted_result_digest(a1_accepted) != a2_result_digest

    parent_id = PreparedRunFactory().create_parent_run(
        store, package, resolved_config=config, invocation={"command": "execute"}
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
    production = store.load_production(parent_id)
    parent_binding = store.load_run(parent_id).get("package_binding") or {}
    state = initial_sub_tdp_state_from_package(
        package.manifest,
        manifest_path=str(parent_binding.get("manifest_path") or package.manifest_path),
        units=units,
        package_units=package.units,
    )
    state["units"][0]["child_run_id"] = a2
    state["units"][0]["status"] = "completed"
    state["units"][0]["accepted_result"] = a2_accepted
    state["units"][0]["accepted_result_digest"] = a2_result_digest
    merged = merge_sub_tdp_state_into_production(production, state)
    expected_revision = int(production["revision"])
    merged["revision"] = expected_revision + 1
    store.save_production(parent_id, merged, expected_revision)

    child_b_run = store.load_run(b_id)
    error = validate_attach_dependency_consistency(
        child_run=child_b_run,
        package=package,
        orchestration_state=state,
        plan_item_id="item-b",
    )
    assert error is not None
    assert "item-a" in error


def test_terminal_child_reuse_revalidates_delivery(tmp_path: Path) -> None:
    """P1#4: corrupted terminal child must not be reused without revalidation."""

    store, _, package = _built_package(tmp_path)
    config = create_run_kwargs(tmp_path)["resolved_config"]
    child_id = PreparedRunFactory().create_child_run(
        store,
        package,
        package.units["item-foundation"],
        resolved_config=config,
        invocation={"command": "execute"},
    )
    accept_child_run(store, child_id)
    run = store.load_run(child_id)
    binding = dict(run.get("package_binding") or {})
    binding["whole_output_review_digest"] = "0" * 64
    _force_run_fields(store, child_id, package_binding=binding)

    executor = PreparedUnitExecutor()
    with pytest.raises(ExecutionPackageError, match="delivery invalid|whole_output"):
        executor.drive_child_run(
            store,
            child_id,
            create_provider=lambda *_a, **_k: None,
            workspace=tmp_path,
        )


def test_persist_package_rejects_id_collision_with_different_digest(tmp_path: Path) -> None:
    """P1#10: same package_id with different digest must fail, not overwrite."""

    store, _, package = _built_package(tmp_path)
    persist_package_in_store(store.root, package)
    import copy

    mutated_manifest = copy.deepcopy(package.manifest)
    mutated_manifest["package_digest"] = "f" * 64
    mutated = LoadedExecutionPackage(
        manifest_path=package.manifest_path,
        manifest=mutated_manifest,
        parent_plan=package.parent_plan,
        units=package.units,
        workspace_path=package.workspace_path,
        resolved_config=package.resolved_config,
    )
    with pytest.raises(ExecutionPackageError, match="refusing to replace"):
        persist_package_in_store(store.root, mutated)


def test_execute_manifest_requires_manifest_json_filename(tmp_path: Path) -> None:
    """P1#11: --manifest must reference manifest.json, not a sibling JSON file."""

    store, _, package = _built_package(tmp_path)
    sibling = package.manifest_path.parent / "not-manifest.json"
    sibling.write_text("{}", encoding="utf-8")
    config_path = tmp_path / "project.yaml"
    config_path.write_text(
        "runtime:\n  runs_dir: runs\nprovider:\n  name: stub\n",
        encoding="utf-8",
    )
    result = run_cli(
        [
            "execute",
            "--manifest",
            str(sibling),
            "--parent-only",
            "--config",
            str(config_path),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--stream-json",
        ]
    )
    assert result.exit_code != 0
    payload = result.json()
    assert payload.get("ok") is False


def test_child_reuse_completes_missing_bindings_after_factory_only_create(
    tmp_path: Path,
) -> None:
    """Factory-created dependent children must carry upstream; executor reuses them."""

    store, output_dir, _plan = _build_package(tmp_path)
    package = ExecutionPackageLoader().load(output_dir, verify_workspace=False)
    config = package.resolved_config
    parent_id = "parent-run-1"
    executor = PreparedUnitExecutor()

    child_a_id = executor.create_or_load_child_run(
        store,
        package,
        "item-a",
        resolved_config=config,
        invocation={"command": "execute", "observability": {}},
        parent_run_id=parent_id,
    )
    accept_child_run(store, child_a_id)

    a_accepted = accepted_result_record(
        child_run=store.load_run(child_a_id),
        child_production=store.load_production(child_a_id),
        unit_id="item-a",
        unit_plan_digest=package.units["item-a"].plan_digest,
        package_id=str(package.manifest.get("package_id") or ""),
        package_digest=str(package.manifest.get("package_digest") or ""),
        assigned_subtree_digest=package.units["item-a"].assigned_subtree_digest,
    )
    from top_down_planning.package.lineage import upstream_accepted_result_binding

    wrapper = upstream_accepted_result_binding(
        a_accepted,
        upstream_contract_digest=package.units["item-a"].assigned_subtree_digest,
    )
    child_b_id = PreparedRunFactory().create_child_run(
        store,
        package,
        package.units["item-b"],
        resolved_config=config,
        invocation={
            "command": "execute",
            "observability": {},
            "sub_tdp": {"parent_run_id": parent_id, "unit_id": "item-b"},
        },
        upstream_accepted_results=[wrapper],
    )
    binding_before = store.load_run(child_b_id).get("package_binding") or {}
    assert len(binding_before.get("upstream_accepted_results") or []) == 1
    assert isinstance(binding_before.get("external_prerequisites"), list)

    child_b_retry = executor.create_or_load_child_run(
        store,
        package,
        "item-b",
        resolved_config=config,
        invocation={"command": "execute", "observability": {}},
        parent_run_id=parent_id,
        explicit_upstream={"item-a": child_a_id},
        explicit_upstream_only=True,
    )
    assert child_b_retry == child_b_id
    binding_after = store.load_run(child_b_id).get("package_binding") or {}
    assert isinstance(binding_after.get("upstream_accepted_results"), list)
    assert isinstance(binding_after.get("external_prerequisites"), list)
    assert len(binding_after["upstream_accepted_results"]) == 1


def test_prepare_resume_rejects_child_missing_binding_keys(tmp_path: Path) -> None:
    """P1: prepared child resume requires upstream and external prerequisite keys."""

    from top_down_planning.orchestrator.prepare_resume import (
        PrepareResumeBlockedError,
        prepare_resume,
    )

    store, output_dir, _plan = _build_package(tmp_path)
    package = ExecutionPackageLoader().load(output_dir, verify_workspace=False)
    config = package.resolved_config
    parent_id = "parent-run-1"
    executor = PreparedUnitExecutor()

    child_a_id = executor.create_or_load_child_run(
        store,
        package,
        "item-a",
        resolved_config=config,
        invocation={"command": "execute"},
        parent_run_id=parent_id,
    )
    accept_child_run(store, child_a_id)

    a_accepted = accepted_result_record(
        child_run=store.load_run(child_a_id),
        child_production=store.load_production(child_a_id),
        unit_id="item-a",
        unit_plan_digest=package.units["item-a"].plan_digest,
        package_id=str(package.manifest.get("package_id") or ""),
        package_digest=str(package.manifest.get("package_digest") or ""),
        assigned_subtree_digest=package.units["item-a"].assigned_subtree_digest,
    )
    from top_down_planning.package.lineage import upstream_accepted_result_binding

    wrapper = upstream_accepted_result_binding(
        a_accepted,
        upstream_contract_digest=package.units["item-a"].assigned_subtree_digest,
    )
    child_b_id = PreparedRunFactory().create_child_run(
        store,
        package,
        package.units["item-b"],
        resolved_config=config,
        invocation={
            "command": "execute",
            "sub_tdp": {"parent_run_id": parent_id, "unit_id": "item-b"},
        },
        upstream_accepted_results=[wrapper],
    )
    run = store.load_run(child_b_id)
    expected = int(run["revision"])
    run = dict(run)
    binding = dict(run.get("package_binding") or {})
    binding.pop("upstream_accepted_results", None)
    binding.pop("external_prerequisites", None)
    run["package_binding"] = binding
    run["revision"] = expected + 1
    run["status"] = "paused"
    run["stop"] = {
        "code": "user_cancelled",
        "category": "operational",
        "phase": "production",
        "message": "paused",
        "role": None,
        "details": {},
    }
    store.save_run(child_b_id, run, expected)

    candidate = store.load_resolved_config(child_b_id)
    with pytest.raises(PrepareResumeBlockedError, match="upstream_accepted_results"):
        prepare_resume(store, child_b_id, candidate)


def test_factory_child_binds_upstream_resource_snapshot_at_create(
    tmp_path: Path,
) -> None:
    """Dependent factory create with upstream authorizes resource drift at create time."""

    store, _output_dir, package = _build_package_with_shared_resource(tmp_path)
    shared = tmp_path / "shared" / "state.json"
    parent_id = "parent-run-1"
    config = package.resolved_config

    child_a_id = PreparedUnitExecutor().create_or_load_child_run(
        store,
        package,
        "item-a",
        resolved_config=config,
        invocation={"command": "execute"},
        parent_run_id=parent_id,
    )
    shared.write_text('{"version": 2}\n', encoding="utf-8")
    accept_child_run(
        store,
        child_a_id,
        outputs=[{"id": "out-a", "type": "artifact", "ref": "shared/state.json"}],
        contributions=[
            {
                "item_id": "item-a",
                "output_refs": ["out-a"],
                "summary": "Updated shared state.",
            }
        ],
        claim_assessment="A done",
    )
    a_accepted = accepted_result_record(
        child_run=store.load_run(child_a_id),
        child_production=store.load_production(child_a_id),
        unit_id="item-a",
        unit_plan_digest=package.units["item-a"].plan_digest,
        package_id=str(package.manifest.get("package_id") or ""),
        package_digest=str(package.manifest.get("package_digest") or ""),
        assigned_subtree_digest=package.units["item-a"].assigned_subtree_digest,
    )
    from top_down_planning.package.lineage import upstream_accepted_result_binding

    wrapper = upstream_accepted_result_binding(
        a_accepted,
        upstream_contract_digest=package.units["item-a"].assigned_subtree_digest,
    )
    child_b_id = PreparedRunFactory().create_child_run(
        store,
        package,
        package.units["item-b"],
        resolved_config=config,
        invocation={
            "command": "execute",
            "sub_tdp": {"parent_run_id": parent_id, "unit_id": "item-b"},
        },
        upstream_accepted_results=[wrapper],
        workspace_baseline_results=[wrapper],
    )
    snapshot = store.load_run(child_b_id).get("context_snapshot_binding") or {}
    assert "shared/state.json" in (snapshot.get("resource_digests") or {})


def test_continue_child_sub_tdp_revalidates_terminal_delivery(tmp_path: Path) -> None:
    """Terminal reuse via continue_child_sub_tdp must revalidate delivery."""

    from top_down_planning.orchestrator.sub_tdp_child_driver import continue_child_sub_tdp

    store, _, package = _built_package(tmp_path)
    config = create_run_kwargs(tmp_path)["resolved_config"]
    child_id = PreparedRunFactory().create_child_run(
        store,
        package,
        package.units["item-foundation"],
        resolved_config=config,
        invocation={"command": "execute"},
    )
    accept_child_run(store, child_id)
    run = store.load_run(child_id)
    binding = dict(run.get("package_binding") or {})
    binding["whole_output_review_digest"] = "0" * 64
    _force_run_fields(store, child_id, package_binding=binding)

    with pytest.raises(ExecutionPackageError, match="delivery invalid|whole_output"):
        continue_child_sub_tdp(
            store,
            child_id,
            create_provider=lambda *_a, **_k: None,
            workspace=tmp_path,
        )


def test_prepare_resume_revalidates_parent_attached_child_delivery(
    tmp_path: Path,
) -> None:
    """Parent resume must revalidate live delivery for attached completed children."""

    from top_down_planning.domain.sub_tdp_units import SubTdpUnit
    from top_down_planning.orchestrator.phases import SUB_TDPS
    from top_down_planning.orchestrator.prepare_resume import (
        PrepareResumeBlockedError,
        prepare_resume,
    )
    from top_down_planning.persistence.sub_tdp_state import (
        initial_sub_tdp_state_from_package,
        merge_sub_tdp_state_into_production,
    )
    from top_down_planning.package.lineage import (
        accepted_result_digest,
        accepted_result_record,
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
    accepted = accepted_result_record(
        child_run=store.load_run(child_id),
        child_production=store.load_production(child_id),
        unit_id="item-foundation",
        unit_plan_digest=package.units["item-foundation"].plan_digest,
        package_id=str(package.manifest.get("package_id") or ""),
        package_digest=str(package.manifest.get("package_digest") or ""),
        assigned_subtree_digest=package.units["item-foundation"].assigned_subtree_digest,
    )
    state["units"][0]["child_run_id"] = child_id
    state["units"][0]["status"] = "completed"
    state["units"][0]["accepted_result"] = accepted
    state["units"][0]["accepted_result_digest"] = accepted_result_digest(accepted)
    merged = merge_sub_tdp_state_into_production(production, state)
    expected_revision = int(production["revision"])
    merged["revision"] = expected_revision + 1
    store.save_production(parent_id, merged, expected_revision)

    child_run = store.load_run(child_id)
    binding = dict(child_run.get("package_binding") or {})
    binding["whole_output_review_digest"] = "0" * 64
    _force_run_fields(store, child_id, package_binding=binding)

    candidate = store.load_resolved_config(parent_id)
    with pytest.raises(PrepareResumeBlockedError, match="child delivery invalid"):
        prepare_resume(store, parent_id, candidate)


# ---------------------------------------------------------------------------
# Remaining P0 blockers from temp/tdp-code-review.md
# ---------------------------------------------------------------------------


def _independent_plan_with_resources(run_id: str) -> Plan:
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
            "item-b": _item("item-b", parent_id=PLAN_ROOT_ITEM_ID, order_key="2", title="B"),
        },
    )


def _chain_plan_with_resources(run_id: str) -> Plan:
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


def _build_package_from_plan(
    tmp_path: Path,
    plan: Plan,
    *,
    run_id: str,
) -> tuple[FileRunStore, Path, object]:
    workspace = tmp_path
    shared = workspace / "shared" / "state.json"
    shared.parent.mkdir(parents=True, exist_ok=True)
    if not shared.is_file():
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
    reviewer:
      resources:
        - shared/
""",
        ),
        cwd=workspace,
    )
    store = FileRunStore(tmp_path / "runs")
    kwargs = create_run_kwargs(workspace, resolved_config=config)
    store.create_run(run_id, plan=plan, phase="plan_validated", **kwargs)
    from tests.helpers import whole_plan_approval_record

    store.save_review(run_id, whole_plan_approval_record(store, run_id))
    output_dir = tmp_path / "pkg"
    ExecutionPackageBuilder().build_from_planning_run(
        store, run_id, output_dir=output_dir
    )
    package = ExecutionPackageLoader().load(output_dir, verify_workspace=False)
    return store, output_dir, package


def _accept_shared_resource_change(
    store: FileRunStore,
    child_id: str,
    *,
    item_id: str,
    workspace: Path,
) -> None:
    # Write accepted bytes before capture so workspace_changes sha256 matches live files.
    (workspace / "shared" / "state.json").write_text(
        '{"version": 2}\n', encoding="utf-8"
    )
    accept_child_run(
        store,
        child_id,
        outputs=[{"id": f"out-{item_id}", "type": "artifact", "ref": "shared/state.json"}],
        contributions=[
            {
                "item_id": item_id,
                "output_refs": [f"out-{item_id}"],
                "summary": f"{item_id} updated shared state.",
            }
        ],
        claim_assessment=f"{item_id} done",
    )


def test_independent_unit_b_starts_after_sibling_a_modifies_configured_resource(
    tmp_path: Path,
) -> None:
    """P0#1: independent units share cumulative workspace baseline, not only deps."""

    plan = _independent_plan_with_resources("run-20260101T005101-005101")
    store, _output_dir, package = _build_package_from_plan(
        tmp_path, plan, run_id="run-20260101T005101-005101"
    )
    parent_id = PreparedRunFactory().create_parent_run(
        store,
        package,
        resolved_config=package.resolved_config,
        invocation={"command": "execute"},
    )
    from top_down_planning.domain.sub_tdp_units import SubTdpUnit
    from top_down_planning.persistence.sub_tdp_state import (
        initial_sub_tdp_state_from_package,
        merge_sub_tdp_state_into_production,
    )
    from top_down_planning.package.lineage import (
        accepted_result_digest,
        accepted_result_record,
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
    production = store.load_production(parent_id)
    parent_binding = store.load_run(parent_id).get("package_binding") or {}
    state = initial_sub_tdp_state_from_package(
        package.manifest,
        manifest_path=str(parent_binding.get("manifest_path") or package.manifest_path),
        units=units,
        package_units=package.units,
    )

    child_a_id = PreparedUnitExecutor().create_or_load_child_run(
        store,
        package,
        "item-a",
        resolved_config=package.resolved_config,
        invocation={"command": "execute"},
        parent_run_id=parent_id,
        orchestration_state=state,
    )
    _accept_shared_resource_change(
        store, child_a_id, item_id="item-a", workspace=tmp_path
    )
    accepted = accepted_result_record(
        child_run=store.load_run(child_a_id),
        child_production=store.load_production(child_a_id),
        unit_id="item-a",
        unit_plan_digest=package.units["item-a"].plan_digest,
        package_id=str(package.manifest.get("package_id") or ""),
        package_digest=str(package.manifest.get("package_digest") or ""),
        assigned_subtree_digest=package.units["item-a"].assigned_subtree_digest,
    )
    state["units"][0]["child_run_id"] = child_a_id
    state["units"][0]["status"] = "completed"
    state["units"][0]["accepted_result"] = accepted
    state["units"][0]["accepted_result_digest"] = accepted_result_digest(accepted)
    merged = merge_sub_tdp_state_into_production(production, state)
    expected_revision = int(production["revision"])
    merged["revision"] = expected_revision + 1
    store.save_production(parent_id, merged, expected_revision)

    child_b_id = PreparedUnitExecutor().create_or_load_child_run(
        store,
        package,
        "item-b",
        resolved_config=package.resolved_config,
        invocation={"command": "execute"},
        parent_run_id=parent_id,
        orchestration_state=state,
    )
    assert child_b_id
    child_b = store.load_run(child_b_id)
    assert child_b["context_snapshot_binding"]["resource_digests"]["shared/state.json"]


def test_transitive_unit_c_starts_after_a_and_b_modify_shared_resource(
    tmp_path: Path,
) -> None:
    """P0#1: A→B→C must authorize A's lingering workspace change via baseline closure."""

    plan = _chain_plan_with_resources("run-20260101T005201-005201")
    store, _output_dir, package = _build_package_from_plan(
        tmp_path, plan, run_id="run-20260101T005201-005201"
    )
    shared = tmp_path / "shared" / "state.json"

    child_a_id = PreparedUnitExecutor().create_or_load_child_run(
        store,
        package,
        "item-a",
        resolved_config=package.resolved_config,
        invocation={"command": "execute"},
    )
    _accept_shared_resource_change(
        store, child_a_id, item_id="item-a", workspace=tmp_path
    )

    child_b_id = PreparedUnitExecutor().create_or_load_child_run(
        store,
        package,
        "item-b",
        resolved_config=package.resolved_config,
        invocation={"command": "execute"},
        explicit_upstream={"item-a": child_a_id},
        explicit_upstream_only=True,
    )
    (tmp_path / "shared" / "b.json").write_text('{"from": "b"}\n', encoding="utf-8")
    accept_child_run(
        store,
        child_b_id,
        outputs=[{"id": "out-b", "type": "artifact", "ref": "shared/b.json"}],
        contributions=[
            {
                "item_id": "item-b",
                "output_refs": ["out-b"],
                "summary": "B produced b.json",
            }
        ],
        claim_assessment="B done",
    )
    # A's change remains; B did not re-attest shared/state.json
    assert shared.read_text(encoding="utf-8") == '{"version": 2}\n'

    child_c_id = PreparedUnitExecutor().create_or_load_child_run(
        store,
        package,
        "item-c",
        resolved_config=package.resolved_config,
        invocation={"command": "execute"},
        explicit_upstream={"item-b": child_b_id},
        explicit_upstream_only=True,
    )
    assert child_c_id
    child_c = store.load_run(child_c_id)
    assert "shared/state.json" in child_c["context_snapshot_binding"]["resource_digests"]


def test_parent_resume_authorizes_attached_child_resource_change(tmp_path: Path) -> None:
    """P0#2: parent resume must authorize configured-resource drift from attached children."""

    from top_down_planning.domain.sub_tdp_units import SubTdpUnit
    from top_down_planning.orchestrator.phases import SUB_TDPS
    from top_down_planning.orchestrator.prepare_resume import prepare_resume
    from top_down_planning.package.lineage import (
        accepted_result_digest,
        accepted_result_record,
    )
    from top_down_planning.persistence.sub_tdp_state import (
        initial_sub_tdp_state_from_package,
        merge_sub_tdp_state_into_production,
    )

    store, _output_dir, package = _build_package_with_shared_resource(tmp_path)
    config = package.resolved_config
    parent_id = PreparedRunFactory().create_parent_run(
        store, package, resolved_config=config, invocation={"command": "execute"}
    )
    child_id = PreparedUnitExecutor().create_or_load_child_run(
        store,
        package,
        "item-a",
        resolved_config=config,
        invocation={"command": "execute"},
        parent_run_id=parent_id,
    )
    _accept_shared_resource_change(
        store, child_id, item_id="item-a", workspace=tmp_path
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
    accepted = accepted_result_record(
        child_run=store.load_run(child_id),
        child_production=store.load_production(child_id),
        unit_id="item-a",
        unit_plan_digest=package.units["item-a"].plan_digest,
        package_id=str(package.manifest.get("package_id") or ""),
        package_digest=str(package.manifest.get("package_digest") or ""),
        assigned_subtree_digest=package.units["item-a"].assigned_subtree_digest,
    )
    state["units"][0]["child_run_id"] = child_id
    state["units"][0]["status"] = "completed"
    state["units"][0]["accepted_result"] = accepted
    state["units"][0]["accepted_result_digest"] = accepted_result_digest(accepted)
    merged = merge_sub_tdp_state_into_production(production, state)
    expected_revision = int(production["revision"])
    merged["revision"] = expected_revision + 1
    store.save_production(parent_id, merged, expected_revision)

    candidate = store.load_resolved_config(parent_id)
    plan = prepare_resume(store, parent_id, candidate)
    assert plan.validation.context_binding_valid is True


def test_paused_child_rebinding_does_not_reject_own_production_evidence(
    tmp_path: Path,
) -> None:
    """P0#3: started/paused child must not be rebased against package+upstream only."""

    from top_down_planning.orchestrator.phases import PRODUCTION

    store, _output_dir, package = _build_package_with_shared_resource(tmp_path)
    shared = tmp_path / "shared" / "state.json"
    config = package.resolved_config

    child_a_id = PreparedUnitExecutor().create_or_load_child_run(
        store, package, "item-a", resolved_config=config, invocation={"command": "execute"}
    )
    accept_child_run(store, child_a_id)

    child_b_id = PreparedUnitExecutor().create_or_load_child_run(
        store,
        package,
        "item-b",
        resolved_config=config,
        invocation={"command": "execute"},
        explicit_upstream={"item-a": child_a_id},
        explicit_upstream_only=True,
    )
    # Simulate B recording its own resource-changing production batch, then pausing.
    from tests.helpers import apply_production

    run = store.load_run(child_b_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["phase"] = PRODUCTION
    store.save_run(child_b_id, run, expected)
    plan = store.load_plan_model(child_b_id)
    work_item_ids = [
        item_id for item_id, item in plan.items.items() if item.kind == "work"
    ]
    shared.write_text('{"version": "b-local"}\n', encoding="utf-8")
    apply_production(
        store,
        child_b_id,
        {
            "production_revision": int(store.load_production(child_b_id)["revision"]),
            "plan_items": work_item_ids,
            "dispositions": {
                item_id: {"disposition": "completed", "evidence": "done"}
                for item_id in work_item_ids
            },
            "outputs": [
                {"id": "out-b-local", "type": "artifact", "ref": "shared/state.json"}
            ],
            "contributions": [
                {
                    "item_id": work_item_ids[0],
                    "output_refs": ["out-b-local"],
                    "summary": "B local change",
                }
            ],
            "summary": "batch",
            "empty_output": False,
        },
        handler="apply",
    )()
    run = store.load_run(child_b_id)
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
    store.save_run(child_b_id, run, expected)

    # Parent resume/rebind of B must not treat B's own evidence as unauthorized drift.
    reused = PreparedUnitExecutor().create_or_load_child_run(
        store,
        package,
        "item-b",
        resolved_config=config,
        invocation={"command": "execute"},
        existing_child_run_id=child_b_id,
        explicit_upstream={"item-a": child_a_id},
        explicit_upstream_only=True,
    )
    assert reused == child_b_id


def test_validate_accepted_child_rejects_mutated_production_after_approval(
    tmp_path: Path,
) -> None:
    """P0#4: recompute live output digest; reject post-acceptance production mutation."""

    from top_down_planning.package.lineage import validate_accepted_child_delivery

    store, _, package = _built_package(tmp_path)
    config = create_run_kwargs(tmp_path)["resolved_config"]
    child_id = PreparedRunFactory().create_child_run(
        store,
        package,
        package.units["item-foundation"],
        resolved_config=config,
        invocation={"command": "execute"},
    )
    accept_child_run(store, child_id)
    production = store.load_production(child_id)
    expected = int(production["revision"])
    production = dict(production)
    production["revision"] = expected + 1
    claim = dict(production.get("completion_claim") or {})
    claim["goal_assessment"] = "mutated after acceptance"
    production["completion_claim"] = claim
    store.save_production(child_id, production, expected)

    with pytest.raises(ValueError, match="output digest"):
        validate_accepted_child_delivery(
            store=store,
            child_run_id=child_id,
            verify_evidence=False,
        )


def test_loader_rejects_malicious_package_ids(tmp_path: Path) -> None:
    """P0#5: package_id must be a safe store id; path escape must fail closed."""

    store, _, package = _built_package(tmp_path)
    malicious_ids = ["../outside", "../../outside", "/absolute/path", "", "bad/sep"]
    for package_id in malicious_ids:
        mutated = copy.deepcopy(package.manifest)
        mutated["package_id"] = package_id
        manifest_path = tmp_path / f"evil-{hash(package_id) & 0xFFFF}" / "manifest.json"
        manifest_path.parent.mkdir(parents=True)
        # Minimal invalid package dir: copy real package then overwrite manifest id
        import shutil

        shutil.copytree(package.manifest_path.parent, manifest_path.parent, dirs_exist_ok=True)
        (manifest_path.parent / "manifest.json").write_text(
            __import__("json").dumps(mutated),
            encoding="utf-8",
        )
        with pytest.raises(ExecutionPackageError):
            ExecutionPackageLoader().load(manifest_path.parent, verify_workspace=False)


def test_persist_rejects_package_id_path_escape(tmp_path: Path) -> None:
    """P0#5: persist must keep package roots under .execution_packages."""

    store, _, package = _built_package(tmp_path)
    mutated_manifest = copy.deepcopy(package.manifest)
    mutated_manifest["package_id"] = "../outside"
    mutated = LoadedExecutionPackage(
        manifest_path=package.manifest_path,
        manifest=mutated_manifest,
        parent_plan=package.parent_plan,
        units=package.units,
        workspace_path=package.workspace_path,
        resolved_config=package.resolved_config,
    )
    with pytest.raises((ExecutionPackageError, ValueError)):
        persist_package_in_store(store.root, mutated)


def test_context_auth_rejects_paths_only_present_in_live_production(
    tmp_path: Path,
) -> None:
    """Context authorization uses accepted workspace_changes only — never live production."""

    from top_down_planning.package.execution_validation import (
        verify_package_context_snapshot_with_baseline,
    )
    from top_down_planning.package.lineage import (
        accepted_result_record,
        upstream_accepted_result_binding,
    )

    store, _output_dir, package = _build_package_with_shared_resource(tmp_path)
    shared = tmp_path / "shared" / "state.json"
    config = package.resolved_config

    child_a_id = PreparedUnitExecutor().create_or_load_child_run(
        store, package, "item-a", resolved_config=config, invocation={"command": "execute"}
    )
    accept_child_run(
        store,
        child_a_id,
        outputs=[{"id": "out-a", "type": "artifact", "ref": "shared/other.json"}],
        contributions=[
            {
                "item_id": "item-a",
                "output_refs": ["out-a"],
                "summary": "Wrote other.json",
            }
        ],
        claim_assessment="A done",
    )
    # Capture immutable accepted result before live production is mutated.
    accepted = accepted_result_record(
        child_run=store.load_run(child_a_id),
        child_production=store.load_production(child_a_id),
        unit_id="item-a",
        unit_plan_digest=package.units["item-a"].plan_digest,
        package_id=str(package.manifest.get("package_id") or ""),
        package_digest=str(package.manifest.get("package_digest") or ""),
        assigned_subtree_digest=package.units["item-a"].assigned_subtree_digest,
    )
    assert all(
        str(ref.get("ref") or "") != "shared/state.json"
        for ref in accepted.get("output_refs") or []
        if isinstance(ref, dict)
    )
    wrapper = upstream_accepted_result_binding(
        accepted,
        upstream_contract_digest=package.units["item-a"].assigned_subtree_digest,
    )

    # Mutate live production and workspace so a production-fallback would wrongly authorize.
    production = store.load_production(child_a_id)
    expected = int(production["revision"])
    production = dict(production)
    production["revision"] = expected + 1
    batches = list(production.get("batches") or [])
    if batches:
        batch = dict(batches[0])
        result = dict(batch.get("result") or {})
        outputs = list(result.get("outputs") or [])
        outputs.append({"id": "sneaky", "type": "artifact", "ref": "shared/state.json"})
        result["outputs"] = outputs
        batch["result"] = result
        batches[0] = batch
        production["batches"] = batches
    from core_tools.persistence import atomic_write_json

    atomic_write_json(store.run_dir(child_a_id) / "production.json", production)
    shared.write_text('{"version": "unauthorized"}\n', encoding="utf-8")

    with pytest.raises(ExecutionPackageError, match="not authorized by workspace baseline"):
        verify_package_context_snapshot_with_baseline(
            package,
            store=store,
            baseline_wrappers=[wrapper],
        )


def test_prepare_resume_rejects_child_missing_workspace_baseline_key(
    tmp_path: Path,
) -> None:
    """Child resume requires workspace_baseline_accepted_results binding key."""

    from top_down_planning.orchestrator.prepare_resume import (
        PrepareResumeBlockedError,
        prepare_resume,
    )

    store, output_dir, _plan = _build_package(tmp_path)
    package = ExecutionPackageLoader().load(output_dir, verify_workspace=False)
    config = package.resolved_config
    parent_id = "parent-run-1"
    executor = PreparedUnitExecutor()

    child_a_id = executor.create_or_load_child_run(
        store,
        package,
        "item-a",
        resolved_config=config,
        invocation={"command": "execute"},
        parent_run_id=parent_id,
    )
    accept_child_run(store, child_a_id)

    child_b_id = executor.create_or_load_child_run(
        store,
        package,
        "item-b",
        resolved_config=config,
        invocation={"command": "execute"},
        parent_run_id=parent_id,
        explicit_upstream={"item-a": child_a_id},
        explicit_upstream_only=True,
    )
    run = store.load_run(child_b_id)
    expected = int(run["revision"])
    run = dict(run)
    binding = dict(run.get("package_binding") or {})
    binding.pop("workspace_baseline_accepted_results", None)
    run["package_binding"] = binding
    run["revision"] = expected + 1
    run["status"] = "paused"
    run["stop"] = {
        "code": "user_cancelled",
        "category": "operational",
        "phase": "production",
        "message": "paused",
        "role": None,
        "details": {},
    }
    store.save_run(child_b_id, run, expected)

    candidate = store.load_resolved_config(child_b_id)
    with pytest.raises(
        PrepareResumeBlockedError, match="workspace_baseline_accepted_results"
    ):
        prepare_resume(store, child_b_id, candidate)


def test_child_binding_persists_workspace_baseline_separate_from_upstream(
    tmp_path: Path,
) -> None:
    """Direct upstream and cumulative baseline must be stored as distinct fields."""

    store, _output_dir, package = _build_package_with_shared_resource(tmp_path)
    config = package.resolved_config
    child_a_id = PreparedUnitExecutor().create_or_load_child_run(
        store, package, "item-a", resolved_config=config, invocation={"command": "execute"}
    )
    _accept_shared_resource_change(
        store, child_a_id, item_id="item-a", workspace=tmp_path
    )
    child_b_id = PreparedUnitExecutor().create_or_load_child_run(
        store,
        package,
        "item-b",
        resolved_config=config,
        invocation={"command": "execute"},
        explicit_upstream={"item-a": child_a_id},
        explicit_upstream_only=True,
    )
    binding = store.load_run(child_b_id).get("package_binding") or {}
    assert "upstream_accepted_results" in binding
    assert "workspace_baseline_accepted_results" in binding
    assert len(binding["upstream_accepted_results"]) == 1
    assert len(binding["workspace_baseline_accepted_results"]) >= 1
    upstream_digests = {
        w["accepted_result_digest"] for w in binding["upstream_accepted_results"]
    }
    baseline_digests = {
        w["accepted_result_digest"] for w in binding["workspace_baseline_accepted_results"]
    }
    assert upstream_digests <= baseline_digests
