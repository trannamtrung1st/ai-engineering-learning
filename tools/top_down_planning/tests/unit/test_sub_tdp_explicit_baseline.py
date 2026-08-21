"""Explicit --baseline for direct Sub-TDP execution (code-review P0#3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.cli.execute import parse_baseline_run_ids
from top_down_planning.config import resolve_config
from top_down_planning.domain.models import Plan
from top_down_planning.domain.plan_tree import PLAN_ROOT_ITEM_ID
from top_down_planning.orchestrator.prepared_unit_executor import PreparedUnitExecutor
from top_down_planning.package.builder import ExecutionPackageBuilder
from top_down_planning.package.loader import ExecutionPackageError, ExecutionPackageLoader
from top_down_planning.persistence import FileRunStore
from tests.helpers import accept_child_run, create_run_kwargs, whole_plan_approval_record
from tests.helpers import write_config
from tests.support.run_builders import _item


def _mixed_graph_plan(run_id: str) -> Plan:
    """A → B plus independent C."""

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
            "item-c": _item("item-c", parent_id=PLAN_ROOT_ITEM_ID, order_key="3", title="C"),
        },
    )


def _build_mixed_package(tmp_path: Path):
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
    run_id = "run-20260101T007001-007001"
    plan = _mixed_graph_plan(run_id)
    kwargs = create_run_kwargs(workspace, resolved_config=config)
    store.create_run(run_id, plan=plan, phase="plan_validated", **kwargs)
    store.save_review(run_id, whole_plan_approval_record(store, run_id))
    output_dir = tmp_path / "pkg"
    ExecutionPackageBuilder().build_from_planning_run(
        store, run_id, output_dir=output_dir
    )
    package = ExecutionPackageLoader().load(output_dir, verify_workspace=False)
    return store, package


def test_parse_baseline_run_ids_rejects_duplicates() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        parse_baseline_run_ids(
            ["run-20260101T000001-000001", "run-20260101T000001-000001"]
        )


def test_direct_b_with_upstream_a_rejects_without_baseline_for_independent_c(
    tmp_path: Path,
) -> None:
    """Mixed graph: C changed a resource; B with only --upstream A must fail closed."""

    store, package = _build_mixed_package(tmp_path)
    config = package.resolved_config
    shared = tmp_path / "shared" / "state.json"
    executor = PreparedUnitExecutor()

    child_a = executor.create_or_load_child_run(
        store, package, "item-a", resolved_config=config, invocation={"command": "execute"}
    )
    accept_child_run(store, child_a)

    child_c = executor.create_or_load_child_run(
        store, package, "item-c", resolved_config=config, invocation={"command": "execute"}
    )
    shared.write_text('{"version": "from-c"}\n', encoding="utf-8")
    accept_child_run(
        store,
        child_c,
        outputs=[{"id": "out-c", "type": "artifact", "ref": "shared/state.json"}],
        contributions=[
            {
                "item_id": "item-c",
                "output_refs": ["out-c"],
                "summary": "C updated shared state",
            }
        ],
    )

    with pytest.raises(ExecutionPackageError, match="not authorized|do not match"):
        executor.create_or_load_child_run(
            store,
            package,
            "item-b",
            resolved_config=config,
            invocation={"command": "execute"},
            explicit_upstream={"item-a": child_a},
            explicit_upstream_only=True,
        )


def test_direct_b_accepts_independent_c_via_explicit_baseline(
    tmp_path: Path,
) -> None:
    """--baseline supplies workspace lineage without making C a semantic dependency."""

    store, package = _build_mixed_package(tmp_path)
    config = package.resolved_config
    shared = tmp_path / "shared" / "state.json"
    executor = PreparedUnitExecutor()

    child_a = executor.create_or_load_child_run(
        store, package, "item-a", resolved_config=config, invocation={"command": "execute"}
    )
    accept_child_run(store, child_a)

    child_c = executor.create_or_load_child_run(
        store, package, "item-c", resolved_config=config, invocation={"command": "execute"}
    )
    shared.write_text('{"version": "from-c"}\n', encoding="utf-8")
    accept_child_run(
        store,
        child_c,
        outputs=[{"id": "out-c", "type": "artifact", "ref": "shared/state.json"}],
        contributions=[
            {
                "item_id": "item-c",
                "output_refs": ["out-c"],
                "summary": "C updated shared state",
            }
        ],
    )

    child_b = executor.create_or_load_child_run(
        store,
        package,
        "item-b",
        resolved_config=config,
        invocation={"command": "execute"},
        explicit_upstream={"item-a": child_a},
        explicit_upstream_only=True,
        explicit_baseline_run_ids=[child_c],
    )
    assert child_b
    binding = store.load_run(child_b).get("package_binding") or {}
    baseline = binding.get("workspace_baseline_accepted_results") or []
    baseline_child_ids = {
        str((wrapper.get("accepted_result") or {}).get("child_run_id") or "")
        for wrapper in baseline
        if isinstance(wrapper, dict)
    }
    assert child_c in baseline_child_ids
    upstream = binding.get("upstream_accepted_results") or []
    upstream_child_ids = {
        str((wrapper.get("accepted_result") or {}).get("child_run_id") or "")
        for wrapper in upstream
        if isinstance(wrapper, dict)
    }
    assert child_a in upstream_child_ids
    assert child_c not in upstream_child_ids
