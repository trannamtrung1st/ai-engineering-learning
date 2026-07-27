"""Unit tests for render decision validation."""

from __future__ import annotations

import pytest

from top_down_planning.models import (
    ArtifactIntent,
    ArtifactLocation,
    ArtifactOperation,
    DeferredTo,
    DeferredToKind,
    OwnerKind,
    RenderDecisionKind,
    RenderDecisionRecord,
    RenderNodePhase,
    RenderNodeTransaction,
)
from top_down_planning.render_decisions import (
    all_deferred_resolved,
    decision_id_for,
    validate_decision_record,
    validate_node_transaction,
)


def _sample_produce_decision() -> RenderDecisionRecord:
    return RenderDecisionRecord(
        run_id="run-1",
        decision_id=decision_id_for("item-001", RenderNodePhase.RENDER, 1),
        node_id="item-001",
        plan_digest="plan",
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
        committed_at="2026-01-01T00:00:00Z",
    )


def test_skip_requires_reason():
    decision = RenderDecisionRecord(
        run_id="run-1",
        decision_id="d1",
        node_id="item-001",
        plan_digest="plan",
        decision=RenderDecisionKind.SKIP,
    )
    assert "reason" in validate_decision_record(decision)[0]


def test_defer_requires_target():
    decision = RenderDecisionRecord(
        run_id="run-1",
        decision_id="d1",
        node_id="item-001",
        plan_digest="plan",
        decision=RenderDecisionKind.DEFER,
        reason="later",
    )
    assert "deferred_to" in validate_decision_record(decision)[0]


def test_produce_requires_artifacts():
    decision = RenderDecisionRecord(
        run_id="run-1",
        decision_id="d1",
        node_id="item-001",
        plan_digest="plan",
        decision=RenderDecisionKind.PRODUCE,
    )
    assert "at least one artifact" in validate_decision_record(decision)[0]


def test_node_transaction_validation():
    txn = RenderNodeTransaction(
        transaction_id="txn-1",
        node_id="item-001",
        context_digest="ctx",
        read_set_digest="ctx",
        plan_digest="plan",
        output_goal_digest="goal",
        render_config_digest="cfg",
        decision=RenderDecisionKind.SKIP,
        reason="not needed",
    )
    assert validate_node_transaction(txn) == []


def test_deferred_resolution():
    deferred = RenderDecisionRecord(
        run_id="run-1",
        decision_id="defer-1",
        node_id="item-001",
        plan_digest="plan",
        decision=RenderDecisionKind.DEFER,
        reason="child owns it",
        deferred_to=DeferredTo(
            kind=DeferredToKind.NODE,
            id="item-002",
            phase=RenderNodePhase.RENDER,
        ),
        committed_at="2026-01-01T00:00:00Z",
    )
    resolver = RenderDecisionRecord(
        run_id="run-1",
        decision_id="resolve-1",
        node_id="item-002",
        plan_digest="plan",
        decision=RenderDecisionKind.PRODUCE,
        resolves=["defer-1"],
        artifacts=[
            ArtifactIntent(
                artifact_key="artifact-002",
                path="backlog/item-002.md",
                location=ArtifactLocation.FINAL,
                operation=ArtifactOperation.CREATE,
                owner_kind=OwnerKind.NODE,
                owner_id="item-002",
            )
        ],
        committed_at="2026-01-01T00:00:00Z",
    )
    assert all_deferred_resolved([deferred, resolver]) == []


def test_deferred_to_phase_resolved_by_completion_record():
    from top_down_planning.models import PhaseCompletionRecord, PhaseStatus, PhaseType

    deferred = RenderDecisionRecord(
        run_id="run-1",
        decision_id="defer-phase-1",
        node_id="item-001",
        plan_digest="plan",
        decision=RenderDecisionKind.DEFER,
        reason="synthesis will own it",
        deferred_to=DeferredTo(kind=DeferredToKind.PHASE, id="final-index"),
        committed_at="2026-01-01T00:00:00Z",
    )
    completion = PhaseCompletionRecord(
        run_id="run-1",
        phase_id="final-index",
        phase_type=PhaseType.SYNTHESIS,
        status=PhaseStatus.COMMITTED,
        resolves=["defer-phase-1"],
        committed_at="2026-01-01T00:00:00Z",
    )
    assert all_deferred_resolved([deferred], phase_completions=[completion]) == []


def test_sample_produce_decision_valid():
    assert validate_decision_record(_sample_produce_decision()) == []
