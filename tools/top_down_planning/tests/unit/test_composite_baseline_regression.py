"""End-to-end regression for explicit composite baseline lineage (A+B -> C)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from top_down_planning.domain.models import Plan
from top_down_planning.domain.plan_tree import PLAN_ROOT_ITEM_ID
from top_down_planning.domain.sub_tdp_units import SubTdpUnit
from top_down_planning.orchestrator.apply_resume import apply_resume_plan_atomically
from top_down_planning.orchestrator.phases import SUB_TDPS, WHOLE_OUTPUT_REVIEW
from top_down_planning.orchestrator.prepare_resume import (
    collect_parent_sub_tdp_authorized_workspace_changes,
    prepare_resume,
    verify_parent_sub_tdp_workspace_matches_accepted,
)
from top_down_planning.orchestrator.prepared_run_factory import PreparedRunFactory
from top_down_planning.orchestrator.prepared_unit_executor import PreparedUnitExecutor
from top_down_planning.orchestrator.whole_output_review import (
    SubTdpWholeOutputReviewAdapter,
)
from top_down_planning.package.lineage import accepted_result_digest, accepted_result_record
from top_down_planning.package.loader import ExecutionPackageError, ExecutionPackageLoader
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.sub_tdp_state import (
    initial_sub_tdp_state_from_package,
    merge_sub_tdp_state_into_production,
)
from tests.helpers import accept_child_run, create_run_kwargs, whole_plan_approval_record
from tests.unit.test_production_auth_alignment import write_config
from tests.unit.test_sub_tdp_defect_pass import _item


def _plan_parallel_composite(run_id: str) -> Plan:
    return Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Ship composite baseline.",
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
            "item-c": _item("item-c", parent_id=PLAN_ROOT_ITEM_ID, order_key="3", title="C"),
            "item-d": _item("item-d", parent_id=PLAN_ROOT_ITEM_ID, order_key="4", title="D"),
        },
    )


def _build_parallel_package(tmp_path: Path):
    from top_down_planning.config import resolve_config
    from top_down_planning.package.builder import ExecutionPackageBuilder

    workspace = tmp_path
    shared = workspace / "shared"
    shared.mkdir(parents=True)
    (shared / "a.json").write_text('{"unit": "a"}\n', encoding="utf-8")
    (shared / "b.json").write_text('{"unit": "b"}\n', encoding="utf-8")
    config = resolve_config(
        write_config(
            tmp_path / "composite-cfg.yaml",
            """
run:
  output_goal: Ship composite baseline.
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
    run_id = "run-20260101T009001-009001"
    kwargs = create_run_kwargs(workspace, resolved_config=config)
    store.create_run(
        run_id,
        plan=_plan_parallel_composite(run_id),
        phase="plan_validated",
        **kwargs,
    )
    store.save_review(run_id, whole_plan_approval_record(store, run_id))
    output_dir = tmp_path / "composite-pkg"
    ExecutionPackageBuilder().build_from_planning_run(store, run_id, output_dir=output_dir)
    package = ExecutionPackageLoader().load(output_dir, verify_workspace=False)
    return store, package, config


def _attach_completed_unit(
    store: FileRunStore,
    package,
    state: dict[str, Any],
    *,
    child_id: str,
    unit_id: str,
) -> dict[str, Any]:
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
    for unit_record in state.get("units") or []:
        if str(unit_record.get("plan_item_id") or "") == unit_id:
            unit_record["child_run_id"] = child_id
            unit_record["status"] = "completed"
            unit_record["accepted_result"] = accepted
            unit_record["accepted_result_digest"] = accepted_result_digest(accepted)
            break
    return accepted


