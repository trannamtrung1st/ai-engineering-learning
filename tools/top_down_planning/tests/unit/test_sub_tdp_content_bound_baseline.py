"""Content-bound workspace baseline authorization (code-review P0#1–#2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.config import resolve_config
from top_down_planning.domain.models import Plan
from top_down_planning.domain.plan_tree import PLAN_ROOT_ITEM_ID
from top_down_planning.orchestrator.prepared_unit_executor import PreparedUnitExecutor
from top_down_planning.package.builder import ExecutionPackageBuilder
from top_down_planning.package.execution_validation import (
    verify_package_context_snapshot_with_baseline,
)
from top_down_planning.package.lineage import (
    accepted_result_record,
    upstream_accepted_result_binding,
)
from top_down_planning.package.loader import ExecutionPackageError, ExecutionPackageLoader
from top_down_planning.persistence import FileRunStore
from tests.helpers import accept_child_run, create_run_kwargs, whole_plan_approval_record
from tests.unit.test_production_auth_alignment import write_config
from tests.unit.test_sub_tdp_defect_pass import _item


def _plan_with_shared_resource(run_id: str, *, dependent: bool = True) -> Plan:
    items = {
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
            depends_on=["item-a"] if dependent else [],
        ),
    }
    return Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Ship.",
        input_refs=[],
        items=items,
    )


def _build_package(tmp_path: Path, *, dependent: bool = True):
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
    run_id = "run-20260101T006001-006001"
    plan = _plan_with_shared_resource(run_id, dependent=dependent)
    kwargs = create_run_kwargs(workspace, resolved_config=config)
    store.create_run(run_id, plan=plan, phase="plan_validated", **kwargs)
    store.save_review(run_id, whole_plan_approval_record(store, run_id))
    output_dir = tmp_path / "pkg"
    ExecutionPackageBuilder().build_from_planning_run(
        store, run_id, output_dir=output_dir
    )
    package = ExecutionPackageLoader().load(output_dir, verify_workspace=False)
    return store, package


def _accepted_wrapper_for_shared(
    store: FileRunStore,
    package,
    child_id: str,
    *,
    unit_id: str,
):
    accepted = accepted_result_record(
        child_run=store.load_run(child_id),
        child_production=store.load_production(child_id),
        unit_id=unit_id,
        unit_plan_digest=package.units[unit_id].plan_digest,
        package_id=str(package.manifest.get("package_id") or ""),
        package_digest=str(package.manifest.get("package_digest") or ""),
        assigned_subtree_digest=package.units[unit_id].assigned_subtree_digest,
    )
    return upstream_accepted_result_binding(
        accepted,
        upstream_contract_digest=package.units[unit_id].assigned_subtree_digest,
    ), accepted


def _create_and_accept_shared_writer(
    store: FileRunStore,
    package,
    *,
    unit_id: str,
    content: str,
) -> str:
    """Create child against package snapshot, then write+accept content-bound output."""

    config = package.resolved_config
    shared = Path(package.workspace_path) / "shared" / "state.json"
    child_id = PreparedUnitExecutor().create_or_load_child_run(
        store,
        package,
        unit_id,
        resolved_config=config,
        invocation={"command": "execute"},
    )
    shared.write_text(content, encoding="utf-8")
    accept_child_run(
        store,
        child_id,
        outputs=[{"id": f"out-{unit_id}", "type": "artifact", "ref": "shared/state.json"}],
        contributions=[
            {
                "item_id": unit_id,
                "output_refs": [f"out-{unit_id}"],
                "summary": f"{unit_id} updated shared state",
            }
        ],
    )
    return child_id


def test_accepted_result_binds_workspace_changes_with_sha256(tmp_path: Path) -> None:
    """Accepted results must bind exact output bytes, not only paths."""

    store, package = _build_package(tmp_path)
    child_id = _create_and_accept_shared_writer(
        store, package, unit_id="item-a", content='{"version": 2}\n'
    )
    _, accepted = _accepted_wrapper_for_shared(
        store, package, child_id, unit_id="item-a"
    )

    changes = accepted.get("workspace_changes")
    assert isinstance(changes, dict)
    assert "shared/state.json" in changes
    entry = changes["shared/state.json"]
    assert entry["operation"] == "write"
    assert entry["sha256"]
    assert entry["size"] > 0
    assert entry.get("snapshot_ref")


def test_baseline_auth_rejects_when_workspace_bytes_differ_from_accepted(
    tmp_path: Path,
) -> None:
    """Path presence is not enough — current bytes must match accepted sha256."""

    store, package = _build_package(tmp_path)
    child_id = _create_and_accept_shared_writer(
        store, package, unit_id="item-a", content='{"version": 2}\n'
    )
    wrapper, _accepted = _accepted_wrapper_for_shared(
        store, package, child_id, unit_id="item-a"
    )

    # External drift after acceptance: same path, different bytes.
    shared = Path(package.workspace_path) / "shared" / "state.json"
    shared.write_text('{"version": "tampered"}\n', encoding="utf-8")

    with pytest.raises(ExecutionPackageError, match="do not match accepted sha256"):
        verify_package_context_snapshot_with_baseline(
            package,
            store=store,
            baseline_wrappers=[wrapper],
        )


def test_authorized_paths_require_workspace_changes_not_output_refs(
    tmp_path: Path,
) -> None:
    """Hard cutover: output_refs alone cannot authorize paths."""

    from top_down_planning.package.execution_validation import (
        authorized_paths_from_accepted_result,
    )

    accepted = {
        "output_refs": [{"id": "out-a", "type": "artifact", "ref": "shared/state.json"}],
        "contributions": [],
        "completion_assessment": "done",
    }
    with pytest.raises(ExecutionPackageError, match="workspace_changes"):
        authorized_paths_from_accepted_result(accepted, workspace=tmp_path)


def test_baseline_auth_accepts_when_workspace_bytes_match_accepted(
    tmp_path: Path,
) -> None:
    """Matching accepted sha256 authorizes resource drift from the package snapshot."""

    store, package = _build_package(tmp_path)
    child_id = _create_and_accept_shared_writer(
        store, package, unit_id="item-a", content='{"version": 2}\n'
    )
    wrapper, _accepted = _accepted_wrapper_for_shared(
        store, package, child_id, unit_id="item-a"
    )

    binding = verify_package_context_snapshot_with_baseline(
        package,
        store=store,
        baseline_wrappers=[wrapper],
    )
    assert isinstance(binding, dict)
    assert "shared/state.json" in (binding.get("resource_digests") or {})


def test_baseline_rejects_conflicting_accepted_hashes_for_same_path(
    tmp_path: Path,
) -> None:
    """Two accepted writers of the same path with different digests are not composable."""

    from top_down_planning.orchestrator.prepared_run_factory import PreparedRunFactory

    store, package = _build_package(tmp_path, dependent=False)
    config = package.resolved_config
    factory = PreparedRunFactory()
    shared = Path(package.workspace_path) / "shared" / "state.json"

    child_a = factory.create_child_run(
        store,
        package,
        package.units["item-a"],
        resolved_config=config,
        invocation={"command": "execute"},
    )
    shared.write_text('{"writer": "a"}\n', encoding="utf-8")
    accept_child_run(
        store,
        child_a,
        outputs=[{"id": "out-a", "type": "artifact", "ref": "shared/state.json"}],
        contributions=[
            {
                "item_id": "item-a",
                "output_refs": ["out-a"],
                "summary": "A wrote state",
            }
        ],
    )

    shared.write_text('{"version": 1}\n', encoding="utf-8")
    child_b = factory.create_child_run(
        store,
        package,
        package.units["item-b"],
        resolved_config=config,
        invocation={"command": "execute"},
    )
    shared.write_text('{"writer": "b"}\n', encoding="utf-8")
    accept_child_run(
        store,
        child_b,
        outputs=[{"id": "out-b", "type": "artifact", "ref": "shared/state.json"}],
        contributions=[
            {
                "item_id": "item-b",
                "output_refs": ["out-b"],
                "summary": "B wrote state",
            }
        ],
    )

    wrapper_a, _ = _accepted_wrapper_for_shared(
        store, package, child_a, unit_id="item-a"
    )
    wrapper_b, _ = _accepted_wrapper_for_shared(
        store, package, child_b, unit_id="item-b"
    )

    with pytest.raises(ExecutionPackageError, match="conflicting"):
        verify_package_context_snapshot_with_baseline(
            package,
            store=store,
            baseline_wrappers=[wrapper_a, wrapper_b],
        )
