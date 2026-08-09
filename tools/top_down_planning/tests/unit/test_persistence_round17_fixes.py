"""Regression tests for Slice 3 round-17 review (TDP-PERSIST-065..068)."""

from __future__ import annotations

from pathlib import Path

import pytest

from core_tools.persistence import PersistenceError
from top_down_planning.config import recompute_context_snapshot_binding, resolve_config
from top_down_planning.config.context_digests import sync_run_production_digests
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.production import live_output_evidence_entries
from top_down_planning.orchestrator.phases import PRODUCTION
from top_down_planning.orchestrator.prepare_resume import _verify_production_evidence
from top_down_planning.package.lineage import validate_accepted_child_delivery
from top_down_planning.persistence import FileRunStore
from tests.helpers import (
    apply_production,
    bind_evidence_snapshot,
    create_run_kwargs,
    goal_met_completion_claim,
    mirrored_production_batch,
    whole_plan_approval_record,
    write_config,
)
from tests.unit.test_persistence_round12_fixes import (
    _create_resource_run,
    _new_run_id as _resource_run_id,
)


def _new_run_id(suffix: str) -> str:
    return f"run-20260101T0063{suffix}-0063{suffix}"


def _resource_workspace(tmp_path: Path) -> tuple[FileRunStore, str, Path]:
    workspace = tmp_path / "ws"
    src = workspace / "src"
    src.mkdir(parents=True)
    feature = src / "feature.py"
    feature.write_text("v1\n", encoding="utf-8")
    store = FileRunStore(tmp_path / "runs")
    run_id = _resource_run_id("01")
    _create_resource_run(store, run_id, workspace)
    store.save_review(run_id, whole_plan_approval_record(store, run_id))
    return store, run_id, workspace


