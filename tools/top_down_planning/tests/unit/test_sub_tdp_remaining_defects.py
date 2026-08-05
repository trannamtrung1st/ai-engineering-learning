"""Failing-first tests for remaining Sub-TDP review defects (#8/#10/#14/#15/#16)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from core_tools.persistence.digests import digest_text

from top_down_planning.config import compute_output_goal_digest
from top_down_planning.domain.run_kind import RUN_KIND_SUB_TDP_EXECUTION
from top_down_planning.orchestrator.prepared_run_factory import PreparedRunFactory
from top_down_planning.orchestrator.prepared_unit_executor import PreparedUnitExecutor
from top_down_planning.package.lineage import (
    accepted_result_digest,
    accepted_result_record,
    verify_accepted_result_attestation,
)
from top_down_planning.package.loader import ExecutionPackageError, ExecutionPackageLoader
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.digests import compute_plan_digest, digest_canonical_payload
from tests.helpers import create_run_kwargs
from tests.unit.test_prepared_runs import _built_package


def test_child_run_binds_unit_output_goal_digest_not_parent_config(tmp_path: Path) -> None:
    """#15: child digests.output_goal must match unit plan goal, not parent config goal."""

    store, _, package = _built_package(tmp_path)
    config = create_run_kwargs(tmp_path)["resolved_config"]
    unit = package.units["item-foundation"]
    parent_goal_digest = compute_output_goal_digest(config, base_dir=tmp_path)
    unit_goal_digest = digest_text(unit.plan.output_goal)
    assert unit_goal_digest != parent_goal_digest

    child_id = PreparedRunFactory().create_child_run(
        store,
        package,
        unit,
        resolved_config=config,
        invocation={"command": "execute", "observability": {}},
    )
    run = store.load_run(child_id)
    binding = run["package_binding"]
    assert run["digests"]["output_goal"] == unit_goal_digest
    assert binding["unit_output_goal"] == unit.plan.output_goal
    assert binding["unit_output_goal_digest"] == unit_goal_digest
    assert binding["parent_output_goal_digest"] == parent_goal_digest


def test_child_creation_is_idempotent_for_same_parent_unit(tmp_path: Path) -> None:
    """#16: crash before parent binds child_run_id must not create a second child."""

    store, _, package = _built_package(tmp_path)
    config = create_run_kwargs(tmp_path)["resolved_config"]
    executor = PreparedUnitExecutor()
    first = executor.create_or_load_child_run(
        store,
        package,
        "item-foundation",
        resolved_config=config,
        invocation={"command": "execute", "observability": {}},
        parent_run_id="parent-run-1",
    )
    second = executor.create_or_load_child_run(
        store,
        package,
        "item-foundation",
        resolved_config=config,
        invocation={"command": "execute", "observability": {}},
        parent_run_id="parent-run-1",
    )
    assert first == second
    child_runs = []
    for p in store.root.iterdir():
        if not p.is_dir() or p.name.startswith("."):
            continue
        run = store.load_run(p.name)
        if str(run.get("run_kind") or "") == RUN_KIND_SUB_TDP_EXECUTION:
            child_runs.append(p.name)
    assert child_runs == [first]


def test_accepted_result_requires_whole_output_review_id(tmp_path: Path) -> None:
    """#10: accepted-result attestation must include WOR id/digest."""

    store, _, package = _built_package(tmp_path)
    config = create_run_kwargs(tmp_path)["resolved_config"]
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
    digests = dict(run.get("digests") or {})
    digests["output"] = "a" * 64
    run["digests"] = digests
    store.save_run(child_id, run, expected)
    production = store.load_production(child_id)
    expected_prod = int(production["revision"])
    production = dict(production)
    production["revision"] = expected_prod + 1
    production["output_revision"] = 1
    production["completion_claim"] = {
        "goal_met": True,
        "status": "complete",
        "goal_assessment": "done",
    }
    store.save_production(child_id, production, expected_prod)

    with pytest.raises(ValueError, match="whole_output_review"):
        accepted_result_record(
            child_run=store.load_run(child_id),
            child_production=store.load_production(child_id),
            unit_id=unit.unit_id,
            unit_plan_digest=unit.plan_digest,
            package_id=str(package.manifest.get("package_id") or ""),
            package_digest=str(package.manifest.get("package_digest") or ""),
            assigned_subtree_digest=unit.assigned_subtree_digest,
        )


