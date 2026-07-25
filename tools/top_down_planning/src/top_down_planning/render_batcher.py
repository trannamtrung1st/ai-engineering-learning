"""Deterministic render batch assignment strategies."""

from __future__ import annotations

from top_down_planning.models import PlanState, RenderBatchStrategy, RenderConfig, RenderManifestItem


def assign_render_batches(
    plan: PlanState,
    items: list[RenderManifestItem],
    *,
    render_config: RenderConfig,
) -> list[str]:
    if not items:
        return []

    strategy = render_config.batch_strategy
    batch_size = max(1, render_config.batch_size)

    if strategy == RenderBatchStrategy.SINGLE:
        return [_batch_id(index) for index, _ in enumerate(items, start=1)]

    if strategy == RenderBatchStrategy.THROUGHPUT:
        return _throughput_batches(items, batch_size=batch_size)

    if strategy == RenderBatchStrategy.BRANCH:
        return _branch_batches(items, batch_size=batch_size)

    return _coherent_batches(items, batch_size=batch_size)


def _batch_id(index: int) -> str:
    return f"render-batch-{index:03d}"


def _throughput_batches(
    items: list[RenderManifestItem],
    *,
    batch_size: int,
) -> list[str]:
    batch_ids: list[str] = []
    batch_index = 1
    for offset in range(0, len(items), batch_size):
        batch_id = _batch_id(batch_index)
        batch_index += 1
        for _ in items[offset : offset + batch_size]:
            batch_ids.append(batch_id)
    return batch_ids


def _branch_batches(
    items: list[RenderManifestItem],
    *,
    batch_size: int,
) -> list[str]:
    by_branch: dict[str, list[RenderManifestItem]] = {}
    for item in items:
        by_branch.setdefault(item.top_level_branch_id, []).append(item)

    batch_ids: list[str] = []
    batch_index = 1
    item_to_batch: dict[str, str] = {}

    for branch_items in by_branch.values():
        chunks = [
            branch_items[offset : offset + batch_size]
            for offset in range(0, len(branch_items), batch_size)
        ]
        for chunk in chunks:
            batch_id = _batch_id(batch_index)
            batch_index += 1
            for entry in chunk:
                item_to_batch[entry.plan_item_id] = batch_id

    for item in items:
        batch_ids.append(item_to_batch[item.plan_item_id])
    return batch_ids


def _coherent_batches(
    items: list[RenderManifestItem],
    *,
    batch_size: int,
) -> list[str]:
    """Group by branch; split oversized branches into ordered chunks."""
    by_branch: dict[str, list[RenderManifestItem]] = {}
    for item in items:
        by_branch.setdefault(item.top_level_branch_id, []).append(item)

    item_to_batch: dict[str, str] = {}
    batch_index = 1

    for branch_id in sorted(by_branch.keys()):
        branch_items = sorted(by_branch[branch_id], key=lambda entry: entry.order)
        offset = 0
        while offset < len(branch_items):
            chunk = branch_items[offset : offset + batch_size]
            batch_id = _batch_id(batch_index)
            batch_index += 1
            for entry in chunk:
                item_to_batch[entry.plan_item_id] = batch_id
            offset += batch_size

    return [item_to_batch[item.plan_item_id] for item in items]


def unique_batch_ids(items: list[RenderManifestItem]) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item.assigned_batch_id not in seen:
            seen.append(item.assigned_batch_id)
    return seen


def items_for_batch(
    manifest_items: list[RenderManifestItem],
    batch_id: str,
) -> list[RenderManifestItem]:
    return [
        item
        for item in manifest_items
        if item.assigned_batch_id == batch_id
    ]
