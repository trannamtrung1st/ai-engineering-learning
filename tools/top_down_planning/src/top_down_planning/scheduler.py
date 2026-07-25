"""Selection of expandable planning items for sequential and concurrent batches."""

from __future__ import annotations

from pathlib import Path

from top_down_planning.digest import compute_plan_digest
from top_down_planning.generation_context import (
    build_plan_overview,
    estimate_context_size,
    select_relevant_node_ids,
)
from top_down_planning.models import (
    BatchStrategy,
    DecompositionStatus,
    GenerationConfig,
    PlanItem,
    PlanState,
    SourceMetadata,
)


def expandable_items(plan: PlanState) -> list[PlanItem]:
    return [
        item
        for item in plan.plan
        if item.decomposition_status == DecompositionStatus.NEEDS_EXPANSION
    ]


def amendable_items(plan: PlanState, node_ids: list[str]) -> list[PlanItem]:
    """Return actionable items eligible for in-place revision."""
    allowed = set(node_ids)
    return sorted(
        [
            item
            for item in plan.plan
            if item.id in allowed
            and item.decomposition_status == DecompositionStatus.ACTIONABLE
        ],
        key=lambda item: (item.depth, item.order),
    )


def is_ancestor(plan: PlanState, ancestor_id: str, item_id: str) -> bool:
    current = plan.item_by_id(item_id)
    while current is not None and current.parent_id is not None:
        if current.parent_id == ancestor_id:
            return True
        current = plan.item_by_id(current.parent_id)
    return False


def are_independent(plan: PlanState, left: PlanItem, right: PlanItem) -> bool:
    if left.id == right.id:
        return False
    return not is_ancestor(plan, left.id, right.id) and not is_ancestor(
        plan, right.id, left.id
    )


def _ordered_expandable_items(plan: PlanState) -> list[PlanItem]:
    return sorted(expandable_items(plan), key=lambda item: (item.depth, item.order))


def _select_wave_candidates(
    plan: PlanState,
    *,
    generation: GenerationConfig,
    max_batches: int,
) -> list[PlanItem]:
    """Pick expandable items for one wave with no ancestor/descendant pairs."""
    candidates = _ordered_expandable_items(plan)
    if not candidates:
        return []

    if generation.batch_strategy == BatchStrategy.SINGLE:
        capacity = max_batches
    else:
        capacity = max_batches * generation.batch_size

    selected: list[PlanItem] = []
    for item in candidates:
        if len(selected) >= capacity:
            break
        if any(not are_independent(plan, item, other) for other in selected):
            continue
        selected.append(item)
    return selected


def _coherence_key(plan: PlanState, item: PlanItem) -> tuple[int, str, int]:
    parent_key = item.parent_id or ""
    return (item.depth, parent_key, item.order)


_GLOBAL_CONSISTENCY_OVERHEAD = 900


def _estimate_batch_context_size(
    plan: PlanState,
    batch: list[PlanItem],
    *,
    output_dir: Path | None = None,
) -> int:
    selected_ids = {item.id for item in batch}
    relevant_ids = select_relevant_node_ids(
        plan,
        selected_ids,
        output_dir=output_dir,
    )
    overview = ""
    if output_dir is not None:
        plan_digest = compute_plan_digest(plan)
        overview = build_plan_overview(plan, plan_digest, output_dir=output_dir)
    return (
        estimate_context_size(
            selected_items=batch,
            relevant_ids=relevant_ids,
            plan=plan,
            overview=overview,
        )
        + _GLOBAL_CONSISTENCY_OVERHEAD
    )


