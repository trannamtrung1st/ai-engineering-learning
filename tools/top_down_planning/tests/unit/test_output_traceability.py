"""Tests for plan_contracts and evidence_by_item output review traceability."""

from __future__ import annotations

from pathlib import Path

from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.production import build_output_traceability
from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.orchestrator.focused_review import build_focused_review_package
from top_down_planning.orchestrator.whole_output_review import (
    build_whole_output_review_package,
)
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs, minimal_resolved_config


def _plan() -> Plan:
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        outcome="Root outcome.",
        acceptance=["Root ok"],
        kind="aggregate",
    )
    a = PlanItem(
        id="item-a",
        parent_id="item-root",
        order_key="0000000000",
        title="A",
        outcome="A outcome.",
        acceptance=["A ok"],
        kind="work",
    )
    b = PlanItem(
        id="item-b",
        parent_id="item-root",
        order_key="0000000100",
        title="B",
        outcome="B outcome.",
        acceptance=["B ok"],
        kind="work",
    )
    return Plan(
        id="plan-trace",
        revision=3,
        output_goal="Deliver.",
        items={"item-root": root, "item-a": a, "item-b": b},
    )


def _production_with_shared_artifact() -> dict:
    return {
        "revision": 2,
        "output_revision": 1,
        "batches": [
            {
                "id": "batch-01",
                "plan_items": ["item-a", "item-b"],
                "status": "completed",
                "result": {
                    "outputs": [],
                    "contributions": [
                        {
                            "item_id": "item-a",
                            "output_refs": ["output-shared", "output-a"],
                            "summary": "A work",
                        },
                        {
                            "item_id": "item-b",
                            "output_refs": ["output-shared"],
                            "summary": "B work",
                        },
                    ],
                    "dispositions": {
                        "item-a": {"disposition": "completed"},
                        "item-b": {"disposition": "completed"},
                    },
                    "summary": "batch",
                },
            },
            {
                "id": "batch-stale",
                "plan_items": ["item-a"],
                "status": "completed",
                "evidence_status": "invalidated_by_reconciliation",
                "result": {
                    "contributions": [
                        {
                            "item_id": "item-a",
                            "output_refs": ["output-stale"],
                            "summary": "stale",
                        }
                    ],
                    "dispositions": {"item-a": {"disposition": "completed"}},
                    "summary": "stale",
                },
            },
        ],
        "dispositions": {
            "item-a": "completed",
            "item-b": "completed",
        },
        "output_evidence": [
            {
                "id": "output-shared",
                "type": "artifact",
                "ref": "shared.md",
                "sha256": "aa",
                "size": 1,
                "media_type": "text/plain",
                "captured_at": "2026-01-01T00:00:00Z",
                "batch_id": "batch-01",
                "snapshot_ref": "artifacts/u1/shared.md",
            },
            {
                "id": "output-a",
                "type": "artifact",
                "ref": "a.md",
                "sha256": "bb",
                "size": 1,
                "media_type": "text/plain",
                "captured_at": "2026-01-01T00:00:00Z",
                "batch_id": "batch-01",
                "snapshot_ref": "artifacts/u1/a.md",
            },
            {
                "id": "output-stale",
                "type": "artifact",
                "ref": "stale.md",
                "sha256": "cc",
                "size": 1,
                "media_type": "text/plain",
                "captured_at": "2026-01-01T00:00:00Z",
                "batch_id": "batch-stale",
                "snapshot_ref": "artifacts/u0/stale.md",
            },
        ],
    }


def test_whole_output_traceability_includes_contracts_and_evidence_by_item() -> None:
    plan = _plan()
    production = _production_with_shared_artifact()
    trace = build_output_traceability(plan, production)

    assert "item-a" in trace["plan_contracts"]
    assert trace["plan_contracts"]["item-a"]["title"] == "A"
    assert trace["plan_contracts"]["item-a"]["outcome"] == "A outcome."
    assert trace["plan_contracts"]["item-a"]["acceptance"] == ["A ok"]

    a_ids = [e["evidence_id"] for e in trace["evidence_by_item"]["item-a"]]
    b_ids = [e["evidence_id"] for e in trace["evidence_by_item"]["item-b"]]
    assert a_ids == ["output-shared", "output-a"]
    assert b_ids == ["output-shared"]
    assert "output-stale" not in a_ids


