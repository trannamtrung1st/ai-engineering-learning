"""Regression tests for Slice 3 round-20 review (TDP-PERSIST-072)."""

from __future__ import annotations

from pathlib import Path

import pytest

from core_tools.persistence import PersistenceError
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.package.lineage import (
    accepted_result_digest,
    accepted_result_record,
    verify_accepted_result_attestation,
)
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.digests import compute_output_digest
from tests.helpers import (
    bind_evidence_snapshot,
    complete_child_production,
    create_run_kwargs,
)


def _new_run_id(suffix: str) -> str:
    return f"run-20260101T0066{suffix}-0066{suffix}"


def _create_run(store: FileRunStore, run_id: str, workspace: Path) -> None:
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
    store.create_run(run_id, plan=plan, **create_run_kwargs(workspace))


def _evidence_row(
    *,
    output_id: str,
    batch_id: str,
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
        "batch_id": batch_id,
    }


def _nested_output(
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


def _completed_batch(
    *,
    batch_id: str,
    nested_outputs: list[dict],
    item_id: str = "item-work",
) -> dict:
    return {
        "id": batch_id,
        "status": "completed",
        "plan_items": [item_id],
        "result": {
            "outputs": nested_outputs,
            "contributions": [
                {
                    "item_id": item_id,
                    "output_refs": [str(output["id"]) for output in nested_outputs],
                    "summary": "done",
                }
            ],
            "dispositions": {
                item_id: {"disposition": "completed", "evidence": "done"},
            },
        },
    }


def _production_with_reordered_same_batch_mirrors(
    store: FileRunStore,
    run_id: str,
) -> dict:
    ref = "src/a.py"
    old_sha = "1" * 64
    new_sha = "2" * 64
    old_nested = _nested_output(
        output_id="out-old",
        ref=ref,
        sha256=old_sha,
        size=1,
        snapshot_ref="artifacts/test/old.bin",
    )
    new_nested = _nested_output(
        output_id="out-new",
        ref=ref,
        sha256=new_sha,
        size=2,
        snapshot_ref="artifacts/test/new.bin",
    )
    old_top = _evidence_row(
        output_id="out-old",
        batch_id="batch-1",
        ref=ref,
        sha256=old_sha,
        size=1,
        snapshot_ref="artifacts/test/old.bin",
    )
    new_top = _evidence_row(
        output_id="out-new",
        batch_id="batch-1",
        ref=ref,
        sha256=new_sha,
        size=2,
        snapshot_ref="artifacts/test/new.bin",
    )
    for row in (old_top, new_top):
        bind_evidence_snapshot(
            store,
            run_id,
            row,
            content=f"{row['id']}\n".encode(),
        )
    batch = _completed_batch(
        batch_id="batch-1",
        nested_outputs=[old_nested, new_nested],
    )
    batch["result"]["outputs"] = [
        {key: value for key, value in old_top.items() if key != "batch_id"},
        {key: value for key, value in new_top.items() if key != "batch_id"},
    ]
    production = dict(store.load_production(run_id))
    production["batches"] = [batch]
    production["output_evidence"] = [new_top, old_top]
    production["dispositions"] = {"item-work": "completed"}
    return production


def test_save_production_rejects_reordered_same_batch_output_mirrors(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("01")
    _create_run(store, run_id, tmp_path)
    production = _production_with_reordered_same_batch_mirrors(store, run_id)
    with pytest.raises(PersistenceError, match="sequence"):
        expected = int(production["revision"])
        production["revision"] = expected + 1
        store.save_production(run_id, production, expected)


def test_reordered_mirror_rejection_leaves_production_bytes_unchanged(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("02")
    _create_run(store, run_id, tmp_path)
    production = _production_with_reordered_same_batch_mirrors(store, run_id)
    before = (store.run_dir(run_id) / "production.json").read_bytes()
    with pytest.raises(PersistenceError, match="sequence"):
        expected = int(production["revision"])
        production["revision"] = expected + 1
        store.save_production(run_id, production, expected)
    assert (store.run_dir(run_id) / "production.json").read_bytes() == before


def test_save_production_rejects_cross_batch_reordered_output_mirrors(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("03")
    _create_run(store, run_id, tmp_path)
    first_nested = _nested_output(
        output_id="out-a",
        ref="src/a.py",
        sha256="1" * 64,
        size=1,
        snapshot_ref="artifacts/test/a.bin",
    )
    second_nested = _nested_output(
        output_id="out-b",
        ref="src/b.py",
        sha256="2" * 64,
        size=2,
        snapshot_ref="artifacts/test/b.bin",
    )
    first_top = _evidence_row(
        output_id="out-a",
        batch_id="batch-a",
        ref="src/a.py",
        sha256="1" * 64,
        size=1,
        snapshot_ref="artifacts/test/a.bin",
    )
    second_top = _evidence_row(
        output_id="out-b",
        batch_id="batch-b",
        ref="src/b.py",
        sha256="2" * 64,
        size=2,
        snapshot_ref="artifacts/test/b.bin",
    )
    for row in (first_top, second_top):
        bind_evidence_snapshot(
            store,
            run_id,
            row,
            content=f"{row['id']}\n".encode(),
        )
    batch_a = _completed_batch(batch_id="batch-a", nested_outputs=[first_nested])
    batch_b = _completed_batch(batch_id="batch-b", nested_outputs=[second_nested])
    batch_a["result"]["outputs"] = [
        {key: value for key, value in first_top.items() if key != "batch_id"}
    ]
    batch_b["result"]["outputs"] = [
        {key: value for key, value in second_top.items() if key != "batch_id"}
    ]
    production = dict(store.load_production(run_id))
    production["batches"] = [batch_a, batch_b]
    production["output_evidence"] = [second_top, first_top]
    production["dispositions"] = {"item-work": "completed"}
    with pytest.raises(PersistenceError, match="sequence"):
        expected = int(production["revision"])
        production["revision"] = expected + 1
        store.save_production(run_id, production, expected)


def test_accepted_result_record_round_trips_when_mirror_sequence_matches(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    child_id = _new_run_id("04")
    _create_run(store, child_id, tmp_path)
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
    verify_accepted_result_attestation(
        {
            "plan_item_id": "item-work",
            "child_run_id": child_id,
            "unit_plan_digest": "b" * 64,
            "accepted_result": accepted,
            "accepted_result_digest": accepted_result_digest(accepted),
        }
    )