def _produce_feature_v2(store: FileRunStore, run_id: str) -> dict:
    run = store.load_run(run_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["phase"] = PRODUCTION
    run["status"] = "running"
    run["outcome"] = None
    store.save_run(run_id, run, expected)
    apply_production(
        store,
        run_id,
        {
            "production_revision": int(store.load_production(run_id)["revision"]),
            "plan_items": ["item-work"],
            "dispositions": {
                "item-work": {"disposition": "completed", "evidence": "feature v2"},
            },
            "outputs": [{"id": "out-1", "type": "artifact", "ref": "src/feature.py"}],
            "contributions": [
                {"item_id": "item-work", "output_refs": ["out-1"], "summary": "batch"},
            ],
            "summary": "production batch",
        },
        handler="apply",
        phase=PRODUCTION,
    )()
    return store.load_production(run_id)


def _snapshot_path(store: FileRunStore, run_id: str, evidence: dict) -> Path:
    snapshot_ref = str(evidence.get("snapshot_ref") or "")
    parts = Path(snapshot_ref).parts
    return store.artifact_path(run_id, parts[1], parts[2])


def _save_context_rebase(store: FileRunStore, run_id: str, workspace: Path) -> None:
    config = resolve_config(
        write_config(
            workspace.parent / "cfg.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  roles:
    producer:
      resources:
        - src/
""",
        ),
        cwd=workspace,
    )
    new_binding, new_digest = recompute_context_snapshot_binding(config, workspace=workspace)
    run = store.load_run(run_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    digests = dict(run.get("digests") or {})
    digests["context_snapshot"] = new_digest
    run["digests"] = digests
    run["context_snapshot_binding"] = new_binding
    store.save_run(run_id, run, expected)


def test_run_only_context_rebase_rejects_missing_evidence_snapshot(tmp_path: Path) -> None:
    store, run_id, workspace = _resource_workspace(tmp_path)
    production = _produce_feature_v2(store, run_id)
    evidence = live_output_evidence_entries(production)[0]
    snapshot_path = _snapshot_path(store, run_id, evidence)
    snapshot_path.unlink()
    before = (store.run_dir(run_id) / "run.json").read_bytes()
    (workspace / "src" / "feature.py").write_text("v2\n", encoding="utf-8")

    with pytest.raises(PersistenceError, match="evidence snapshot missing"):
        _save_context_rebase(store, run_id, workspace)

    assert (store.run_dir(run_id) / "run.json").read_bytes() == before


def test_run_only_context_rebase_rejects_corrupt_evidence_snapshot(tmp_path: Path) -> None:
    store, run_id, workspace = _resource_workspace(tmp_path)
    production = _produce_feature_v2(store, run_id)
    evidence = live_output_evidence_entries(production)[0]
    snapshot_path = _snapshot_path(store, run_id, evidence)
    snapshot_path.write_bytes(b"corrupted")
    before = (store.run_dir(run_id) / "run.json").read_bytes()
    (workspace / "src" / "feature.py").write_text("v2\n", encoding="utf-8")

    with pytest.raises(PersistenceError, match="hash mismatch"):
        _save_context_rebase(store, run_id, workspace)

    assert (store.run_dir(run_id) / "run.json").read_bytes() == before


def test_run_only_context_rebase_succeeds_with_intact_evidence_snapshot(tmp_path: Path) -> None:
    store, run_id, workspace = _resource_workspace(tmp_path)
    pre_snapshot = store.load_run(run_id)["digests"]["context_snapshot"]
    (workspace / "src" / "feature.py").write_text("v2\n", encoding="utf-8")
    _produce_feature_v2(store, run_id)
    assert sync_run_production_digests(store, run_id) is True
    post_snapshot = store.load_run(run_id)["digests"]["context_snapshot"]
    assert post_snapshot != pre_snapshot


def test_create_run_rejects_live_output_evidence(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("01")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Goal.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0",
                title="Root",
                kind="aggregate",
            ),
            "item-work": PlanItem(
                id="item-work",
                parent_id="item-root",
                order_key="1",
                title="Work",
                kind="work",
            ),
        },
    )
    kwargs = create_run_kwargs(workspace)
    batch, evidence = mirrored_production_batch(item_id="item-work")
    production = {
        "revision": 0,
        "output_revision": 0,
        "batches": [batch],
        "output_evidence": [evidence],
        "dispositions": {"item-work": "completed"},
        "amendment_requests": [],
    }
    with pytest.raises(PersistenceError, match="live output evidence"):
        store.create_run(run_id, plan=plan, production=production, **kwargs)


def test_plan_only_revision_bump_rejects_stale_completion_claim(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("02")
    workspace = tmp_path
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Goal.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0",
                title="Root",
                kind="aggregate",
            ),
            "item-work": PlanItem(
                id="item-work",
                parent_id="item-root",
                order_key="1",
                title="Work",
                kind="work",
            ),
        },
    )
    kwargs = create_run_kwargs(workspace)
    store.create_run(run_id, plan=plan, **kwargs)
    batch, evidence = mirrored_production_batch(
        store=store,
        run_id=run_id,
        item_id="item-work",
    )
    production = dict(store.load_production(run_id))
    production["batches"] = [batch]
    production["output_evidence"] = [evidence]
    production["dispositions"] = {"item-work": "completed"}
    production["output_revision"] = 1
    production["completion_claim"] = goal_met_completion_claim(
        production,
        plan_revision=0,
    )
    expected_prod = int(production["revision"])
    production["revision"] = expected_prod + 1
    store.save_production(run_id, production, expected_prod)

    next_plan = store.load_plan_model(run_id)
    next_plan = Plan(
        id=next_plan.id,
        revision=next_plan.revision + 1,
        output_goal=next_plan.output_goal,
        items={
            **next_plan.items,
            "item-work": PlanItem(
                id="item-work",
                parent_id="item-root",
                order_key="1",
                title="Work revised",
                outcome=next_plan.items["item-work"].outcome,
                kind="work",
            ),
        },
    )
    before_plan = (store.run_dir(run_id) / "plan.json").read_bytes()
    before_production = (store.run_dir(run_id) / "production.json").read_bytes()

    with pytest.raises(PersistenceError, match="plan_revision"):
        store.save_plan_model(run_id, next_plan, 0)

    assert (store.run_dir(run_id) / "plan.json").read_bytes() == before_plan
    assert (store.run_dir(run_id) / "production.json").read_bytes() == before_production


def test_atomic_plan_and_production_commit_validates_claim_against_prospective_plan(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("03")
    workspace = tmp_path
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Goal.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0",
                title="Root",
                kind="aggregate",
            ),
            "item-work": PlanItem(
                id="item-work",
                parent_id="item-root",
                order_key="1",
                title="Work",
                kind="work",
            ),
        },
    )
    kwargs = create_run_kwargs(workspace)
    store.create_run(run_id, plan=plan, **kwargs)
    batch, evidence = mirrored_production_batch(
        store=store,
        run_id=run_id,
        item_id="item-work",
    )
    production = dict(store.load_production(run_id))
    production["batches"] = [batch]
    production["output_evidence"] = [evidence]
    production["dispositions"] = {"item-work": "completed"}
    production["output_revision"] = 1
    production["completion_claim"] = {
        "goal_met": False,
        "status": "integration_pending",
        "goal_assessment": "cleared for plan revision",
    }
    expected_prod = int(production["revision"])
    production["revision"] = expected_prod + 1

    next_plan = store.load_plan_model(run_id)
    next_plan = Plan(
        id=next_plan.id,
        revision=next_plan.revision + 1,
        output_goal=next_plan.output_goal,
        items={
            **next_plan.items,
            "item-work": PlanItem(
                id="item-work",
                parent_id="item-root",
                order_key="1",
                title="Work revised",
                outcome=next_plan.items["item-work"].outcome,
                kind="work",
            ),
        },
    )

    from top_down_planning.persistence.commit import CommitSpec

    store.commit(
        run_id,
        CommitSpec(
            plan=next_plan.to_dict(),
            plan_expected_revision=0,
            production=production,
            production_expected_revision=expected_prod,
        ),
    )
    assert store.load_plan(run_id)["revision"] == 1
    assert store.load_production(run_id)["completion_claim"]["goal_met"] is False


def test_accepted_result_rejects_numeric_child_run_id(tmp_path: Path) -> None:
    from tests.helpers import decorate_sub_tdp_v2_package
    from top_down_planning.domain.sub_tdp_units import SubTdpUnit
    from top_down_planning.persistence.sub_tdp_state import initial_sub_tdp_state

    store = FileRunStore(tmp_path)
    run_id = _new_run_id("04")
    workspace = tmp_path
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Goal.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0",
                title="Root",
                kind="aggregate",
            ),
            "item-work": PlanItem(
                id="item-work",
                parent_id="item-root",
                order_key="1",
                title="Work",
                kind="work",
            ),
        },
    )
    kwargs = create_run_kwargs(workspace)
    store.create_run(run_id, plan=plan, **kwargs)
    state = decorate_sub_tdp_v2_package(
        initial_sub_tdp_state(
            [
                SubTdpUnit(
                    plan_item_id="item-work",
                    title="Work",
                    outcome="Work.",
                    directory="01-work",
                    ordinal=1,
                )
            ]
        )
    )
    unit = state["units"][0]
    unit["status"] = "completed"
    unit["child_run_id"] = "run-child"
    unit["accepted_result_digest"] = "a" * 64
    unit["accepted_result"] = {
        "schema_version": 1,
        "package_id": "pkg",
        "package_digest": "b" * 64,
        "unit_id": "item-work",
        "unit_plan_digest": "c" * 64,
        "assigned_subtree_digest": "d" * 64,
        "child_run_id": 123,
        "output_revision": 1,
        "output_digest": "e" * 64,
        "whole_output_review_id": "review-1",
        "whole_output_review_digest": "f" * 64,
        "outcome": "accepted",
        "evidence_digest": "0" * 64,
        "output_refs": [],
        "contributions": [],
        "workspace_changes": {},
        "baseline_context_snapshot_digest": "1" * 64,
        "baseline_accepted_result_digests": [],
        "final_context_snapshot_digest": "2" * 64,
        "completion_assessment": "done",
    }
    production = dict(store.load_production(run_id))
    production["sub_tdps"] = state
    with pytest.raises(PersistenceError, match="child_run_id"):
        expected = int(production["revision"])
        production["revision"] = expected + 1
        store.save_production(run_id, production, expected)


def test_accepted_result_rejects_output_ref_missing_snapshot_ref(tmp_path: Path) -> None:
    from tests.helpers import decorate_sub_tdp_v2_package
    from top_down_planning.domain.sub_tdp_units import SubTdpUnit
    from top_down_planning.persistence.sub_tdp_state import initial_sub_tdp_state

    store = FileRunStore(tmp_path)
    run_id = _new_run_id("05")
    workspace = tmp_path
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Goal.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0",
                title="Root",
                kind="aggregate",
            ),
            "item-work": PlanItem(
                id="item-work",
                parent_id="item-root",
                order_key="1",
                title="Work",
                kind="work",
            ),
        },
    )
    kwargs = create_run_kwargs(workspace)
    store.create_run(run_id, plan=plan, **kwargs)
    state = decorate_sub_tdp_v2_package(
        initial_sub_tdp_state(
            [
                SubTdpUnit(
                    plan_item_id="item-work",
                    title="Work",
                    outcome="Work.",
                    directory="01-work",
                    ordinal=1,
                )
            ]
        )
    )
    unit = state["units"][0]
    unit["status"] = "completed"
    unit["child_run_id"] = "run-child"
    unit["accepted_result_digest"] = "a" * 64
    unit["accepted_result"] = {
        "schema_version": 1,
        "package_id": "pkg",
        "package_digest": "b" * 64,
        "unit_id": "item-work",
        "unit_plan_digest": "c" * 64,
        "assigned_subtree_digest": "d" * 64,
        "child_run_id": "run-child",
        "output_revision": 1,
        "output_digest": "e" * 64,
        "whole_output_review_id": "review-1",
        "whole_output_review_digest": "f" * 64,
        "outcome": "accepted",
        "evidence_digest": "0" * 64,
        "output_refs": [
            {
                "id": "out-1",
                "type": "artifact",
                "ref": "out.txt",
                "sha256": "a" * 64,
                "size": 1,
                "media_type": "text/plain",
                "captured_at": "2026-01-01T00:00:00Z",
            }
        ],
        "contributions": [],
        "workspace_changes": {},
        "baseline_context_snapshot_digest": "1" * 64,
        "baseline_accepted_result_digests": [],
        "final_context_snapshot_digest": "2" * 64,
        "completion_assessment": "done",
    }
    production = dict(store.load_production(run_id))
    production["sub_tdps"] = state
    with pytest.raises(PersistenceError, match="snapshot_ref"):
        expected = int(production["revision"])
        production["revision"] = expected + 1
        store.save_production(run_id, production, expected)


def test_resume_ignores_invalidated_historical_evidence_snapshot(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("06")
    workspace = tmp_path
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Goal.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0",
                title="Root",
                kind="aggregate",
            ),
            "item-work": PlanItem(
                id="item-work",
                parent_id="item-root",
                order_key="1",
                title="Work",
                kind="work",
            ),
        },
    )
    kwargs = create_run_kwargs(workspace)
    store.create_run(run_id, plan=plan, **kwargs)
    production = dict(store.load_production(run_id))
    old_batch, old_evidence = mirrored_production_batch(
        batch_id="batch-old",
        evidence_id="out-old",
        store=store,
        run_id=run_id,
    )
    old_batch["evidence_status"] = "invalidated_by_reconciliation"
    old_batch["invalidated_item_ids"] = ["item-work"]
    live_batch, live_evidence = mirrored_production_batch(
        batch_id="batch-live",
        evidence_id="out-live",
        store=store,
        run_id=run_id,
    )
    production["batches"] = [old_batch, live_batch]
    production["output_evidence"] = [old_evidence, live_evidence]
    production["dispositions"] = {"item-work": "completed"}

    old_path = _snapshot_path(store, run_id, old_evidence)
    old_path.unlink()

    assert _verify_production_evidence(store, run_id, production) is None


def test_accepted_child_delivery_ignores_invalidated_historical_evidence(
    tmp_path: Path,
) -> None:
    from tests.helpers import accept_child_run

    store = FileRunStore(tmp_path)
    child_id = _new_run_id("07")
    workspace = tmp_path
    plan = Plan(
        id=f"plan-{child_id}",
        revision=0,
        output_goal="Goal.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0",
                title="Root",
                kind="aggregate",
            ),
            "item-a": PlanItem(
                id="item-a",
                parent_id="item-root",
                order_key="1",
                title="A",
                kind="work",
            ),
        },
    )
    kwargs = create_run_kwargs(workspace)
    store.create_run(child_id, plan=plan, **kwargs)
    store.save_review(child_id, whole_plan_approval_record(store, child_id))
    accept_child_run(store, child_id)

    production = dict(store.load_production(child_id))
    old_batch, old_evidence = mirrored_production_batch(
        batch_id="batch-old",
        evidence_id="out-old",
        item_id="item-a",
        store=store,
        run_id=child_id,
    )
    old_batch["evidence_status"] = "invalidated_by_reconciliation"
    old_batch["invalidated_item_ids"] = ["item-a"]
    production["batches"] = [old_batch, *production["batches"]]
    production["output_evidence"] = [old_evidence, *production["output_evidence"]]

    old_path = _snapshot_path(store, child_id, old_evidence)
    old_path.write_bytes(b"corrupt")

    validate_accepted_child_delivery(
        store=store,
        child_run_id=child_id,
        child_production=production,
        verify_evidence=True,
    )
