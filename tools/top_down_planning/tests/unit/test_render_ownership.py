"""Unit tests for render ownership ledger."""

from __future__ import annotations

from top_down_planning.models import (
    ArtifactIntent,
    ArtifactLocation,
    ArtifactOperation,
    OwnerKind,
    OwnershipChange,
)
from top_down_planning.render_ownership import (
    apply_artifact_intent,
    apply_ownership_change,
    new_ownership_ledger,
    validate_ownership_claim,
    validate_ownership_transfer,
)


def test_create_claim_on_empty_path():
    ledger = new_ownership_ledger()
    intent = ArtifactIntent(
        artifact_key="a1",
        path="backlog/a.md",
        location=ArtifactLocation.FINAL,
        operation=ArtifactOperation.CREATE,
        owner_kind=OwnerKind.NODE,
        owner_id="item-001",
    )
    assert validate_ownership_claim(ledger, intent) == []


def test_unauthorized_update_rejected():
    ledger = apply_artifact_intent(
        new_ownership_ledger(),
        ArtifactIntent(
            artifact_key="a1",
            path="backlog/a.md",
            location=ArtifactLocation.FINAL,
            operation=ArtifactOperation.CREATE,
            owner_kind=OwnerKind.NODE,
            owner_id="item-001",
        ),
        transaction_id="txn-1",
        commit_sequence=1,
        content="# A",
    )
    errors = validate_ownership_claim(
        ledger,
        ArtifactIntent(
            artifact_key="a1",
            path="backlog/a.md",
            location=ArtifactLocation.FINAL,
            operation=ArtifactOperation.UPDATE,
            owner_kind=OwnerKind.NODE,
            owner_id="item-002",
        ),
    )
    assert errors


def test_ownership_transfer():
    ledger = apply_artifact_intent(
        new_ownership_ledger(),
        ArtifactIntent(
            artifact_key="a1",
            path="backlog/a.md",
            location=ArtifactLocation.FINAL,
            operation=ArtifactOperation.CREATE,
            owner_kind=OwnerKind.NODE,
            owner_id="item-001",
        ),
        transaction_id="txn-1",
        commit_sequence=1,
        content="# A",
    )
    change = OwnershipChange(
        path="backlog/a.md",
        prior_owner_kind=OwnerKind.NODE,
        prior_owner_id="item-001",
        new_owner_kind=OwnerKind.PHASE,
        new_owner_id="final-index",
    )
    assert validate_ownership_transfer(ledger, change) == []
    updated = apply_ownership_change(
        ledger,
        change,
        transaction_id="txn-2",
        commit_sequence=2,
    )
    assert updated.artifacts["backlog/a.md"].owner_id == "final-index"
