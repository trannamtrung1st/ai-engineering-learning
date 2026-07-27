"""Ownership ledger operations for progressive rendering."""

from __future__ import annotations

from top_down_planning.digest import digest_text
from top_down_planning.models import (
    ArtifactIntent,
    ArtifactLocation,
    ArtifactOperation,
    OwnershipChange,
    OwnershipLedger,
    OwnershipLedgerEntry,
    OwnershipLedgerEntryState,
    OwnerKind,
)


def new_ownership_ledger() -> OwnershipLedger:
    return OwnershipLedger()


def validate_ownership_claim(
    ledger: OwnershipLedger,
    artifact: ArtifactIntent,
) -> list[str]:
    errors: list[str] = []
    existing = ledger.artifacts.get(artifact.path)
    if artifact.operation == ArtifactOperation.CREATE:
        if existing and existing.state == OwnershipLedgerEntryState.ACTIVE:
            errors.append(f"path already owned: {artifact.path!r}")
        return errors
    if existing is None or existing.state != OwnershipLedgerEntryState.ACTIVE:
        errors.append(f"path not owned for update/delete: {artifact.path!r}")
        return errors
    if existing.owner_kind != artifact.owner_kind or existing.owner_id != artifact.owner_id:
        errors.append(
            f"unauthorized update to {artifact.path!r}: owned by "
            f"{existing.owner_kind.value}:{existing.owner_id}"
        )
    return errors


def validate_ownership_transfer(
    ledger: OwnershipLedger,
    change: OwnershipChange,
) -> list[str]:
    existing = ledger.artifacts.get(change.path)
    if existing is None or existing.state != OwnershipLedgerEntryState.ACTIVE:
        return [f"path not active for transfer: {change.path!r}"]
    if (
        existing.owner_kind != change.prior_owner_kind
        or existing.owner_id != change.prior_owner_id
    ):
        return [
            f"prior owner mismatch for {change.path!r}: expected "
            f"{change.prior_owner_kind.value}:{change.prior_owner_id}, got "
            f"{existing.owner_kind.value}:{existing.owner_id}"
        ]
    return []


def apply_artifact_intent(
    ledger: OwnershipLedger,
    artifact: ArtifactIntent,
    *,
    transaction_id: str,
    commit_sequence: int,
    content: str | None = None,
) -> OwnershipLedger:
    updated = ledger.model_copy(deep=True)
    if artifact.operation == ArtifactOperation.DELETE:
        entry = updated.artifacts.get(artifact.path)
        if entry is None:
            entry = OwnershipLedgerEntry(
                location=artifact.location,
                state=OwnershipLedgerEntryState.DELETED,
                owner_kind=artifact.owner_kind,
                owner_id=artifact.owner_id,
                artifact_key=artifact.artifact_key,
                prior_content_digest=artifact.prior_content_digest,
                last_transaction_id=transaction_id,
                commit_sequence=commit_sequence,
            )
        else:
            entry = entry.model_copy(
                update={
                    "state": OwnershipLedgerEntryState.DELETED,
                    "prior_content_digest": artifact.prior_content_digest
                    or entry.content_digest,
                    "content_digest": None,
                    "last_transaction_id": transaction_id,
                    "commit_sequence": commit_sequence,
                }
            )
        updated.artifacts[artifact.path] = entry
        return updated

    content_digest = artifact.content_digest
    if content_digest is None and content is not None:
        content_digest = digest_text(content)

    updated.artifacts[artifact.path] = OwnershipLedgerEntry(
        location=artifact.location,
        state=OwnershipLedgerEntryState.ACTIVE,
        owner_kind=artifact.owner_kind,
        owner_id=artifact.owner_id,
        artifact_key=artifact.artifact_key,
        content_digest=content_digest,
        last_transaction_id=transaction_id,
        commit_sequence=commit_sequence,
    )
    return updated


def apply_ownership_change(
    ledger: OwnershipLedger,
    change: OwnershipChange,
    *,
    transaction_id: str,
    commit_sequence: int,
) -> OwnershipLedger:
    updated = ledger.model_copy(deep=True)
    existing = updated.artifacts.get(change.path)
    if existing is None:
        return updated
    updated.artifacts[change.path] = existing.model_copy(
        update={
            "owner_kind": change.new_owner_kind,
            "owner_id": change.new_owner_id,
            "last_transaction_id": transaction_id,
            "commit_sequence": commit_sequence,
        }
    )
    return updated


def owned_paths_for_node(
    ledger: OwnershipLedger,
    node_id: str,
) -> list[str]:
    return sorted(
        path
        for path, entry in ledger.artifacts.items()
        if entry.state == OwnershipLedgerEntryState.ACTIVE
        and entry.owner_kind == OwnerKind.NODE
        and entry.owner_id == node_id
    )


def owned_paths_for_phase(
    ledger: OwnershipLedger,
    phase_id: str,
) -> list[str]:
    return sorted(
        path
        for path, entry in ledger.artifacts.items()
        if entry.state == OwnershipLedgerEntryState.ACTIVE
        and entry.owner_kind == OwnerKind.PHASE
        and entry.owner_id == phase_id
    )


def final_paths(ledger: OwnershipLedger) -> list[str]:
    return sorted(
        path
        for path, entry in ledger.artifacts.items()
        if entry.state == OwnershipLedgerEntryState.ACTIVE
        and entry.location == ArtifactLocation.FINAL
    )


def staged_paths(ledger: OwnershipLedger) -> list[str]:
    return sorted(
        path
        for path, entry in ledger.artifacts.items()
        if entry.state == OwnershipLedgerEntryState.ACTIVE
        and entry.location == ArtifactLocation.STAGED
    )
