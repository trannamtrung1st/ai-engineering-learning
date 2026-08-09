"""Regression tests for Slice 3 round-19 review (TDP-PERSIST-071)."""

from __future__ import annotations

from pathlib import Path

import pytest

from core_tools.persistence import PersistenceError
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.sub_tdp_units import SubTdpUnit
from top_down_planning.package.lineage import (
    accepted_result_digest,
    accepted_result_record,
    verify_accepted_result_attestation,
    workspace_changes_from_output_evidence,
)
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.digests import compute_output_digest
from top_down_planning.persistence.sub_tdp_state import initial_sub_tdp_state
from tests.helpers import (
    complete_child_production,
    create_run_kwargs,
    decorate_sub_tdp_v2_package,
)


def _new_run_id(suffix: str) -> str:
    return f"run-20260101T0065{suffix}-0065{suffix}"


def _output_ref(
    *,
    output_id: str,
    ref: str,
    sha256: str,
    size: int,
    snapshot_ref: str,
) -> dict:
    return {
        "id": output_id,
        "type": "artifact",
        "ref": ref,
        "sha256": sha256,
        "size": size,
        "media_type": "text/plain",
        "captured_at": "2026-01-01T00:00:00Z",
        "snapshot_ref": snapshot_ref,
    }


def _canonical_accepted_result(
    output_refs: list[dict],
    *,
    ref: str | None = None,
) -> dict:
    primary_ref = ref or str(output_refs[-1].get("ref") or "src/a.py")
    latest = output_refs[-1]
    workspace_changes = workspace_changes_from_output_evidence(output_refs)
    return {
        "schema_version": 1,
        "package_id": "pkg",
        "package_digest": "a" * 64,
        "unit_id": "item-work",
        "unit_plan_digest": "b" * 64,
        "assigned_subtree_digest": "c" * 64,
        "child_run_id": "child-1",
        "output_revision": 1,
        "output_digest": "d" * 64,
        "whole_output_review_id": "review-01",
        "whole_output_review_digest": "e" * 64,
        "outcome": "accepted",
        "evidence_digest": "f" * 64,
        "output_refs": output_refs,
        "contributions": [],
        "workspace_changes": workspace_changes,
        "baseline_context_snapshot_digest": "2" * 64,
        "final_context_snapshot_digest": "3" * 64,
        "baseline_accepted_result_digests": [],
        "completion_assessment": "done",
    }


def _create_sub_tdp_run(store: FileRunStore, run_id: str, workspace: Path) -> None:
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


def _sub_tdp_production_state(
    store: FileRunStore,
    run_id: str,
    *,
    accepted: dict,
) -> dict:
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
    unit["child_run_id"] = str(accepted.get("child_run_id") or "child-1")
    unit["accepted_result"] = accepted
    unit["accepted_result_digest"] = accepted_result_digest(accepted)
    production = dict(store.load_production(run_id))
    production["sub_tdps"] = state
    return production