def _pack_into_batches(
    plan: PlanState,
    candidates: list[PlanItem],
    *,
    generation: GenerationConfig,
    max_batches: int,
    output_dir: Path | None = None,
) -> list[list[PlanItem]]:
    if not candidates:
        return []

    if generation.batch_strategy == BatchStrategy.SINGLE:
        return [[item] for item in candidates[:max_batches]]

    remaining = list(candidates)
    batches: list[list[PlanItem]] = []

    while remaining and len(batches) < max_batches:
        seed = remaining.pop(0)
        batch = [seed]

        if generation.batch_strategy == BatchStrategy.THROUGHPUT:
            while len(batch) < generation.batch_size and remaining:
                next_item = remaining[0]
                if all(are_independent(plan, next_item, other) for other in batch):
                    batch.append(remaining.pop(0))
                else:
                    break
            batches.append(batch)
            continue

        index = 0
        while index < len(remaining) and len(batch) < generation.batch_size:
            candidate = remaining[index]
            if not all(are_independent(plan, candidate, other) for other in batch):
                index += 1
                continue

            same_parent = candidate.parent_id == seed.parent_id
            nearby_depth = abs(candidate.depth - seed.depth) <= 1
            if not same_parent and not nearby_depth and len(batch) >= 1:
                index += 1
                continue

            trial = batch + [candidate]
            if (
                _estimate_batch_context_size(plan, trial, output_dir=output_dir)
                > generation.max_context_characters
            ):
                index += 1
                continue

            batch.append(remaining.pop(index))
            index = 0

        batches.append(batch)

    return [batch for batch in batches if batch]


def select_concurrent_batches(
    plan: PlanState,
    generation: GenerationConfig,
    *,
    max_batches: int,
    output_dir: Path | None = None,
) -> list[list[PlanItem]]:
    """Return up to ``max_batches`` disjoint batches from independent expandable items."""
    if max_batches <= 0:
        return []

    wave_candidates = _select_wave_candidates(
        plan,
        generation=generation,
        max_batches=max_batches,
    )
    if not wave_candidates:
        return []

    if generation.batch_strategy == BatchStrategy.COHERENT:
        wave_candidates = sorted(
            wave_candidates,
            key=lambda item: _coherence_key(plan, item),
        )

    return _pack_into_batches(
        plan,
        wave_candidates,
        generation=generation,
        max_batches=max_batches,
        output_dir=output_dir,
    )


def select_batch(plan: PlanState, generation: GenerationConfig) -> list[PlanItem]:
    """Return the first concurrent batch for single-batch scheduling."""
    batches = select_concurrent_batches(plan, generation, max_batches=1)
    return batches[0] if batches else []


def select_amend_batches(
    plan: PlanState,
    node_ids: list[str],
    generation: GenerationConfig,
    *,
    max_batches: int,
    output_dir: Path | None = None,
) -> list[list[PlanItem]]:
    """Return concurrent amend batches from pending actionable revision targets."""
    if max_batches <= 0:
        return []

    candidates = amendable_items(plan, node_ids)
    if not candidates:
        return []

    if generation.batch_strategy == BatchStrategy.COHERENT:
        candidates = sorted(candidates, key=lambda item: _coherence_key(plan, item))

    return _pack_into_batches(
        plan,
        candidates,
        generation=generation,
        max_batches=max_batches,
        output_dir=output_dir,
    )


def wave_batch_budget(generation: GenerationConfig, *, remaining_iterations: int) -> int:
    if remaining_iterations <= 0:
        return 0
    return min(generation.concurrent_batches, remaining_iterations)


def next_item_id(plan: PlanState) -> str:
    max_num = 0
    for item in plan.plan:
        if item.id.startswith("item-"):
            suffix = item.id.removeprefix("item-")
            if suffix.isdigit():
                max_num = max(max_num, int(suffix))
    return f"item-{max_num + 1:03d}"


def next_order(plan: PlanState) -> int:
    if not plan.plan:
        return 1
    return max(item.order for item in plan.plan) + 1


def initialize_root_plan(*, source: SourceMetadata) -> PlanState:
    from top_down_planning.models import ReadinessStatus, ResultMetadata

    root = PlanItem(
        id="item-001",
        parent_id=None,
        title="Understand and plan the requested work",
        objective="Transform the input into the requested final plan",
        depth=0,
        order=1,
        decomposition_status=DecompositionStatus.NEEDS_EXPANSION,
        readiness_status=ReadinessStatus.PENDING,
    )
    return PlanState(
        source=source,
        plan=[root],
        result=ResultMetadata(),
    )
