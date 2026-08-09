"""Regression tests for Slice 3 round-18 review (TDP-PERSIST-069..070)."""

from __future__ import annotations

from pathlib import Path

import pytest

from core_tools.persistence import PersistenceError
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator.prepare_resume import _verify_production_evidence
from top_down_planning.package.lineage import (
    accepted_result_digest,
    verify_accepted_result_attestation,
    workspace_changes_from_output_evidence,
)
from top_down_planning.persistence import FileRunStore
from tests.helpers import (
    bind_evidence_snapshot,
    create_run_kwargs,
    decorate_sub_tdp_v2_package,
    mirrored_production_batch,
)
from top_down_planning.domain.sub_tdp_units import SubTdpUnit
from top_down_planning.persistence.sub_tdp_state import initial_sub_tdp_state


def _new_run_id(suffix: str) -> str:
    return f"run-20260101T0064{suffix}-0064{suffix}"


def _snapshot_path(store: FileRunStore, run_id: str, evidence: dict) -> Path:
    snapshot_ref = str(evidence.get("snapshot_ref") or "")
    return store.run_dir(run_id) / snapshot_ref


def _minimal_accepted_result(*, ref: str = "src/a.py", sha256: str = "1" * 64) -> dict:
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
        "output_refs": [
            {
                "id": "out-1",
                "type": "artifact",
                "ref": ref,
                "sha256": sha256,
                "size": 1,
                "media_type": "text/plain",
                "captured_at": "2026-01-01T00:00:00Z",
                "snapshot_ref": "artifacts/test/out.py",
            }
        ],
        "contributions": [],
        "workspace_changes": workspace_changes_from_output_evidence(
            [
                {
                    "id": "out-1",
                    "type": "artifact",
                    "ref": ref,
                    "sha256": sha256,
                    "size": 1,
                    "media_type": "text/plain",
                    "captured_at": "2026-01-01T00:00:00Z",
                    "snapshot_ref": "artifacts/test/out.py",
                }
            ]
        ),
        "baseline_context_snapshot_digest": "2" * 64,
        "final_context_snapshot_digest": "3" * 64,
        "baseline_accepted_result_digests": [],
        "completion_assessment": "done",
    }


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


def _non_live_batch_with_nested_snapshot(
    store: FileRunStore,
    run_id: str,
    *,
    batch_id: str,
    status: str,
    item_id: str = "item-work",
) -> tuple[dict, dict]:
    evidence = {
        "id": f"out-{batch_id}",
        "type": "artifact",
        "ref": f"src/{batch_id}.py",
        "sha256": "a" * 64,
        "size": 10,
        "media_type": "text/plain",
        "captured_at": "2026-01-01T00:00:00Z",
        "batch_id": batch_id,
    }
    evidence, nested = bind_evidence_snapshot(store, run_id, evidence)
    batch = {
        "id": batch_id,
        "status": status,
        "plan_items": [item_id],
        "result": {
            "outputs": [nested],
            "contributions": [],
            "dispositions": {},
        },
    }
    return batch, evidence


