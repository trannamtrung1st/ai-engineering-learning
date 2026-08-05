"""Hard-cutover: no Sub-TDP legacy package / run_kind fallbacks."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.domain.models import Plan, PlanItem, Scope
from top_down_planning.domain.plan_tree import PLAN_ROOT_ITEM_ID
from top_down_planning.domain.run_kind import resolve_run_kind
from top_down_planning.domain.sub_tdp_units import derive_sub_tdp_units
from top_down_planning.domain.unit_plan import build_unit_plan_snapshot
from top_down_planning.orchestrator.prepared_run_factory import inherited_whole_plan_approval
from top_down_planning.package.execution_validation import verify_package_authoritative_inputs
from top_down_planning.package.loader import ExecutionPackageError, ExecutionPackageLoader
from top_down_planning.package.lineage import ExecutionLineageValidator
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs


def test_resolve_run_kind_requires_explicit_kind() -> None:
    with pytest.raises(ValueError, match="run_kind is required"):
        resolve_run_kind({"phase": "production"})


def test_create_run_persists_run_kind_by_default(tmp_path: Path) -> None:
    from top_down_planning.domain.models import Plan
    from top_down_planning.domain.plan_tree import PLAN_ROOT_ITEM_ID, seed_plan_root_item

    store = FileRunStore(tmp_path / "runs")
    plan = Plan(
        id="plan-x",
        revision=0,
        output_goal="Ship.",
        items={PLAN_ROOT_ITEM_ID: seed_plan_root_item()},
    )
    kwargs = create_run_kwargs(tmp_path)
    store.create_run(
        "run-20260101T003001-003001",
        plan=plan,
        phase="planning",
        **kwargs,
    )
    assert store.load_run("run-20260101T003001-003001")["run_kind"] == "planning"
    store.create_run(
        "run-20260101T003002-003002",
        plan=plan,
        phase="production",
        **create_run_kwargs(tmp_path),
    )
    assert (
        store.load_run("run-20260101T003002-003002")["run_kind"] == "single_execution"
    )


def test_unit_plan_snapshot_requires_package_id() -> None:
    plan = Plan(
        id="plan",
        revision=0,
        output_goal="Ship.",
        items={
            PLAN_ROOT_ITEM_ID: PlanItem(
                id=PLAN_ROOT_ITEM_ID,
                parent_id=None,
                order_key="0",
                title="Root",
                outcome="Root.",
                kind="aggregate",
            ),
            "item-a": PlanItem(
                id="item-a",
                parent_id=PLAN_ROOT_ITEM_ID,
                order_key="1",
                title="A",
                outcome="A.",
                kind="work",
                scope=Scope(includes=["a"]),
            ),
        },
    )
    unit = derive_sub_tdp_units(plan)[0]
    with pytest.raises(ValueError, match="package_id"):
        build_unit_plan_snapshot(plan, unit, package_id="")


def test_inherited_approval_requires_package_attestation() -> None:
    plan = Plan(id="plan", revision=0, output_goal="Ship.", items={})
    with pytest.raises(ValueError, match="inherited_plan_approval"):
        inherited_whole_plan_approval(
            run_id="run-x",
            plan=plan,
            package_manifest={"planning_run": {"run_id": "run-plan"}},
            run_digests={},
        )


def test_loader_rejects_list_form_input_refs(tmp_path: Path) -> None:
    from top_down_planning.package.builder import ExecutionPackageBuilder
    from tests.helpers import whole_plan_approval_record

    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T003003-003003"
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Ship.",
        input_refs=[],
        items={
            PLAN_ROOT_ITEM_ID: PlanItem(
                id=PLAN_ROOT_ITEM_ID,
                parent_id=None,
                order_key="0",
                title="Root",
                outcome="Root.",
                kind="aggregate",
            ),
            "item-a": PlanItem(
                id="item-a",
                parent_id=PLAN_ROOT_ITEM_ID,
                order_key="1",
                title="A",
                outcome="A.",
                kind="work",
                scope=Scope(includes=["a"]),
            ),
        },
    )
    kwargs = create_run_kwargs(tmp_path)
    store.create_run(run_id, plan=plan, phase="plan_validated", **kwargs)
    store.save_review(run_id, whole_plan_approval_record(store, run_id))
    output_dir = tmp_path / "pkg"
    ExecutionPackageBuilder().build_from_planning_run(store, run_id, output_dir=output_dir)

    import json

    manifest_path = output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["context"]["input_refs"] = [{"path": "docs/x.md", "digest": "abc"}]
    # Invalidate package digest so we hit structure validation first by patching
    # via loader path: rewrite and recompute is hard; instead call verify directly.
    package = ExecutionPackageLoader().load(output_dir, verify_workspace=False)
    # Mutate loaded manifest view is frozen via object — write file and load again
    # after fixing digest check: inject list shape then expect loader to fail before digest.
    # Rebuild package_digest by loading with a custom check — simplest: patch context
    # then recompute digest in test using builder helpers.
    from top_down_planning.package.digests import compute_package_digest, digest_plan_file

    parent_digest = digest_plan_file(output_dir / "parent" / "plan.json")
    unit_digests = [
        digest_plan_file(output_dir / unit["plan_file"])
        for unit in manifest["units"]
    ]
    context_digests = {
        key: str(value)
        for key, value in manifest["context"].items()
        if key.endswith("_digest") and value
    }
    manifest["package_digest"] = compute_package_digest(
        manifest,
        parent_plan_digest=parent_digest,
        unit_plan_digests=unit_digests,
        approved_plan_digest=str(
            (manifest.get("planning_run") or {}).get("approved_plan_digest") or ""
        ),
        context_digests=context_digests,
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ExecutionPackageError, match="input_refs"):
        ExecutionPackageLoader().load(output_dir, verify_workspace=False)


def test_lineage_attach_always_requires_completed_accepted() -> None:
    """Paused attach path is removed — parameter must not reopen it."""

    import inspect

    sig = inspect.signature(ExecutionLineageValidator.validate_attach)
    assert "require_completed_accepted" not in sig.parameters


def test_verify_requires_embedded_resolved_config(tmp_path: Path) -> None:
    from top_down_planning.package.loader import LoadedExecutionPackage

    bare = LoadedExecutionPackage(
        manifest_path=tmp_path / "manifest.json",
        manifest={"context": {"input_refs": {"aggregate_digest": "", "refs": []}}},
        parent_plan=Plan(id="p", revision=0, output_goal="g", items={}),
        units={},
        workspace_path=tmp_path,
        resolved_config={},  # type ignored — force missing via empty then clear
    )
    # Bypass frozen dataclass: construct via object.__new__ path using replace isn't available
    # for required field; instead omit by monkeypatching attribute after construct isn't possible.
    # Use a simple Namespace-like stand-in through verify's attribute access:
    class _Bare:
        workspace_path = tmp_path
        manifest = {"context": {"input_refs": {"aggregate_digest": "x", "refs": []}}}
        resolved_config = None

    with pytest.raises(ExecutionPackageError, match="execution config"):
        verify_package_authoritative_inputs(_Bare())  # type: ignore[arg-type]
