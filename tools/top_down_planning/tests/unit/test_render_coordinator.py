"""Unit tests for progressive render coordinator."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.models import (
    ArtifactIntent,
    ArtifactLocation,
    ArtifactOperation,
    OwnerKind,
    RenderDecisionKind,
    RenderNodePhase,
    RenderNodeTransaction,
)
from top_down_planning.render_coordinator import RenderCoordinator


@pytest.fixture
def coordinator_dirs(tmp_path: Path):
    output_dir = tmp_path / "planning-output"
    output_dir.mkdir(parents=True)
    workspace = tmp_path
    return output_dir, workspace


def test_dry_run_commits_decision_without_workspace_write(
    coordinator_dirs: tuple[Path, Path],
):
    output_dir, workspace = coordinator_dirs
    coordinator = RenderCoordinator(
        output_dir=output_dir,
        workspace=workspace,
        run_id="run-1",
        dry_run=True,
    )
    txn = RenderNodeTransaction(
        transaction_id="txn-item-001-render",
        node_id="item-001",
        context_digest="ctx",
        read_set_digest="ctx",
        plan_digest="plan",
        output_goal_digest="goal",
        render_config_digest="cfg",
        decision=RenderDecisionKind.PRODUCE,
        artifacts=[
            ArtifactIntent(
                artifact_key="artifact-001",
                path="backlog/item-001.md",
                location=ArtifactLocation.FINAL,
                operation=ArtifactOperation.CREATE,
                owner_kind=OwnerKind.NODE,
                owner_id="item-001",
            )
        ],
        staged_files={"artifact-001": "# Item 001"},
    )
    with coordinator.acquire():
        result = coordinator.commit_candidate(txn, manifest_slot=1, plan_digest="plan")
    assert result.committed
    assert not (workspace / "backlog/item-001.md").exists()


def test_render_mode_publishes_final_artifact(coordinator_dirs: tuple[Path, Path]):
    output_dir, workspace = coordinator_dirs
    coordinator = RenderCoordinator(
        output_dir=output_dir,
        workspace=workspace,
        run_id="run-1",
        dry_run=False,
    )
    txn = RenderNodeTransaction(
        transaction_id="txn-item-001-render",
        node_id="item-001",
        phase=RenderNodePhase.RENDER,
        context_digest="ctx",
        read_set_digest="ctx",
        plan_digest="plan",
        output_goal_digest="goal",
        render_config_digest="cfg",
        decision=RenderDecisionKind.PRODUCE,
        artifacts=[
            ArtifactIntent(
                artifact_key="artifact-001",
                path="backlog/item-001.md",
                location=ArtifactLocation.FINAL,
                operation=ArtifactOperation.CREATE,
                owner_kind=OwnerKind.NODE,
                owner_id="item-001",
            )
        ],
        staged_files={"artifact-001": "# Item 001"},
    )
    with coordinator.acquire():
        result = coordinator.commit_candidate(txn, manifest_slot=1, plan_digest="plan")
    assert result.committed
    assert (workspace / "backlog/item-001.md").read_text(encoding="utf-8") == "# Item 001\n"


def test_skip_decision_commits_without_artifacts(coordinator_dirs: tuple[Path, Path]):
    output_dir, workspace = coordinator_dirs
    coordinator = RenderCoordinator(
        output_dir=output_dir,
        workspace=workspace,
        run_id="run-1",
        dry_run=True,
    )
    txn = RenderNodeTransaction(
        transaction_id="txn-item-003-render",
        node_id="item-003",
        context_digest="ctx",
        read_set_digest="ctx",
        plan_digest="plan",
        output_goal_digest="goal",
        render_config_digest="cfg",
        decision=RenderDecisionKind.SKIP,
        reason="blocked",
    )
    with coordinator.acquire():
        result = coordinator.commit_candidate(txn, manifest_slot=1, plan_digest="plan")
    assert result.committed


def test_commit_failure_barrier_advances_manifest_slot(
    coordinator_dirs: tuple[Path, Path],
):
    output_dir, workspace = coordinator_dirs
    coordinator = RenderCoordinator(
        output_dir=output_dir,
        workspace=workspace,
        run_id="run-1",
        dry_run=True,
    )
    with coordinator.acquire():
        result = coordinator.commit_failure_barrier(
            manifest_slot=1,
            node_id="item-001",
            reason="dependency_failed",
        )
        assert result.committed
        assert coordinator._commit_sequence == 2


def test_rejects_final_publication_when_disabled(
    coordinator_dirs: tuple[Path, Path],
):
    output_dir, workspace = coordinator_dirs
    coordinator = RenderCoordinator(
        output_dir=output_dir,
        workspace=workspace,
        run_id="run-1",
        allow_final_publication=False,
    )
    txn = RenderNodeTransaction(
        transaction_id="txn-item-001-render",
        node_id="item-001",
        context_digest="ctx",
        read_set_digest="ctx",
        plan_digest="plan",
        output_goal_digest="goal",
        render_config_digest="cfg",
        decision=RenderDecisionKind.PRODUCE,
        artifacts=[
            ArtifactIntent(
                artifact_key="artifact-001",
                path="plan.md",
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
    assert not result.committed
    assert any("final publication is disabled" in error for error in result.errors)


@pytest.mark.asyncio
async def test_manifest_slots_commit_in_order(coordinator_dirs: tuple[Path, Path]):
    output_dir, workspace = coordinator_dirs
    coordinator = RenderCoordinator(
        output_dir=output_dir,
        workspace=workspace,
        run_id="run-1",
        dry_run=True,
    )

    def _skip_txn(node_id: str) -> RenderNodeTransaction:
        return RenderNodeTransaction(
            transaction_id=f"txn-{node_id}-render",
            node_id=node_id,
            context_digest="ctx",
            read_set_digest="ctx",
            plan_digest="plan",
            output_goal_digest="goal",
            render_config_digest="cfg",
            decision=RenderDecisionKind.SKIP,
            reason="not needed",
        )

    with coordinator.acquire():
        second = await coordinator.commit_candidate_async(
            _skip_txn("item-002"),
            manifest_slot=2,
            plan_digest="plan",
        )
        assert not second.committed
        assert any("out of order" in error for error in second.errors)

        first = await coordinator.commit_candidate_async(
            _skip_txn("item-001"),
            manifest_slot=1,
            plan_digest="plan",
        )
        assert first.committed
        second = await coordinator.commit_candidate_async(
            _skip_txn("item-002"),
            manifest_slot=2,
            plan_digest="plan",
        )
        assert second.committed