def test_accepted_result_rejects_workspace_change_sha_mismatch(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("01")
    _create_sub_tdp_run(store, run_id, tmp_path)
    ref = "src/a.py"
    sha = "1" * 64
    output_refs = [
        _output_ref(
            output_id="out-1",
            ref=ref,
            sha256=sha,
            size=1,
            snapshot_ref="artifacts/test/out.py",
        )
    ]
    accepted = _canonical_accepted_result(output_refs)
    accepted["workspace_changes"][ref]["sha256"] = "9" * 64
    production = _sub_tdp_production_state(store, run_id, accepted=accepted)
    with pytest.raises(PersistenceError, match="sha256"):
        expected = int(production["revision"])
        production["revision"] = expected + 1
        store.save_production(run_id, production, expected)


def test_accepted_result_sha_mismatch_leaves_production_bytes_unchanged(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("02")
    _create_sub_tdp_run(store, run_id, tmp_path)
    ref = "src/a.py"
    output_refs = [
        _output_ref(
            output_id="out-1",
            ref=ref,
            sha256="1" * 64,
            size=1,
            snapshot_ref="artifacts/test/out.py",
        )
    ]
    accepted = _canonical_accepted_result(output_refs)
    accepted["workspace_changes"][ref]["sha256"] = "9" * 64
    production = _sub_tdp_production_state(store, run_id, accepted=accepted)
    before = (store.run_dir(run_id) / "production.json").read_bytes()
    with pytest.raises(PersistenceError, match="sha256"):
        expected = int(production["revision"])
        production["revision"] = expected + 1
        store.save_production(run_id, production, expected)
    assert (store.run_dir(run_id) / "production.json").read_bytes() == before


def test_accepted_result_rejects_repeated_path_bound_to_first_sha(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("03")
    _create_sub_tdp_run(store, run_id, tmp_path)
    ref = "src/a.py"
    first_sha = "1" * 64
    latest_sha = "2" * 64
    output_refs = [
        _output_ref(
            output_id="out-1",
            ref=ref,
            sha256=first_sha,
            size=1,
            snapshot_ref="artifacts/test/out-v1.py",
        ),
        _output_ref(
            output_id="out-2",
            ref=ref,
            sha256=latest_sha,
            size=2,
            snapshot_ref="artifacts/test/out-v2.py",
        ),
    ]
    accepted = _canonical_accepted_result(output_refs)
    accepted["workspace_changes"][ref] = {
        "operation": "write",
        "sha256": first_sha,
        "size": 1,
        "snapshot_ref": "artifacts/test/out-v1.py",
    }
    production = _sub_tdp_production_state(store, run_id, accepted=accepted)
    with pytest.raises(PersistenceError, match="sha256"):
        expected = int(production["revision"])
        production["revision"] = expected + 1
        store.save_production(run_id, production, expected)


def test_accepted_result_rejects_missing_workspace_change_size(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("04")
    _create_sub_tdp_run(store, run_id, tmp_path)
    ref = "src/a.py"
    output_refs = [
        _output_ref(
            output_id="out-1",
            ref=ref,
            sha256="1" * 64,
            size=1,
            snapshot_ref="artifacts/test/out.py",
        )
    ]
    accepted = _canonical_accepted_result(output_refs)
    accepted["workspace_changes"][ref] = {
        "operation": "write",
        "sha256": "1" * 64,
        "snapshot_ref": "artifacts/test/out.py",
    }
    production = _sub_tdp_production_state(store, run_id, accepted=accepted)
    with pytest.raises(PersistenceError, match="size"):
        expected = int(production["revision"])
        production["revision"] = expected + 1
        store.save_production(run_id, production, expected)


def test_accepted_result_rejects_mismatched_workspace_change_snapshot_ref(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("05")
    _create_sub_tdp_run(store, run_id, tmp_path)
    ref = "src/a.py"
    output_refs = [
        _output_ref(
            output_id="out-1",
            ref=ref,
            sha256="1" * 64,
            size=1,
            snapshot_ref="artifacts/test/out.py",
        )
    ]
    accepted = _canonical_accepted_result(output_refs)
    accepted["workspace_changes"][ref]["snapshot_ref"] = "artifacts/test/other.py"
    production = _sub_tdp_production_state(store, run_id, accepted=accepted)
    with pytest.raises(PersistenceError, match="snapshot_ref"):
        expected = int(production["revision"])
        production["revision"] = expected + 1
        store.save_production(run_id, production, expected)


def test_attestation_rejects_workspace_change_sha_mismatch() -> None:
    ref = "src/a.py"
    output_refs = [
        _output_ref(
            output_id="out-1",
            ref=ref,
            sha256="1" * 64,
            size=1,
            snapshot_ref="artifacts/test/out.py",
        )
    ]
    accepted = _canonical_accepted_result(output_refs)
    accepted["workspace_changes"][ref]["sha256"] = "9" * 64
    unit = {
        "plan_item_id": "item-work",
        "child_run_id": "child-1",
        "unit_plan_digest": "b" * 64,
        "accepted_result": accepted,
        "accepted_result_digest": accepted_result_digest(accepted),
    }
    with pytest.raises(ValueError, match="sha256"):
        verify_accepted_result_attestation(unit)


def test_canonical_repeated_path_workspace_change_round_trips(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("06")
    _create_sub_tdp_run(store, run_id, tmp_path)
    ref = "src/a.py"
    output_refs = [
        _output_ref(
            output_id="out-1",
            ref=ref,
            sha256="1" * 64,
            size=1,
            snapshot_ref="artifacts/test/out-v1.py",
        ),
        _output_ref(
            output_id="out-2",
            ref=ref,
            sha256="2" * 64,
            size=2,
            snapshot_ref="artifacts/test/out-v2.py",
        ),
    ]
    accepted = _canonical_accepted_result(output_refs)
    production = _sub_tdp_production_state(store, run_id, accepted=accepted)
    expected = int(production["revision"])
    production["revision"] = expected + 1
    store.save_production(run_id, production, expected)
    reloaded = store.load_production(run_id)
    assert reloaded["sub_tdps"]["units"][0]["accepted_result"]["workspace_changes"] == {
        ref: {
            "operation": "write",
            "sha256": "2" * 64,
            "size": 2,
            "snapshot_ref": "artifacts/test/out-v2.py",
        }
    }


def test_accepted_result_record_output_passes_strict_parser(tmp_path: Path) -> None:
    from top_down_planning.domain.models import Plan, PlanItem
    from top_down_planning.persistence.persisted_validation import (
        _validate_accepted_result_schema,
    )

    store = FileRunStore(tmp_path)
    child_id = _new_run_id("07")
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
            "item-work": PlanItem(
                id="item-work",
                parent_id="item-root",
                order_key="1",
                title="Work",
                kind="work",
            ),
        },
    )
    store.create_run(child_id, plan=plan, **create_run_kwargs(tmp_path))
    complete_child_production(
        store,
        child_id,
        item_id="item-work",
        goal_assessment="done",
        ref="temp/out.md",
    )
    production = store.load_production(child_id)
    run = store.load_run(child_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["status"] = "completed"
    run["phase"] = "output_validated"
    run["outcome"] = "accepted"
    digests = dict(run.get("digests") or {})
    digests["output"] = compute_output_digest(production)
    run["digests"] = digests
    binding = dict(run.get("package_binding") or {})
    binding["whole_output_review_id"] = "review-1"
    binding["whole_output_review_digest"] = "e" * 64
    binding["baseline_context_snapshot_digest"] = "2" * 64
    binding["baseline_accepted_result_digests"] = []
    run["package_binding"] = binding
    store.save_run(child_id, run, expected)

    accepted = accepted_result_record(
        child_run=store.load_run(child_id),
        child_production=store.load_production(child_id),
        unit_id="item-work",
        unit_plan_digest="b" * 64,
        package_id="pkg",
        package_digest="a" * 64,
        assigned_subtree_digest="c" * 64,
        whole_output_review_id="review-1",
        whole_output_review_digest="e" * 64,
    )

    _validate_accepted_result_schema(accepted, label="canonical")
    verify_accepted_result_attestation(
        {
            "plan_item_id": "item-work",
            "child_run_id": child_id,
            "unit_plan_digest": "b" * 64,
            "accepted_result": accepted,
            "accepted_result_digest": accepted_result_digest(accepted),
        }
    )