def test_validate_child_bindings_rejects_partial_lineage_digests(tmp_path: Path) -> None:
    """Partial baseline_accepted_result_digests must not pass binding validation."""

    from top_down_planning.package.lineage import validate_child_package_bindings

    store, package, config = _build_parallel_package(tmp_path)
    executor = PreparedUnitExecutor()
    parent_id = PreparedRunFactory().create_parent_run(
        store, package, resolved_config=config, invocation={"command": "execute"},
    )
    shared = Path(package.workspace_path) / "shared"

    child_a = executor.create_or_load_child_run(
        store, package, "item-a", resolved_config=config,
        invocation={"command": "execute"}, parent_run_id=parent_id,
    )
    (shared / "a.json").write_text('{"writer": "a"}\n', encoding="utf-8")
    accept_child_run(
        store, child_a,
        outputs=[{"id": "out-a", "type": "artifact", "ref": "shared/a.json"}],
        contributions=[{"item_id": "item-a", "output_refs": ["out-a"], "summary": "A"}],
    )
    wrapper_a, _ = _wrapper_for(store, package, child_a, "item-a")

    (shared / "a.json").write_text('{"unit": "a"}\n', encoding="utf-8")
    (shared / "b.json").write_text('{"unit": "b"}\n', encoding="utf-8")

    child_b = executor.create_or_load_child_run(
        store, package, "item-b", resolved_config=config,
        invocation={"command": "execute"},
        parent_run_id=parent_id,
        explicit_upstream_only=True,
    )
    (shared / "b.json").write_text('{"writer": "b"}\n', encoding="utf-8")
    accept_child_run(
        store, child_b,
        outputs=[{"id": "out-b", "type": "artifact", "ref": "shared/b.json"}],
        contributions=[{"item_id": "item-b", "output_refs": ["out-b"], "summary": "B"}],
    )
    wrapper_b, _ = _wrapper_for(store, package, child_b, "item-b")

    (shared / "a.json").write_text('{"writer": "a"}\n', encoding="utf-8")
    (shared / "b.json").write_text('{"writer": "b"}\n', encoding="utf-8")

    child_c = executor.create_or_load_child_run(
        store, package, "item-c", resolved_config=config,
        invocation={"command": "execute"},
        parent_run_id=parent_id,
        explicit_baseline_run_ids=[child_a, child_b],
        explicit_upstream_only=True,
    )
    binding = dict(store.load_run(child_c)["package_binding"])
    binding["baseline_accepted_result_digests"] = [wrapper_b["accepted_result_digest"]]
    error = validate_child_package_bindings(binding)
    assert error is not None
    assert "exactly match" in error


def test_parallel_composite_join_c_overwrites_a_json(tmp_path: Path) -> None:
    """Independent A and B from S0; C joins A+B and overwrites a.json."""

    store, package, config = _build_parallel_package(tmp_path)
    executor = PreparedUnitExecutor()
    factory = PreparedRunFactory()
    shared = Path(package.workspace_path) / "shared"
    package_initial = str(
        (package.manifest.get("context") or {}).get("context_snapshot_digest") or ""
    )

    parent_id = factory.create_parent_run(
        store, package, resolved_config=config, invocation={"command": "execute"},
    )

    child_a = executor.create_or_load_child_run(
        store, package, "item-a", resolved_config=config,
        invocation={"command": "execute"}, parent_run_id=parent_id,
    )
    (shared / "a.json").write_text('{"writer": "a"}\n', encoding="utf-8")
    accept_child_run(
        store, child_a,
        outputs=[{"id": "out-a", "type": "artifact", "ref": "shared/a.json"}],
        contributions=[{"item_id": "item-a", "output_refs": ["out-a"], "summary": "A"}],
    )
    wrapper_a, accepted_a = _wrapper_for(store, package, child_a, "item-a")

    (shared / "a.json").write_text('{"unit": "a"}\n', encoding="utf-8")
    (shared / "b.json").write_text('{"unit": "b"}\n', encoding="utf-8")

    child_b = executor.create_or_load_child_run(
        store, package, "item-b", resolved_config=config,
        invocation={"command": "execute"},
        parent_run_id=parent_id,
        explicit_upstream_only=True,
    )
    binding_b = store.load_run(child_b)["package_binding"]
    assert binding_b["baseline_accepted_result_digests"] == []
    assert binding_b["baseline_context_snapshot_digest"] == package_initial
    (shared / "b.json").write_text('{"writer": "b"}\n', encoding="utf-8")
    accept_child_run(
        store, child_b,
        outputs=[{"id": "out-b", "type": "artifact", "ref": "shared/b.json"}],
        contributions=[{"item_id": "item-b", "output_refs": ["out-b"], "summary": "B"}],
    )
    wrapper_b, accepted_b = _wrapper_for(store, package, child_b, "item-b")

    (shared / "a.json").write_text('{"writer": "a"}\n', encoding="utf-8")
    (shared / "b.json").write_text('{"writer": "b"}\n', encoding="utf-8")

    child_c = executor.create_or_load_child_run(
        store, package, "item-c", resolved_config=config,
        invocation={"command": "execute"},
        parent_run_id=parent_id,
        explicit_baseline_run_ids=[child_a, child_b],
        explicit_upstream_only=True,
    )
    binding_c = store.load_run(child_c)["package_binding"]
    assert set(binding_c["baseline_accepted_result_digests"]) == {
        wrapper_a["accepted_result_digest"],
        wrapper_b["accepted_result_digest"],
    }
    (shared / "a.json").write_text('{"writer": "c-overwrites-a"}\n', encoding="utf-8")
    (shared / "c.json").write_text('{"writer": "c"}\n', encoding="utf-8")
    accept_child_run(
        store, child_c,
        outputs=[
            {"id": "out-c-a", "type": "artifact", "ref": "shared/a.json"},
            {"id": "out-c", "type": "artifact", "ref": "shared/c.json"},
        ],
        contributions=[
            {
                "item_id": "item-c",
                "output_refs": ["out-c-a", "out-c"],
                "summary": "C",
            },
        ],
    )
    accepted_c = accepted_result_record(
        child_run=store.load_run(child_c),
        child_production=store.load_production(child_c),
        unit_id="item-c",
        unit_plan_digest=package.units["item-c"].plan_digest,
        package_id=str(package.manifest.get("package_id") or ""),
        package_digest=str(package.manifest.get("package_digest") or ""),
        assigned_subtree_digest=package.units["item-c"].assigned_subtree_digest,
    )
    assert accepted_c["baseline_accepted_result_digests"] == binding_c[
        "baseline_accepted_result_digests"
    ]

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
    _attach_completed_unit(store, package, state, child_id=child_a, unit_id="item-a")
    _attach_completed_unit(store, package, state, child_id=child_b, unit_id="item-b")
    _attach_completed_unit(store, package, state, child_id=child_c, unit_id="item-c")
    merged = merge_sub_tdp_state_into_production(production, state)
    expected_revision = int(production["revision"])
    merged["revision"] = expected_revision + 1
    store.save_production(parent_id, merged, expected_revision)

    authorized = collect_parent_sub_tdp_authorized_workspace_changes(
        store,
        production=store.load_production(parent_id),
        workspace=package.workspace_path,
    )
    assert authorized["shared/a.json"]["sha256"] == accepted_c["workspace_changes"][
        "shared/a.json"
    ]["sha256"]
    assert "shared/b.json" in authorized
    assert "shared/c.json" in authorized
    verify_parent_sub_tdp_workspace_matches_accepted(
        store,
        production=store.load_production(parent_id),
        workspace=package.workspace_path,
    )


