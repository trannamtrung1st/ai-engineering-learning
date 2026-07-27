"""Coherent sequential batch scheduling for cumulative render authoring."""

from __future__ import annotations

from top_down_planning.models import (
    BatchStrategy,
    GenerationConfig,
    PlanItem,
    PlanState,
    RenderBatchItem,
    RenderConfig,
)
from top_down_planning.render_brief import actionable_leaf_items
from top_down_planning.scheduler import _coherence_key, _pack_into_batches, are_independent


def build_render_batch_schedule(
    plan: PlanState,
    *,
    render_config: RenderConfig,
    output_dir=None,
) -> tuple[list[RenderBatchItem], list[str]]:
    errors: list[str] = []
    leaves = actionable_leaf_items(plan)
    if not leaves:
        return [], errors

    generation = GenerationConfig(
        batch_strategy=render_config.batch_strategy,
        batch_size=render_config.batch_size,
        concurrent_batches=1,
        max_context_characters=render_config.max_context_characters,
        whole_plan_context=render_config.whole_plan_context,
    )

    ordered = sorted(leaves, key=lambda item: _coherence_key(plan, item))
    batches = _pack_into_batches(
        plan,
        ordered,
        generation=generation,
        max_batches=len(ordered),
        output_dir=output_dir,
    )

    items: list[RenderBatchItem] = []
    for batch_index, batch in enumerate(batches):
        item_ids = [item.id for item in batch]
        dependencies = _batch_dependencies(plan, batch)
        title = _batch_title(plan, batch)
        items.append(
            RenderBatchItem(
                batch_index=batch_index,
                item_ids=item_ids,
                dependencies=dependencies,
                title=title,
            )
        )
    return items, errors


def _batch_dependencies(plan: PlanState, batch: list[PlanItem]) -> list[str]:
    batch_ids = {item.id for item in batch}
    deps: set[str] = set()
    for item in batch:
        for dep in item.dependencies:
            if dep not in batch_ids:
                deps.add(dep)
    return sorted(deps)


def _batch_title(plan: PlanState, batch: list[PlanItem]) -> str:
    if len(batch) == 1:
        return batch[0].title
    parent_ids = {item.parent_id for item in batch}
    if len(parent_ids) == 1 and None not in parent_ids:
        parent = plan.item_by_id(next(iter(parent_ids)))
        if parent is not None:
            return f"{parent.title} ({len(batch)} items)"
    return f"Batch of {len(batch)} items"


def batches_covering_items(
    schedule: list[RenderBatchItem],
    item_ids: set[str],
) -> list[int]:
    return [
        batch.batch_index
        for batch in schedule
        if item_ids.intersection(batch.item_ids)
    ]


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
