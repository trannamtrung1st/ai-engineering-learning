"""Tests for focused-output evidence_revision during production."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.agent_tool import ProductionAgentService, RequestError
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator.phases import PRODUCTION
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs, grant_capability, whole_plan_approval_record, save_review_payload


def _create_run(store: FileRunStore, run_id: str = "run-20260101T000551-000551") -> None:
    root = PlanItem(id="item-root", parent_id=None, order_key="0000000000", title="Root", kind="aggregate")
    first = PlanItem(
        id="item-first",
        parent_id="item-root",
        order_key="0000000000",
        title="First",
        outcome="First outcome.",
        kind="work",
    )
    second = PlanItem(
        id="item-second",
        parent_id="item-root",
        order_key="0000000100",
        title="Second",
        outcome="Second outcome.",
        kind="work",
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver.",
        items={"item-root": root, "item-first": first, "item-second": second},
    )
    config = {
        "run": {"output_goal": "Deliver.", "input_refs": ["README.md"]},
        "planning": {
            "stop_hint": "Stop.",
            "max_depth": 4,
            "max_expansion_per_item": 7,
        },
        "limits": {"production": {"max_batches": 50, "max_agent_turns_per_batch": 10}},
    }
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=config),
        phase=PRODUCTION,
    )
    save_review_payload(store, run_id, whole_plan_approval_record(store, run_id))
    production = store.load_production(run_id)
    expected = int(production["revision"])
    production = dict(production)
    production["revision"] = expected + 1
    production["output_revision"] = 1
    production["dispositions"] = {
        "item-first": "completed",
        "item-second": "completed",
    }
    production["batches"] = [
        {
            "id": "batch-01",
            "plan_items": ["item-first", "item-second"],
            "status": "completed",
            "result": {
                "outputs": [],
                "contributions": [
                    {
                        "item_id": "item-first",
                        "output_refs": ["output-first"],
                        "summary": "initial",
                    }
                ],
                "dispositions": {
                    "item-first": {"disposition": "completed"},
                    "item-second": {"disposition": "completed"},
                },
                "summary": "initial",
            },
        }
    ]
    production["output_evidence"] = [
        {
            "id": "output-first",
            "type": "artifact",
            "ref": "first.txt",
            "sha256": "aa",
            "size": 1,
            "media_type": "text/plain",
            "captured_at": "2026-01-01T00:00:00Z",
            "batch_id": "batch-01",
            "snapshot_ref": "artifacts/u1/first.txt",
        }
    ]
    production["completion_claim"] = {
        "goal_met": True,
        "goal_assessment": "done",
        "summary": "",
        "plan_revision": 0,
        "output_revision": 1,
        "all_applicable_items_processed": True,
    }
    store.save_production(run_id, production, expected)


def _focused_review(*, item_ids: list[str], status: str = "changes_requested") -> dict:
    return {
        "id": "review-focused-output-01",
        "type": "focused_output",
        "revise_at": "blocker",
        "reviewer_session_id": "stub-session-reviewer",
        "target_revision": 1,
        "scope": {"kind": "focused_output", "item_ids": item_ids},
        "status": status,
        "findings": [
            {
                "id": "finding-01",
                "severity": "blocker",
                "target_refs": item_ids[:1],
                "issue": "Need better evidence.",
                "recommended_change": "Add revised artifact.",
                "status": "unresolved",
            }
        ],
        "revision_cycles": 1,
    }


def test_focused_evidence_revision_succeeds(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    save_review_payload(store, "run-20260101T000551-000551", _focused_review(item_ids=["item-first"]))
    artifact = tmp_path / "first-v2.txt"
    artifact.write_text("revised", encoding="utf-8")
    service = ProductionAgentService(store, "run-20260101T000551-000551")
    token = grant_capability(
        store, "run-20260101T000551-000551", role="producer", phase=PRODUCTION
    )

    result = service.apply(
        {
            "production_revision": 1,
            "evidence_revision": True,
            "focused_review_loop_id": "review-focused-output-01",
            "plan_items": ["item-first"],
            "dispositions": {
                "item-first": {
                    "disposition": "completed",
                    "evidence": "Revised artifact.",
                }
            },
            "outputs": [
                {"id": "output-first-v2", "type": "artifact", "ref": "first-v2.txt"}
            ],
            "contributions": [
                {
                    "item_id": "item-first",
                    "output_refs": ["output-first-v2"],
                    "summary": "Addressed focused finding.",
                }
            ],
            "summary": "Focused evidence revision.",
        },
        capability_token=token,
    )

    assert result["ok"] is True
    production = store.load_production("run-20260101T000551-000551")
    assert production["output_revision"] == 2
    assert production["completion_claim"] is None
    evidence_ids = {e["id"] for e in production["output_evidence"]}
    assert "output-first-v2" in evidence_ids


def test_focused_evidence_revision_rejects_stale_target_revision(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    stale_loop = _focused_review(item_ids=["item-first"])
    stale_loop["target_revision"] = 0
    save_review_payload(store, "run-20260101T000551-000551", stale_loop)
    artifact = tmp_path / "first-v2.txt"
    artifact.write_text("revised", encoding="utf-8")
    service = ProductionAgentService(store, "run-20260101T000551-000551")
    token = grant_capability(
        store, "run-20260101T000551-000551", role="producer", phase=PRODUCTION
    )

    with pytest.raises(RequestError, match="does not match current output revision"):
        service.apply(
            {
                "production_revision": 1,
                "evidence_revision": True,
                "focused_review_loop_id": "review-focused-output-01",
                "plan_items": ["item-first"],
                "dispositions": {"item-first": {"disposition": "completed"}},
                "outputs": [
                    {"id": "output-first-v2", "type": "artifact", "ref": "first-v2.txt"}
                ],
                "contributions": [
                    {
                        "item_id": "item-first",
                        "output_refs": ["output-first-v2"],
                        "summary": "stale loop",
                    }
                ],
                "summary": "stale loop",
            },
            capability_token=token,
        )


def test_focused_evidence_revision_rejects_out_of_scope(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    save_review_payload(store, "run-20260101T000551-000551", _focused_review(item_ids=["item-first"]))
    artifact = tmp_path / "second.txt"
    artifact.write_text("x", encoding="utf-8")
    service = ProductionAgentService(store, "run-20260101T000551-000551")
    token = grant_capability(
        store, "run-20260101T000551-000551", role="producer", phase=PRODUCTION
    )

    with pytest.raises(RequestError, match="not targeted by open required focused-output"):
        service.apply(
            {
                "production_revision": 1,
                "evidence_revision": True,
                "focused_review_loop_id": "review-focused-output-01",
                "plan_items": ["item-second"],
                "dispositions": {"item-second": {"disposition": "completed"}},
                "outputs": [
                    {"id": "output-second", "type": "artifact", "ref": "second.txt"}
                ],
                "contributions": [
                    {
                        "item_id": "item-second",
                        "output_refs": ["output-second"],
                        "summary": "out of scope",
                    }
                ],
                "summary": "bad",
            },
            capability_token=token,
        )


def test_focused_evidence_revision_rejects_disposition_change(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    save_review_payload(store, "run-20260101T000551-000551", _focused_review(item_ids=["item-first"]))
    artifact = tmp_path / "first-v2.txt"
    artifact.write_text("revised", encoding="utf-8")
    service = ProductionAgentService(store, "run-20260101T000551-000551")
    token = grant_capability(
        store, "run-20260101T000551-000551", role="producer", phase=PRODUCTION
    )

    with pytest.raises(RequestError, match="cannot change disposition"):
        service.apply(
            {
                "production_revision": 1,
                "evidence_revision": True,
                "focused_review_loop_id": "review-focused-output-01",
                "plan_items": ["item-first"],
                "dispositions": {"item-first": {"disposition": "superseded"}},
                "outputs": [
                    {"id": "output-first-v2", "type": "artifact", "ref": "first-v2.txt"}
                ],
                "contributions": [
                    {
                        "item_id": "item-first",
                        "output_refs": ["output-first-v2"],
                        "summary": "bad",
                    }
                ],
                "summary": "bad",
            },
            capability_token=token,
        )


def test_focused_evidence_revision_requires_new_evidence(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    save_review_payload(store, "run-20260101T000551-000551", _focused_review(item_ids=["item-first"]))
    service = ProductionAgentService(store, "run-20260101T000551-000551")
    token = grant_capability(
        store, "run-20260101T000551-000551", role="producer", phase=PRODUCTION
    )

    with pytest.raises(RequestError, match="requires outputs"):
        service.apply(
            {
                "production_revision": 1,
                "evidence_revision": True,
                "focused_review_loop_id": "review-focused-output-01",
                "plan_items": ["item-first"],
                "dispositions": {"item-first": {"disposition": "completed"}},
                "outputs": [],
                "contributions": [],
                "summary": "no evidence",
            },
            capability_token=token,
        )


def test_submit_completion_blocked_while_focused_findings_unresolved(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    save_review_payload(store, "run-20260101T000551-000551", _focused_review(item_ids=["item-first"]))
    service = ProductionAgentService(store, "run-20260101T000551-000551")
    token = grant_capability(
        store, "run-20260101T000551-000551", role="producer", phase=PRODUCTION
    )

    with pytest.raises(RequestError, match="focused output findings"):
        service.submit_completion(
            {
                "goal_met": True,
                "goal_assessment": "Everything is done.",
            },
            capability_token=token,
        )
