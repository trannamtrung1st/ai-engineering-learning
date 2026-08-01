"""Review-loop record revision CAS tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from core_tools.persistence import StoreRevisionConflictError
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.review_commit import (
    review_record_revision,
    save_review_with_expected_revision,
)
from tests.helpers import create_run_kwargs, make_review_loop


def _sample_plan() -> Plan:
    return Plan(
        id="plan-review-rev",
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


def _create_run(store: FileRunStore, run_id: str) -> None:
    store.create_run(
        run_id,
        plan=_sample_plan(),
        **create_run_kwargs(store.root),
    )


def test_save_review_with_expected_revision_bumps_record(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T007001-007001"
    _create_run(store, run_id)
    loop = make_review_loop(
        id="loop-rev-01",
        type="focused_plan",
        reviewer_session_id=None,
        target_revision=1,
        scope={"item_ids": ["item-root"]},
        status="pending",
        revise_at="blocker",
    )
    store.save_review(run_id, loop.to_dict())

    next_revision = save_review_with_expected_revision(
        store,
        run_id,
        loop,
        expected_revision=0,
    )
    assert next_revision == 1
    loaded = store.load_review(run_id, loop.id)
    assert review_record_revision(loaded) == 1


def test_save_review_with_expected_revision_rejects_stale_write(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T007002-007002"
    _create_run(store, run_id)
    loop = make_review_loop(
        id="loop-rev-02",
        type="focused_plan",
        reviewer_session_id=None,
        target_revision=1,
        scope={"item_ids": ["item-root"]},
        status="pending",
        revise_at="blocker",
    )
    store.save_review(run_id, loop.to_dict())

    with pytest.raises(StoreRevisionConflictError):
        save_review_with_expected_revision(
            store,
            run_id,
            loop,
            expected_revision=1,
        )
