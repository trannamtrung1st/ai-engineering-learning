"""Integration tests for per-node render pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.digest import compute_plan_digest, compute_render_config_digest
from top_down_planning.models import (
    ArtifactIntent,
    ArtifactLocation,
    ArtifactOperation,
    DecompositionStatus,
    OwnerKind,
    PlanItem,
    PlanState,
    RenderConfig,
    RenderDecisionKind,
    RenderNodeTransaction,
    SourceMetadata,
)
from top_down_planning.persistence import render_decisions_dir
from top_down_planning.render_coordinator import RenderCoordinator
from top_down_planning.render_manifest import build_render_manifest


def _simple_plan() -> PlanState:
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
                title="Feature",
                objective="Deliver feature",
                depth=0,
                order=1,
                decomposition_status=DecompositionStatus.ACTIONABLE,
            ),
        ],
    )


def test_render_manifest_builds_all_nodes(tmp_path: Path):
    plan = _simple_plan()
    manifest, errors = build_render_manifest(
        plan,
        run_id="run-test",
        plan_digest=compute_plan_digest(plan),
        output_goal_digest="out",
        render_config=RenderConfig(),
    )
    assert errors == []
    assert len(manifest.items) == 1
    assert manifest.items[0].plan_item_id == "item-001"


@pytest.mark.asyncio
async def test_dry_run_does_not_publish_workspace(tmp_path: Path):
    output_dir = tmp_path / "planning-output"
    output_dir.mkdir()
    workspace = tmp_path
    coordinator = RenderCoordinator(
        output_dir=output_dir,
        workspace=workspace,
        run_id="run-dry",
        dry_run=True,
    )
    txn = RenderNodeTransaction(
        transaction_id="txn-item-001-render",
        node_id="item-001",
        context_digest="ctx",
        read_set_digest="ctx",
        plan_digest="plan",
        output_goal_digest="out",
        render_config_digest=compute_render_config_digest(RenderConfig(dry_run=True)),
        decision=RenderDecisionKind.PRODUCE,
        artifacts=[
            ArtifactIntent(
                artifact_key="artifact-001",
                path="implementation-plan.md",
                location=ArtifactLocation.FINAL,
                operation=ArtifactOperation.CREATE,
                owner_kind=OwnerKind.NODE,
                owner_id="item-001",
            )
        ],
        staged_files={"artifact-001": "# Plan"},
    )
    with coordinator.acquire():
        result = coordinator.commit_candidate(txn, manifest_slot=1, plan_digest="plan")
    assert result.committed
    assert not (workspace / "implementation-plan.md").exists()
    assert render_decisions_dir(output_dir).is_dir()