def test_verify_attestation_rejects_missing_review_id() -> None:
    accepted = {
        "schema_version": 1,
        "package_id": "pkg",
        "package_digest": "b" * 64,
        "unit_id": "item-a",
        "unit_plan_digest": "c" * 64,
        "assigned_subtree_digest": "d" * 64,
        "child_run_id": "child-1",
        "output_revision": 1,
        "output_digest": "e" * 64,
        "whole_output_review_id": "",
        "whole_output_review_digest": "",
        "outcome": "accepted",
        "evidence_digest": "f" * 64,
    }
    unit_record = {
        "accepted_result": accepted,
        "accepted_result_digest": accepted_result_digest(accepted),
    }
    with pytest.raises(ValueError, match="whole_output_review"):
        verify_accepted_result_attestation(unit_record)


def test_loader_rejects_missing_assigned_subtree_digest(tmp_path: Path) -> None:
    """#8: empty assigned_subtree_digest must hard-fail, not soft-skip."""

    store, _, package = _built_package(tmp_path)
    manifest_path = package.manifest_path
    import json

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for unit in manifest["units"]:
        unit["assigned_subtree_digest"] = ""
    # Recompute package digest would still fail subtree check first.
    from top_down_planning.package.digests import compute_package_digest

    context_digests = {
        key: str(value)
        for key, value in (manifest.get("context") or {}).items()
        if key.endswith("_digest") and value
    }
    manifest["package_digest"] = compute_package_digest(
        manifest,
        parent_plan_digest=str((manifest.get("parent") or {}).get("plan_digest") or ""),
        unit_plan_digests=[str(u.get("plan_digest") or "") for u in manifest["units"]],
        approved_plan_digest=str(
            (manifest.get("planning_run") or {}).get("approved_plan_digest") or ""
        ),
        context_digests=context_digests,
    )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ExecutionPackageError, match="assigned_subtree_digest"):
        ExecutionPackageLoader().load(manifest_path.parent, verify_workspace=False)


def test_loader_rejects_approved_plan_digest_mismatch(tmp_path: Path) -> None:
    """#8: planning_run.approved_plan_digest must match parent plan digest."""

    store, _, package = _built_package(tmp_path)
    manifest_path = package.manifest_path
    import json

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    parent_digest = compute_plan_digest(package.parent_plan)
    assert manifest["planning_run"]["approved_plan_digest"] == parent_digest
    manifest["planning_run"]["approved_plan_digest"] = "0" * 64
    from top_down_planning.package.digests import compute_package_digest

    context_digests = {
        key: str(value)
        for key, value in (manifest.get("context") or {}).items()
        if key.endswith("_digest") and value
    }
    manifest["package_digest"] = compute_package_digest(
        manifest,
        parent_plan_digest=str((manifest.get("parent") or {}).get("plan_digest") or ""),
        unit_plan_digests=[str(u.get("plan_digest") or "") for u in manifest["units"]],
        approved_plan_digest=str(manifest["planning_run"]["approved_plan_digest"]),
        context_digests=context_digests,
    )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ExecutionPackageError, match="approved_plan_digest"):
        ExecutionPackageLoader().load(manifest_path.parent, verify_workspace=False)


