"""Helpers for agent-selected render batch tracking."""

from __future__ import annotations

import json

from top_down_planning.digest import digest_text
from top_down_planning.models import PlanItem, PlanState, ProcessedBatchRecord
from top_down_planning.scheduler import are_independent


def processed_batches_digest(records: list[ProcessedBatchRecord]) -> str:
    payload = json.dumps(
        [record.model_dump(mode="json") for record in records],
        sort_keys=True,
    )
    return digest_text(payload)


def processed_batch_indices(records: list[ProcessedBatchRecord]) -> list[int]:
    return list(range(len(records)))


def validate_batch_independence(plan: PlanState, batch: list[PlanItem]) -> list[str]:
    errors: list[str] = []
    for left in batch:
        for right in batch:
            if left.id >= right.id:
                continue
            if not are_independent(plan, left, right):
                errors.append(
                    f"batch contains ancestor/descendant pair: {left.id!r}, {right.id!r}"
                )
    return errors


def validate_render_batch_selection(
    plan: PlanState,
    *,
    selected_ids: list[str],
    eligible_ids: set[str],
    covered_ids: set[str],
) -> list[str]:
    errors: list[str] = []
    if not selected_ids:
        errors.append(
            "Render batch must record select-batch with at least one eligible item"
        )
        return errors

    items: list[PlanItem] = []
    for item_id in selected_ids:
        if item_id in covered_ids:
            errors.append(f"{item_id} was already covered by a prior render batch")
        if eligible_ids and item_id not in eligible_ids:
            errors.append(f"{item_id} is not in the eligible item inventory")
        item = plan.item_by_id(item_id)
        if item is None:
            errors.append(f"Unknown plan item id: {item_id}")
            continue
        items.append(item)

    errors.extend(validate_batch_independence(plan, items))
    return errors