def test_composite_baseline_ab_then_c_parent_resume_and_closure(tmp_path: Path) -> None:
    """S0: A writes a.json, B writes b.json; C joins A+B; D uses A+B+C closure."""

    store, package, config = _build_parallel_package(tmp_path)
    executor = PreparedUnitExecutor()
    factory = PreparedRunFactory()
    shared = Path(package.workspace_path) / "shared"

    parent_id = factory.create_parent_run(
        store, package, resolved_config=config, invocation={"command": "execute"},
    )

    child_a = executor.create_or_load_child_run(
        store, package, "item-a", resolved_config=config,
        invocation={"command": "execute"}, parent_run_id=parent_id,
    )
    (shared / "a.json").write_text('{"writer": "a"}\n', encoding="utf-8")
    accept_child_run(
        store, child_a,
        outputs=[{"id": "out-a", "type": "artifact", "ref": "shared/a.json"}],
        contributions=[{"item_id": "item-a", "output_refs": ["out-a"], "summary": "A"}],
    )
    wrapper_a, _ = _wrapper_for(store, package, child_a, "item-a")

    child_b = executor.create_or_load_child_run(
        store, package, "item-b", resolved_config=config,
        invocation={"command": "execute"}, parent_run_id=parent_id,
    )
    (shared / "b.json").write_text('{"writer": "b"}\n', encoding="utf-8")
    accept_child_run(
        store, child_b,
        outputs=[{"id": "out-b", "type": "artifact", "ref": "shared/b.json"}],
        contributions=[{"item_id": "item-b", "output_refs": ["out-b"], "summary": "B"}],
    )
    wrapper_b, _ = _wrapper_for(store, package, child_b, "item-b")

    child_c = executor.create_or_load_child_run(
        store, package, "item-c", resolved_config=config,
        invocation={"command": "execute"},
        parent_run_id=parent_id,
        explicit_baseline_run_ids=[child_a, child_b],
        explicit_upstream_only=True,
    )
    binding_c = store.load_run(child_c)["package_binding"]
    assert binding_c["baseline_accepted_result_digests"] == [
        wrapper_a["accepted_result_digest"],
        wrapper_b["accepted_result_digest"],
    ]
    (shared / "c.json").write_text('{"writer": "c"}\n', encoding="utf-8")
    accept_child_run(
        store, child_c,
        outputs=[{"id": "out-c", "type": "artifact", "ref": "shared/c.json"}],
        contributions=[{"item_id": "item-c", "output_refs": ["out-c"], "summary": "C"}],
    )
    accepted_c = accepted_result_record(
        child_run=store.load_run(child_c),
        child_production=store.load_production(child_c),
        unit_id="item-c",
        unit_plan_digest=package.units["item-c"].plan_digest,
        package_id=str(package.manifest.get("package_id") or ""),
        package_digest=str(package.manifest.get("package_digest") or ""),
        assigned_subtree_digest=package.units["item-c"].assigned_subtree_digest,
    )
    assert accepted_c["baseline_accepted_result_digests"] == binding_c[
        "baseline_accepted_result_digests"
    ]

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
    _attach_completed_unit(store, package, state, child_id=child_a, unit_id="item-a")
    _attach_completed_unit(store, package, state, child_id=child_b, unit_id="item-b")
    _attach_completed_unit(store, package, state, child_id=child_c, unit_id="item-c")

    merged = merge_sub_tdp_state_into_production(production, state)
    expected_revision = int(production["revision"])
    merged["revision"] = expected_revision + 1
    store.save_production(parent_id, merged, expected_revision)

    authorized = collect_parent_sub_tdp_authorized_workspace_changes(
        store,
        production=store.load_production(parent_id),
        workspace=package.workspace_path,
    )
    assert "shared/a.json" in authorized
    assert "shared/b.json" in authorized
    assert "shared/c.json" in authorized
    verify_parent_sub_tdp_workspace_matches_accepted(
        store,
        production=store.load_production(parent_id),
        workspace=package.workspace_path,
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

    invocation = store.load_invocation(parent_id)
    plan = prepare_resume(store, parent_id, config)
    result = apply_resume_plan_atomically(
        store, plan, resolved_config=config, invocation=invocation,
    )
    assert result["ok"] is True
    assert store.load_run(parent_id)["status"] == "running"

    child_d = executor.create_or_load_child_run(
        store, package, "item-d", resolved_config=config,
        invocation={"command": "execute"},
        parent_run_id=parent_id,
    )
    binding_d = store.load_run(child_d)["package_binding"]
    baseline_digests = set(binding_d.get("baseline_accepted_result_digests") or [])
    assert wrapper_a["accepted_result_digest"] in baseline_digests
    assert wrapper_b["accepted_result_digest"] in baseline_digests
    assert accepted_result_digest(accepted_c) in baseline_digests
    (shared / "d.json").write_text('{"writer": "d"}\n', encoding="utf-8")
    accept_child_run(
        store, child_d,
        outputs=[{"id": "out-d", "type": "artifact", "ref": "shared/d.json"}],
        contributions=[{"item_id": "item-d", "output_refs": ["out-d"], "summary": "D"}],
    )
    _attach_completed_unit(store, package, state, child_id=child_d, unit_id="item-d")
    merged = merge_sub_tdp_state_into_production(
        store.load_production(parent_id),
        state,
    )
    expected_revision = int(store.load_production(parent_id)["revision"])
    merged["revision"] = expected_revision + 1
    store.save_production(parent_id, merged, expected_revision)

    production = store.load_production(parent_id)
    expected_prod = int(production["revision"])
    production = dict(production)
    production["completion_claim"] = {
        "goal_met": True,
        "goal_assessment": "Parent composite baseline validated; goal met.",
    }
    production["revision"] = expected_prod + 1
    store.save_production(parent_id, production, expected_prod)

    run = store.load_run(parent_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["phase"] = WHOLE_OUTPUT_REVIEW
    store.save_run(parent_id, run, expected)
    adapter = SubTdpWholeOutputReviewAdapter(store, parent_id)
    adapter.preflight(None)
    loop = adapter.new_loop("review-whole-output-composite")
    package_payload = adapter.build_review_package(
        store.load_run(parent_id),
        store.load_resolved_config(parent_id),
        loop,
    )
    assert len(package_payload["sub_tdp_evidence"]) == 4

    tampered = dict(store.load_production(parent_id))
    state = tampered.get("sub_tdps") or {}
    for unit_record in state.get("units") or []:
        if str(unit_record.get("plan_item_id") or "") == "item-c":
            accepted = dict(unit_record.get("accepted_result") or {})
            accepted["baseline_accepted_result_digests"] = []
            unit_record["accepted_result"] = accepted
            unit_record["accepted_result_digest"] = accepted_result_digest(accepted)
            break
    with pytest.raises((ValueError, ExecutionPackageError)):
        collect_parent_sub_tdp_authorized_workspace_changes(
            store,
            production=tampered,
            workspace=package.workspace_path,
        )


def _wrapper_for(store, package, child_id: str, unit_id: str):
    from top_down_planning.package.lineage import upstream_accepted_result_binding

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
    return upstream_accepted_result_binding(
        accepted,
        upstream_contract_digest=unit.assigned_subtree_digest,
    ), accepted
