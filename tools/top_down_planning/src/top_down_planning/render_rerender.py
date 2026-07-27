"""Targeted rerender preparation after output review."""

from __future__ import annotations

import shutil
from pathlib import Path

from top_down_planning.models import (
    NodeRenderPhaseState,
    NodeRenderRevision,
    NodeRenderRevisionStatus,
    PlanState,
    RenderManifest,
    RenderManifestItem,
    RenderManifestItemStatus,
    RenderNodePhase,
    RenderState,
    RenderedOutputReviewResult,
)
from top_down_planning.persistence import (
    render_decisions_dir,
    render_transaction_dir,
    save_ownership_ledger,
    save_render_manifest_to_output,
)
from top_down_planning.render_ownership import revoke_node_ownership


def resolve_rerender_node_ids(
    review_result: RenderedOutputReviewResult,
    plan: PlanState,
) -> list[str]:
    """Collect node ids to rerun from review output, including descendants."""
    roots: set[str] = set(review_result.affected_node_ids)
    for finding in review_result.findings:
        roots.update(finding.plan_item_ids)
    return sorted(expand_with_descendants(plan, roots))


def expand_with_descendants(plan: PlanState, root_ids: set[str]) -> set[str]:
    expanded = set(root_ids)
    changed = True
    while changed:
        changed = False
        for item in plan.plan:
            if item.parent_id in expanded and item.id not in expanded:
                expanded.add(item.id)
                changed = True
    return expanded


def prepare_targeted_rerender(
    *,
    output_dir: Path,
    workspace: Path,
    plan: PlanState,
    manifest: RenderManifest,
    render_state: RenderState,
    coordinator,
    node_ids: list[str],
) -> set[str]:
    """Revoke prior publication for affected nodes and schedule them for rerun."""
    target_ids = expand_with_descendants(plan, set(node_ids))
    if not target_ids:
        return set()

    coordinator._ledger = revoke_node_ownership(
        coordinator._ledger,
        workspace,
        sorted(target_ids),
    )
    save_ownership_ledger(output_dir, coordinator._ledger)

    for node_id in target_ids:
        _clear_node_decisions(output_dir, node_id)
        _bump_manifest_item(manifest, node_id)
        _reset_render_state_node(render_state, node_id)

    save_render_manifest_to_output(output_dir, manifest)
    return target_ids


def _clear_node_decisions(output_dir: Path, node_id: str) -> None:
    decisions_root = render_decisions_dir(output_dir) / node_id
    if decisions_root.is_dir():
        shutil.rmtree(decisions_root)
    txn_dir = render_transaction_dir(output_dir, f"txn-{node_id}-render")
    if txn_dir.is_dir():
        shutil.rmtree(txn_dir)


def _bump_manifest_item(manifest: RenderManifest, node_id: str) -> None:
    for item in manifest.items:
        if item.plan_item_id != node_id:
            continue
        item.revision += 1
        item.status = RenderManifestItemStatus.PENDING
        item.decision_path = None
        return


def _reset_render_state_node(render_state: RenderState, node_id: str) -> None:
    phase_key = RenderNodePhase.RENDER.value
    node_phases = render_state.nodes.setdefault(node_id, {})
    phase_state = node_phases.get(phase_key)
    if not isinstance(phase_state, NodeRenderPhaseState):
        phase_state = NodeRenderPhaseState()
        node_phases[phase_key] = phase_state
    next_revision = max(phase_state.current_revision, 1) + 1
    phase_state.current_revision = next_revision
    phase_state.revisions[next_revision] = NodeRenderRevision(
        status=NodeRenderRevisionStatus.PENDING,
    )


def manifest_items_for_rerender(
    items: list[RenderManifestItem],
    only_node_ids: set[str] | None,
) -> list[RenderManifestItem]:
    if only_node_ids is None:
        return items
    return [item for item in items if item.plan_item_id in only_node_ids]