def test_accepted_result_includes_delivery_shape(tmp_path: Path) -> None:
    """#2: accepted results carry output_refs/contributions/completion_assessment."""

    store, _, package = _built_package(tmp_path)
    config = create_run_kwargs(tmp_path)["resolved_config"]
    unit = package.units["item-foundation"]
    child_id = PreparedRunFactory().create_child_run(
        store,
        package,
        unit,
        resolved_config=config,
        invocation={"command": "execute", "observability": {}},
    )
    production = store.load_production(child_id)
    expected_prod = int(production["revision"])
    production = dict(production)
    production["revision"] = expected_prod + 1
    production["output_revision"] = 1
    production["outputs"] = [{"path": "out.md", "kind": "file"}]
    production["contributions"] = [{"item_id": "item-foundation", "summary": "done"}]
    production["completion_claim"] = {
        "goal_met": True,
        "status": "complete",
        "goal_assessment": "Unit goal met.",
    }
    store.save_production(child_id, production, expected_prod)
    run = store.load_run(child_id)
    expected = int(run["revision"])
    run = dict(run)
    binding = dict(run.get("package_binding") or {})
    binding["whole_output_review_id"] = "review-1"
    binding["whole_output_review_digest"] = "r" * 64
    run["package_binding"] = binding
    digests = dict(run.get("digests") or {})
    from top_down_planning.persistence.digests import compute_output_digest

    digests["output"] = compute_output_digest(store.load_production(child_id))
    run["digests"] = digests
    run["revision"] = expected + 1
    run["status"] = "completed"
    run["phase"] = "output_validated"
    run["outcome"] = "accepted"
    store.save_run(child_id, run, expected)

    record = accepted_result_record(
        child_run=store.load_run(child_id),
        child_production=store.load_production(child_id),
        unit_id=unit.unit_id,
        unit_plan_digest=unit.plan_digest,
        package_id=str(package.manifest.get("package_id") or ""),
        package_digest=str(package.manifest.get("package_digest") or ""),
        assigned_subtree_digest=unit.assigned_subtree_digest,
    )
    assert record["output_refs"] == [{"path": "out.md", "kind": "file"}]
    assert record["contributions"] == [
        {"item_id": "item-foundation", "summary": "done"}
    ]
    assert record["completion_assessment"] == "Unit goal met."


def test_evidence_promotion_rejects_malformed_snapshot_ref() -> None:
    from top_down_planning.orchestrator.evidence_promotion import (
        promote_child_evidence_to_parent,
    )

    with pytest.raises(ValueError, match="snapshot_ref"):
        promote_child_evidence_to_parent(
            {"id": "ev-1", "snapshot_ref": "not/a/valid/ref"},
            child_store=MagicMock(),  # type: ignore[arg-type]
            child_run_id="child",
            parent_store=MagicMock(),  # type: ignore[arg-type]
            parent_run_id="parent",
        )


def test_parse_upstream_bindings() -> None:
    from top_down_planning.cli.execute import parse_upstream_bindings

    assert parse_upstream_bindings(["item-a=run-1", "item-b=run-2"]) == {
        "item-a": "run-1",
        "item-b": "run-2",
    }
    with pytest.raises(ValueError, match="upstream"):
        parse_upstream_bindings(["bad"])


def test_package_lineage_imports_without_circular_orchestrator_dependency() -> None:
    """Non-editable installs must import package.lineage without orchestrator cycles."""

    import importlib

    module = importlib.import_module("top_down_planning.package.lineage")
    assert hasattr(module, "ExecutionLineageValidator")
    assert hasattr(module, "validate_accepted_child_delivery")


def test_prepare_resume_revalidates_prepared_package_binding(tmp_path: Path) -> None:
    """#14: prepared resume must reload and verify package binding digests."""

    from top_down_planning.orchestrator.prepare_resume import (
        PrepareResumeBlockedError,
        prepare_resume,
    )

    store, _, package = _built_package(tmp_path)
    config = create_run_kwargs(tmp_path)["resolved_config"]
    parent_id = PreparedRunFactory().create_parent_run(
        store,
        package,
        resolved_config=config,
        invocation={"command": "execute", "observability": {}},
    )
    run = store.load_run(parent_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["status"] = "paused"
    run["stop"] = {
        "code": "sub_tdps_awaiting_children",
        "category": "operational",
        "phase": "sub_tdps",
        "message": "waiting",
        "role": None,
        "details": {},
    }
    binding = dict(run.get("package_binding") or {})
    binding["package_digest"] = "0" * 64
    run["package_binding"] = binding
    store.save_run(parent_id, run, expected)

    with pytest.raises(PrepareResumeBlockedError, match="package"):
        prepare_resume(store, parent_id, config)
