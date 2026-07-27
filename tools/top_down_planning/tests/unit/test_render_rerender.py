"""Unit tests for targeted rerender helpers."""

from __future__ import annotations

from pathlib import Path

from top_down_planning.models import (
    ArtifactIntent,
    ArtifactLocation,
    ArtifactOperation,
    DecompositionStatus,
    OwnerKind,
    PlanItem,
    PlanState,
    RenderDecisionKind,
    RenderManifest,
    RenderManifestItem,
    RenderManifestItemStatus,
    RenderNodeTransaction,
    RenderOutputReviewDecision,
    RenderedOutputReviewResult,
    RenderState,
    SourceMetadata,
)
from top_down_planning.render_coordinator import RenderCoordinator
from top_down_planning.render_rerender import (
    prepare_targeted_rerender,
    resolve_rerender_node_ids,
)


def _plan_tree() -> PlanState:
    return PlanState(
        source=SourceMetadata(
            input_file="idea.md",
            output_goal="goal",
            input_digest="in",
            output_goal_digest="out",
        ),
        plan=[
            PlanItem(
                id="item-001",
                title="Root",
                objective="Root",
                depth=0,
                order=1,
                decomposition_status=DecompositionStatus.ACTIONABLE,
            ),
            PlanItem(
                id="item-002",
                title="Child",
                objective="Child",
                depth=1,
                order=2,
                parent_id="item-001",
                decomposition_status=DecompositionStatus.ACTIONABLE,
            ),
        ],
    )


def test_resolve_rerender_node_ids_expands_descendants() -> None:
    plan = _plan_tree()
    review = RenderedOutputReviewResult(
        plan_digest="plan",
        output_goal_digest="out",
        render_manifest_digest="manifest",
        deliverable_output_digest="deliverable",
        decision=RenderOutputReviewDecision.NEEDS_RERENDER,
        summary="fix root",
        affected_node_ids=["item-001"],
    )
    node_ids = resolve_rerender_node_ids(review, plan)
    assert node_ids == ["item-001", "item-002"]


def test_prepare_targeted_rerender_revokes_workspace_file(tmp_path: Path) -> None:
    plan = _plan_tree()
    output_dir = tmp_path / "planning-output"
    output_dir.mkdir()
    workspace = tmp_path
    coordinator = RenderCoordinator(
        output_dir=output_dir,
        workspace=workspace,
        run_id="run-1",
        dry_run=False,
    )
    manifest = RenderManifest(
        run_id="run-1",
        plan_digest="plan",
        output_goal_digest="out",
        render_config_digest="cfg",
        items=[
            RenderManifestItem(
                plan_item_id="item-002",
                parent_id="item-001",
                depth=1,
                order=2,
                revision=1,
                status=RenderManifestItemStatus.COMMITTED,
                title="Child",
            )
        ],
    )
    txn = RenderNodeTransaction(
        transaction_id="txn-item-002-render",
        node_id="item-002",
        context_digest="ctx",
        read_set_digest="ctx",
        plan_digest="plan",
        output_goal_digest="out",
        render_config_digest="cfg",
        decision=RenderDecisionKind.PRODUCE,
        artifacts=[
            ArtifactIntent(
                artifact_key="artifact-002",
                path="child.md",
                location=ArtifactLocation.FINAL,
                operation=ArtifactOperation.CREATE,
                owner_kind=OwnerKind.NODE,
                owner_id="item-002",
            )
        ],
        staged_files={"artifact-002": "# Child"},
    )
    with coordinator.acquire():
        result = coordinator.commit_candidate(txn, manifest_slot=1, plan_digest="plan")
        assert result.committed
    assert (workspace / "child.md").is_file()

    render_state = RenderState(run_id="run-1")
    with coordinator.acquire():
        target_ids = prepare_targeted_rerender(
            output_dir=output_dir,
            workspace=workspace,
            plan=plan,
            manifest=manifest,
            render_state=render_state,
            coordinator=coordinator,
            node_ids=["item-002"],
        )
    assert target_ids == {"item-002"}
    assert not (workspace / "child.md").exists()
    assert manifest.items[0].revision == 2
    assert manifest.items[0].status == RenderManifestItemStatus.PENDING
