"""Unit tests for render invalidation and resume."""

from __future__ import annotations

from top_down_planning.models import (
    NodeRenderPhaseState,
    NodeRenderRevision,
    NodeRenderRevisionStatus,
    RenderDecisionKind,
    RenderDecisionRecord,
    RenderNodePhase,
    RenderState,
)
from top_down_planning.render_invalidation import (
    conservative_full_invalidation,
    invalidate_on_read_set_change,
)


def test_conservative_full_invalidation():
    state = RenderState(
        run_id="run-1",
        nodes={
            "item-001": {
                "render": NodeRenderPhaseState(
                    current_revision=1,
                    revisions={
                        1: NodeRenderRevision(
                            status=NodeRenderRevisionStatus.COMMITTED,
                            decision=RenderDecisionKind.PRODUCE,
                        )
                    },
                )
            }
        },
    )
    updated = conservative_full_invalidation(state)
    revision = updated.nodes["item-001"]["render"].revisions[1]
    assert revision.status == NodeRenderRevisionStatus.INVALIDATED


def test_read_set_invalidation():
    state = RenderState(run_id="run-1")
    decisions = [
        RenderDecisionRecord(
            run_id="run-1",
            decision_id="d1",
            node_id="item-001",
            phase=RenderNodePhase.RENDER,
            revision=1,
            plan_digest="plan",
            decision=RenderDecisionKind.PRODUCE,
            read_set_digest="digest-a",
        )
    ]
    state.nodes["item-001"] = {
        "render": NodeRenderPhaseState(
            current_revision=1,
            revisions={
                1: NodeRenderRevision(status=NodeRenderRevisionStatus.COMMITTED)
            },
        )
    }
    updated = invalidate_on_read_set_change(
        state,
        changed_digest="digest-a",
        decisions=decisions,
    )
    assert (
        updated.nodes["item-001"]["render"].revisions[1].status
        == NodeRenderRevisionStatus.INVALIDATED
    )