def test_shared_artifacts_appear_under_multiple_items() -> None:
    trace = build_output_traceability(_plan(), _production_with_shared_artifact())
    shared_a = next(
        e for e in trace["evidence_by_item"]["item-a"] if e["evidence_id"] == "output-shared"
    )
    shared_b = next(
        e for e in trace["evidence_by_item"]["item-b"] if e["evidence_id"] == "output-shared"
    )
    assert shared_a["ref"] == "shared.md"
    assert shared_b["sha256"] == "aa"


def test_invalidated_evidence_excluded_from_traceability() -> None:
    trace = build_output_traceability(_plan(), _production_with_shared_artifact())
    all_ids = [
        e["evidence_id"]
        for entries in trace["evidence_by_item"].values()
        for e in entries
    ]
    assert "output-stale" not in all_ids


def test_evidence_revision_updates_traceability() -> None:
    plan = _plan()
    production = _production_with_shared_artifact()
    production = dict(production)
    production["revision"] = 3
    production["output_revision"] = 2
    production["batches"] = list(production["batches"]) + [
        {
            "id": "batch-02",
            "plan_items": ["item-a"],
            "status": "completed",
            "result": {
                "contributions": [
                    {
                        "item_id": "item-a",
                        "output_refs": ["output-a2"],
                        "summary": "revised",
                    }
                ],
                "dispositions": {"item-a": {"disposition": "completed"}},
                "summary": "revision",
            },
        }
    ]
    production["output_evidence"] = list(production["output_evidence"]) + [
        {
            "id": "output-a2",
            "type": "artifact",
            "ref": "a2.md",
            "sha256": "dd",
            "size": 2,
            "media_type": "text/plain",
            "captured_at": "2026-01-01T01:00:00Z",
            "batch_id": "batch-02",
            "snapshot_ref": "artifacts/u2/a2.md",
        }
    ]
    trace = build_output_traceability(plan, production)
    a_ids = [e["evidence_id"] for e in trace["evidence_by_item"]["item-a"]]
    assert "output-a2" in a_ids


def test_whole_output_package_includes_traceability(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    plan = _plan()
    config = minimal_resolved_config()
    store.create_run(
        "run-20260101T000901-000901",
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=config),
        phase="whole_output_review",
    )
    production = _production_with_shared_artifact()
    loop = ReviewLoop(
        id="review-whole-output-01",
        type="whole_output",
        reviewer_session_id="sess",
        target_revision=1,
        scope={"kind": "whole_output"},
        status="in_progress",
    )
    package = build_whole_output_review_package(
        "run-20260101T000901-000901",
        store.load_run("run-20260101T000901-000901"),
        config,
        plan,
        production,
        loop,
    )
    assert "item-a" in package["plan_contracts"]
    assert package["evidence_by_item"]["item-a"]


def test_focused_output_package_includes_scoped_traceability(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    plan = _plan()
    config = minimal_resolved_config()
    store.create_run(
        "run-20260101T000902-000902",
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=config),
        phase="production",
    )
    production = _production_with_shared_artifact()
    loop = ReviewLoop(
        id="review-focused-output-01",
        type="focused_output",
        reviewer_session_id="sess",
        target_revision=1,
        scope={"kind": "focused_output", "item_ids": ["item-a"]},
        status="in_progress",
    )
    package = build_focused_review_package(
        "run-20260101T000902-000902",
        store.load_run("run-20260101T000902-000902"),
        config,
        loop,
        plan=plan,
        production=production,
    )
    assert set(package["plan_contracts"]) == {"item-a"}
    assert "item-b" not in package["evidence_by_item"]
    assert "output-shared" in [
        e["evidence_id"] for e in package["evidence_by_item"]["item-a"]
    ]