def test_accepted_result_rejects_extra_workspace_changes_path(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("01")
    _create_sub_tdp_run(store, run_id, tmp_path)
    accepted = _minimal_accepted_result()
    accepted["workspace_changes"]["src/extra.py"] = {
        "operation": "write",
        "sha256": "9" * 64,
    }
    accepted_result_digest(accepted)
    production = _sub_tdp_production_state(store, run_id, accepted=accepted)
    with pytest.raises(PersistenceError, match="workspace_changes"):
        expected = int(production["revision"])
        production["revision"] = expected + 1
        store.save_production(run_id, production, expected)


def test_accepted_result_extra_workspace_changes_leaves_production_bytes_unchanged(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("02")
    _create_sub_tdp_run(store, run_id, tmp_path)
    accepted = _minimal_accepted_result()
    accepted["workspace_changes"]["src/extra.py"] = {
        "operation": "write",
        "sha256": "9" * 64,
    }
    production = _sub_tdp_production_state(store, run_id, accepted=accepted)
    before = (store.run_dir(run_id) / "production.json").read_bytes()
    with pytest.raises(PersistenceError, match="workspace_changes"):
        expected = int(production["revision"])
        production["revision"] = expected + 1
        store.save_production(run_id, production, expected)
    assert (store.run_dir(run_id) / "production.json").read_bytes() == before


def test_attestation_rejects_extra_workspace_changes_path() -> None:
    accepted = _minimal_accepted_result()
    accepted["workspace_changes"]["src/extra.py"] = {
        "operation": "write",
        "sha256": "9" * 64,
    }
    unit = {
        "plan_item_id": "item-work",
        "child_run_id": "child-1",
        "unit_plan_digest": "b" * 64,
        "accepted_result": accepted,
        "accepted_result_digest": accepted_result_digest(accepted),
    }
    with pytest.raises(ValueError, match="workspace_changes"):
        verify_accepted_result_attestation(unit)


def test_canonical_accepted_result_with_one_output_path_round_trips(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("03")
    _create_sub_tdp_run(store, run_id, tmp_path)
    accepted = _minimal_accepted_result()
    production = _sub_tdp_production_state(store, run_id, accepted=accepted)
    expected = int(production["revision"])
    production["revision"] = expected + 1
    store.save_production(run_id, production, expected)
    reloaded = store.load_production(run_id)
    assert reloaded["sub_tdps"]["units"][0]["accepted_result"]["workspace_changes"] == {
        "src/a.py": {
            "operation": "write",
            "sha256": "1" * 64,
            "size": 1,
            "snapshot_ref": "artifacts/test/out.py",
        }
    }


def test_canonical_accepted_result_repeated_path_writes_round_trip(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("04")
    _create_sub_tdp_run(store, run_id, tmp_path)
    ref = "src/a.py"
    first_sha = "1" * 64
    latest_sha = "2" * 64
    output_refs = [
        {
            "id": "out-1",
            "type": "artifact",
            "ref": ref,
            "sha256": first_sha,
            "size": 1,
            "media_type": "text/plain",
            "captured_at": "2026-01-01T00:00:00Z",
            "snapshot_ref": "artifacts/test/out-v1.py",
        },
        {
            "id": "out-2",
            "type": "artifact",
            "ref": ref,
            "sha256": latest_sha,
            "size": 2,
            "media_type": "text/plain",
            "captured_at": "2026-01-02T00:00:00Z",
            "snapshot_ref": "artifacts/test/out-v2.py",
        },
    ]
    workspace_changes = workspace_changes_from_output_evidence(output_refs)
    accepted = _minimal_accepted_result(ref=ref, sha256=latest_sha)
    accepted["output_refs"] = output_refs
    accepted["workspace_changes"] = workspace_changes
    production = _sub_tdp_production_state(store, run_id, accepted=accepted)
    expected = int(production["revision"])
    production["revision"] = expected + 1
    store.save_production(run_id, production, expected)
    reloaded = store.load_production(run_id)
    assert reloaded["sub_tdps"]["units"][0]["accepted_result"]["workspace_changes"] == {
        ref: {
            "operation": "write",
            "sha256": latest_sha,
            "size": 2,
            "snapshot_ref": "artifacts/test/out-v2.py",
        }
    }


@pytest.mark.parametrize(
    ("run_suffix", "status"),
    [("07", "failed"), ("08", "aborted"), ("09", "started")],
)
def test_resume_ignores_non_live_batch_nested_snapshot(
    tmp_path: Path,
    run_suffix: str,
    status: str,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id(run_suffix)
    _create_sub_tdp_run(store, run_id, tmp_path)
    non_live_batch, non_live_evidence = _non_live_batch_with_nested_snapshot(
        store,
        run_id,
        batch_id=f"batch-{status}",
        status=status,
    )
    live_batch, live_evidence = mirrored_production_batch(
        batch_id="batch-live",
        evidence_id="out-live",
        store=store,
        run_id=run_id,
    )
    production = dict(store.load_production(run_id))
    production["batches"] = [non_live_batch, live_batch]
    production["output_evidence"] = [non_live_evidence, live_evidence]
    production["dispositions"] = {"item-work": "completed"}

    _snapshot_path(store, run_id, non_live_evidence).unlink()

    assert _verify_production_evidence(store, run_id, production) is None


def test_resume_fails_when_live_nested_snapshot_is_corrupt(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("10")
    _create_sub_tdp_run(store, run_id, tmp_path)
    live_batch, live_evidence = mirrored_production_batch(
        batch_id="batch-live",
        evidence_id="out-live",
        store=store,
        run_id=run_id,
    )
    production = dict(store.load_production(run_id))
    production["batches"] = [live_batch]
    production["output_evidence"] = [live_evidence]
    production["dispositions"] = {"item-work": "completed"}

    snapshot_path = _snapshot_path(store, run_id, live_evidence)
    snapshot_path.write_bytes(b"corrupt")

    result = _verify_production_evidence(store, run_id, production)
    assert result is not None
    assert "evidence integrity failure" in result
