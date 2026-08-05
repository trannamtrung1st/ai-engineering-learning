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
    shared.write_text('{"version": 2}\n', encoding="utf-8")

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
    wrong_unit_run_id = PreparedRunFactory().create_child_run(
        store,
        package,
        package.units["item-b"],
        resolved_config=package.resolved_config,
        invocation={"command": "execute"},
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
    """P0: factory-only child without bindings must be completed on executor retry."""

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
    )
    binding_before = store.load_run(child_b_id).get("package_binding") or {}
    assert binding_before.get("upstream_accepted_results") == []
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

    child_b_id = PreparedRunFactory().create_child_run(
        store,
        package,
        package.units["item-b"],
        resolved_config=config,
        invocation={
            "command": "execute",
            "sub_tdp": {"parent_run_id": parent_id, "unit_id": "item-b"},
        },
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


def test_factory_early_child_rebases_snapshot_when_upstream_retrofitted(
    tmp_path: Path,
) -> None:
    """Early factory child must rebase context snapshot when upstream is bound later."""

    store, _output_dir, package = _build_package_with_shared_resource(tmp_path)
    shared = tmp_path / "shared" / "state.json"
    parent_id = "parent-run-1"
    config = package.resolved_config

    child_b_id = PreparedRunFactory().create_child_run(
        store,
        package,
        package.units["item-b"],
        resolved_config=config,
        invocation={
            "command": "execute",
            "sub_tdp": {"parent_run_id": parent_id, "unit_id": "item-b"},
        },
    )
    snapshot_before = store.load_run(child_b_id).get("context_snapshot_binding") or {}

    child_a_id = PreparedUnitExecutor().create_or_load_child_run(
        store,
        package,
        "item-a",
        resolved_config=config,
        invocation={"command": "execute"},
        parent_run_id=parent_id,
    )
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
    shared.write_text('{"version": 2}\n', encoding="utf-8")

    child_b_retry = PreparedUnitExecutor().create_or_load_child_run(
        store,
        package,
        "item-b",
        resolved_config=config,
        invocation={"command": "execute"},
        parent_run_id=parent_id,
        explicit_upstream={"item-a": child_a_id},
        explicit_upstream_only=True,
    )
    assert child_b_retry == child_b_id
    snapshot_after = store.load_run(child_b_id).get("context_snapshot_binding") or {}
    assert snapshot_after != snapshot_before
    assert snapshot_after["resource_digests"]["shared/state.json"] != snapshot_before[
        "resource_digests"
    ]["shared/state.json"]


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