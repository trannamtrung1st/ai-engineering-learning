"""Run, package, and planning-state builders shared by unit tests."""

from __future__ import annotations

import shutil
from pathlib import Path

from top_down_planning.domain.models import Plan, PlanItem, Scope
from top_down_planning.domain.plan_tree import PLAN_ROOT_ITEM_ID
from core_tools.persistence import atomic_write_json
from top_down_planning.orchestrator.phases import OUTPUT_VALIDATED, PLANNING, PRODUCTION, SUB_TDPS
from top_down_planning.orchestrator.prepared_run_factory import PreparedRunFactory
from top_down_planning.package.builder import ExecutionPackageBuilder
from top_down_planning.package.loader import ExecutionPackageLoader
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs, minimal_resolved_config, whole_plan_approval_record


def _wipe_txn_dirs(run_dir: Path) -> None:
    for child in list(run_dir.iterdir()):
        if child.name.startswith("."):
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()


def _create_planning_run(store: FileRunStore, run_id: str) -> str:
    store.create_run(
        run_id,
        plan=Plan(
            id="plan-slice7",
            revision=0,
            output_goal="Goal.",
            items={
                "item-root": PlanItem(
                    id="item-root",
                    parent_id=None,
                    order_key="0000000000",
                    title="Root",
                    kind="aggregate",
                )
            },
        ),
        phase=PLANNING,
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
    )
    return run_id


def _pause_run(store: FileRunStore, run_id: str) -> None:
    run = store.load_run(run_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["status"] = "paused"
    run["stop"] = {
        "code": "limit_exhausted",
        "category": "operational",
        "phase": PLANNING,
        "message": "paused for tests",
        "role": None,
        "details": {},
    }
    store.save_run(run_id, run, expected)


def _approved_parent_plan(run_id: str) -> Plan:
    root = PlanItem(
        id=PLAN_ROOT_ITEM_ID,
        parent_id=None,
        order_key="0000000000",
        title="Deliver",
        outcome="Deliver the output.",
        kind="aggregate",
    )
    foundation = PlanItem(
        id="item-foundation",
        parent_id=PLAN_ROOT_ITEM_ID,
        order_key="0000000000",
        title="Foundation",
        outcome="Persist state reliably.",
        kind="work",
        scope=Scope(includes=["storage"]),
    )
    storage = PlanItem(
        id="item-storage",
        parent_id="item-foundation",
        order_key="0000000001",
        title="Storage layer",
        outcome="Implement storage.",
        kind="work",
        scope=Scope(includes=["db"]),
    )
    return Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Ship the product.",
        input_refs=["docs/spec.md"],
        items={
            PLAN_ROOT_ITEM_ID: root,
            "item-foundation": foundation,
            "item-storage": storage,
        },
    )


def _planning_run_at_validated(store: FileRunStore, workspace: Path, run_id: str) -> None:
    from top_down_planning.domain.run_kind import RUN_KIND_PLANNING

    config = create_run_kwargs(workspace)["resolved_config"]
    kwargs = create_run_kwargs(workspace, resolved_config=config)
    store.create_run(
        run_id,
        plan=_approved_parent_plan(run_id),
        phase="plan_validated",
        run_extras={"run_kind": RUN_KIND_PLANNING},
        **kwargs,
    )
    store.save_review(run_id, whole_plan_approval_record(store, run_id))


def _built_package(tmp_path: Path) -> tuple[FileRunStore, str, ExecutionPackageLoader]:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T000901-000901"
    _planning_run_at_validated(store, tmp_path, run_id)
    built = ExecutionPackageBuilder().build_from_planning_run(
        store,
        run_id,
        output_dir=tmp_path / "execution",
    )
    loaded = ExecutionPackageLoader().load(built.manifest_path.parent, verify_workspace=False)
    return store, run_id, loaded


