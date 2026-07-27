"""Targeted invalidation for render state."""

from __future__ import annotations

from top_down_planning.models import (
    NodeRenderPhaseState,
    NodeRenderRevisionStatus,
    RenderDecisionRecord,
    RenderState,
)


def invalidate_on_read_set_change(
    state: RenderState,
    *,
    changed_digest: str,
    decisions: list[RenderDecisionRecord],
) -> RenderState:
    """Conservatively invalidate node revisions whose read set includes a changed digest."""
    updated = state.model_copy(deep=True)
    for decision in decisions:
        if decision.read_set_digest == changed_digest:
            phases = updated.nodes.setdefault(decision.node_id, {})
            phase_state = phases.setdefault(decision.phase.value, None)
            if phase_state is None:
                phase_state = NodeRenderPhaseState()
                phases[decision.phase.value] = phase_state
            revision = phase_state.revisions.get(decision.revision)
            if revision is not None:
                revision.status = NodeRenderRevisionStatus.INVALIDATED
    return updated


def conservative_full_invalidation(state: RenderState) -> RenderState:
    updated = state.model_copy(deep=True)
    for node_phases in updated.nodes.values():
        for phase_state in node_phases.values():
            for revision in phase_state.revisions.values():
                revision.status = NodeRenderRevisionStatus.INVALIDATED
    return updated
