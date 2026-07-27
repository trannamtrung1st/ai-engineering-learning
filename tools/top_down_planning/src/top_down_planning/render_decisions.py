"""Validation and helpers for structured render decisions."""

from __future__ import annotations

from dataclasses import dataclass

from top_down_planning.models import (
    PhaseCompletionRecord,
    PhaseStatus,
    ArtifactIntent,
    DeferredTo,
    DeferredToKind,
    RenderDecisionKind,
    RenderDecisionRecord,
    RenderNodePhase,
    RenderNodeTransaction,
)


def validate_decision_record(decision: RenderDecisionRecord) -> list[str]:
    errors: list[str] = []
    if decision.decision in {RenderDecisionKind.SKIP, RenderDecisionKind.DEFER}:
        if not decision.reason.strip():
            errors.append(f"decision {decision.decision.value} requires a reason")
    if decision.decision == RenderDecisionKind.DEFER:
        if decision.deferred_to is None:
            errors.append("defer requires deferred_to")
        else:
            errors.extend(_validate_deferred_to(decision.deferred_to))
    if decision.decision == RenderDecisionKind.PRODUCE:
        if not decision.artifacts:
            errors.append("produce requires at least one artifact")
    if decision.decision in {RenderDecisionKind.SKIP, RenderDecisionKind.DEFER}:
        if decision.artifacts:
            errors.append(f"{decision.decision.value} must not declare artifacts")
    return errors


def validate_node_transaction(transaction: RenderNodeTransaction) -> list[str]:
    errors: list[str] = []
    if transaction.decision is None:
        errors.append("node transaction must record a decision")
        return errors
    if transaction.decision in {RenderDecisionKind.SKIP, RenderDecisionKind.DEFER}:
        if not transaction.reason.strip():
            errors.append(f"decision {transaction.decision.value} requires a reason")
    if transaction.decision == RenderDecisionKind.DEFER:
        if transaction.deferred_to is None:
            errors.append("defer requires deferred_to")
        else:
            errors.extend(_validate_deferred_to(transaction.deferred_to))
    if transaction.decision == RenderDecisionKind.PRODUCE:
        if not transaction.artifacts:
            errors.append("produce requires at least one artifact")
    if transaction.decision in {RenderDecisionKind.SKIP, RenderDecisionKind.DEFER}:
        if transaction.artifacts:
            errors.append(f"{transaction.decision.value} must not declare artifacts")
    for artifact in transaction.artifacts:
        errors.extend(_validate_artifact_intent(artifact))
    return errors


def _validate_deferred_to(target: DeferredTo) -> list[str]:
    errors: list[str] = []
    if not target.id.strip():
        errors.append("deferred_to.id is required")
    if target.kind == DeferredToKind.NODE and target.phase is None:
        errors.append("deferred_to.phase is required for node targets")
    if target.kind == DeferredToKind.PHASE and target.phase is not None:
        errors.append("deferred_to.phase must be omitted for phase targets")
    return errors


def _validate_artifact_intent(artifact: ArtifactIntent) -> list[str]:
    errors: list[str] = []
    if not artifact.artifact_key.strip():
        errors.append("artifact_key is required")
    if not artifact.path.strip():
        errors.append("artifact path is required")
    if artifact.operation.value == "delete":
        if artifact.content_digest is not None:
            errors.append("delete operations must omit content_digest")
        if artifact.prior_content_digest is None:
            errors.append("delete operations require prior_content_digest")
    return errors


def decision_id_for(node_id: str, phase: RenderNodePhase, revision: int) -> str:
    return f"decision-{node_id}-{phase.value}-r{revision}"


def deferred_resolved(
    deferred: RenderDecisionRecord,
    resolver: RenderDecisionRecord | None,
    *,
    phase_completions: list[PhaseCompletionRecord] | None = None,
) -> bool:
    if deferred.decision != RenderDecisionKind.DEFER or deferred.deferred_to is None:
        return True
    target = deferred.deferred_to
    if target.kind == DeferredToKind.PHASE:
        for completion in phase_completions or []:
            if (
                completion.phase_id == target.id
                and completion.status == PhaseStatus.COMMITTED
                and deferred.decision_id in completion.resolves
            ):
                return True
        return False
    if resolver is None:
        return False
    if deferred.decision_id not in resolver.resolves:
        return False
    if target.kind == DeferredToKind.NODE:
        return resolver.node_id == target.id and resolver.phase == target.phase
    return False


def all_deferred_resolved(
    decisions: list[RenderDecisionRecord],
    *,
    phase_completions: list[PhaseCompletionRecord] | None = None,
) -> list[str]:
    """Return unresolved deferred decision IDs."""
    current = {
        d.decision_id: d
        for d in decisions
        if d.committed_at or d.commit_sequence is not None
    }
    deferred = [
        d
        for d in decisions
        if d.decision == RenderDecisionKind.DEFER
        and (d.committed_at or d.commit_sequence is not None)
    ]
    unresolved: list[str] = []
    for decision in deferred:
        if decision.deferred_to is None:
            unresolved.append(decision.decision_id)
            continue
        if decision.deferred_to.kind == DeferredToKind.PHASE:
            resolved = deferred_resolved(
                decision,
                None,
                phase_completions=phase_completions,
            )
        else:
            resolved = any(
                deferred_resolved(decision, resolver, phase_completions=phase_completions)
                for resolver in current.values()
                if decision.decision_id in resolver.resolves
            )
        if not resolved:
            unresolved.append(decision.decision_id)
    return unresolved