def _parent_with_orchestration(tmp_path: Path):
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
    run["phase"] = SUB_TDPS
    run["status"] = "paused"
    run["stop"] = {
        "code": "sub_tdps_awaiting_children",
        "category": "operational",
        "phase": SUB_TDPS,
        "message": "waiting for children",
        "role": None,
        "details": {},
    }
    store.save_run(parent_id, run, expected)

    from top_down_planning.domain.sub_tdp_units import SubTdpUnit
    from top_down_planning.persistence.sub_tdp_state import (
        initial_sub_tdp_state_from_package,
        merge_sub_tdp_state_into_production,
    )

    units = [
        SubTdpUnit(
            plan_item_id=unit.unit_id,
            title=unit.title,
            outcome="",
            directory=unit.plan_file.parent.name,
            ordinal=unit.ordinal,
        )
        for unit in sorted(package.units.values(), key=lambda item: item.ordinal)
    ]
    production = store.load_production(parent_id)
    parent_binding = store.load_run(parent_id).get("package_binding") or {}
    state = initial_sub_tdp_state_from_package(
        package.manifest,
        manifest_path=str(parent_binding.get("manifest_path") or package.manifest_path),
        units=units,
        package_units=package.units,
    )
    merged = merge_sub_tdp_state_into_production(production, state)
    expected_revision = int(production["revision"])
    merged["revision"] = expected_revision + 1
    store.save_production(parent_id, merged, expected_revision)
    return store, parent_id, package, config


def _sample_plan() -> Plan:
    return Plan(
        id="plan-run-test",
        revision=0,
        output_goal="Goal.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="Root",
                kind="aggregate",
            )
        },
    )


def _create_paused_production_run(store: FileRunStore) -> str:
    run_id = "run-20260101T002201-002201"
    config = minimal_resolved_config()
    store.create_run(
        run_id,
        plan=_sample_plan(),
        phase=PRODUCTION,
        **create_run_kwargs(store.root, resolved_config=config),
    )
    store.save_review(run_id, whole_plan_approval_record(store, run_id))
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["status"] = "paused"
    run["stop"] = {
        "code": "limit_exhausted",
        "category": "operational",
        "phase": PRODUCTION,
        "message": "limit reached",
        "details": {
            "limit": "limits.production.max_batches",
            "consumed": 1,
            "configured": 1,
        },
    }
    store.save_run(run_id, run, expected_revision)
    return run_id


def _item(item_id: str, *, parent_id: str | None, order_key: str, title: str, **kwargs):
    return PlanItem(
        id=item_id,
        parent_id=parent_id,
        order_key=order_key,
        title=title,
        outcome=f"{title} outcome.",
        kind=kwargs.get("kind", "work"),
        depends_on=list(kwargs.get("depends_on") or []),
        scope=Scope(includes=[title.lower()]),
    )


def _dependent_plan(run_id: str) -> Plan:
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


def _build_package(tmp_path: Path) -> tuple[FileRunStore, Path, Plan]:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T004001-004001"
    plan = _dependent_plan(run_id)
    from top_down_planning.domain.run_kind import RUN_KIND_PLANNING

    kwargs = create_run_kwargs(tmp_path)
    store.create_run(
        run_id,
        plan=plan,
        phase="plan_validated",
        run_extras={"run_kind": RUN_KIND_PLANNING},
        **kwargs,
    )
    store.save_review(run_id, whole_plan_approval_record(store, run_id))
    output_dir = tmp_path / "pkg"
    ExecutionPackageBuilder().build_from_planning_run(store, run_id, output_dir=output_dir)
    return store, output_dir, plan


def _force_run_fields(store: FileRunStore, run_id: str, **fields) -> None:
    run = store.load_run(run_id)
    run = dict(run)
    run.update(fields)
    if (
        str(run.get("outcome") or "") == "accepted"
        and str(run.get("phase") or "") == OUTPUT_VALIDATED
    ):
        binding = dict(run.get("package_binding") or {})
        if not str(binding.get("whole_output_review_id") or "").strip():
            binding["whole_output_review_id"] = "review-whole-output-1"
            binding["whole_output_review_digest"] = "r" * 64
            run["package_binding"] = binding
    atomic_write_json(store.run_dir(run_id) / "run.json", run)
