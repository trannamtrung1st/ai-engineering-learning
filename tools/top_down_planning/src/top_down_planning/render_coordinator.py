"""Single-writer coordinator for progressive render publication."""

from __future__ import annotations

import asyncio
import fcntl
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from top_down_planning.digest import digest_text
from top_down_planning.models import (
    ArtifactLocation,
    ArtifactOperation,
    CommitJournalEntry,
    CommitJournalEntryStatus,
    CoordinatorState,
    OwnershipLedger,
    RenderDecisionKind,
    RenderDecisionRecord,
    RenderNodeTransaction,
)
from top_down_planning.paths import resolve_within_workspace, validate_relative_path
from top_down_planning.persistence import (
    append_commit_journal_entry,
    load_commit_journal,
    load_coordinator_state,
    load_ownership_ledger,
    render_staged_artifacts_dir,
    save_coordinator_state,
    save_ownership_ledger,
    save_render_decision,
)
from top_down_planning.render_decisions import decision_id_for, validate_node_transaction
from top_down_planning.render_ownership import (
    apply_artifact_intent,
    apply_ownership_change,
    new_ownership_ledger,
    validate_ownership_claim,
    validate_ownership_transfer,
)


_FORBIDDEN_PREFIXES = (".planning-output/", ".planning-output")


@dataclass
class CoordinatorResult:
    committed: bool
    decision_id: str | None = None
    commit_sequence: int | None = None
    errors: list[str] = field(default_factory=list)


class RenderCoordinator:
    """Serialize progressive render commits for one workspace."""

    def __init__(
        self,
        *,
        output_dir: Path,
        workspace: Path,
        run_id: str,
        dry_run: bool = False,
        allow_final_publication: bool = True,
        allow_staged_artifacts: bool = True,
    ) -> None:
        self.output_dir = output_dir.resolve()
        self.workspace = workspace.resolve()
        self.run_id = run_id
        self.dry_run = dry_run
        self.allow_final_publication = allow_final_publication
        self.allow_staged_artifacts = allow_staged_artifacts
        self._state = load_coordinator_state(output_dir) or CoordinatorState()
        self._ledger = load_ownership_ledger(output_dir) or new_ownership_ledger()
        self._commit_sequence = self._next_commit_sequence()
        self._lock_file: Path | None = None
        self._commit_lock = asyncio.Lock()

    def _next_commit_sequence(self) -> int:
        journal = load_commit_journal(self.output_dir)
        if not journal:
            return 1
        return max(entry.manifest_slot for entry in journal) + 1

    @contextmanager
    def acquire(self):
        lock_path = self.output_dir / ".coordinator.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = lock_path.open("w", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            self._state.workspace_generation += 1
            self._state.active_run_id = self.run_id
            save_coordinator_state(self.output_dir, self._state)
            self._lock_file = lock_path
            self.recover_journal()
            yield self
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    def freeze_for_review(self) -> None:
        self._state.frozen_for_review = True
        save_coordinator_state(self.output_dir, self._state)

    def unfreeze_after_review(self) -> None:
        self._state.frozen_for_review = False
        save_coordinator_state(self.output_dir, self._state)

    def validate_candidate(
        self,
        transaction: RenderNodeTransaction,
        *,
        manifest_slot: int,
    ) -> list[str]:
        if self._state.frozen_for_review:
            return ["coordinator is frozen for review"]
        errors = validate_node_transaction(transaction)
        errors.extend(_validate_paths(transaction, workspace=self.workspace))
        for artifact in transaction.artifacts:
            errors.extend(validate_ownership_claim(self._ledger, artifact))
            if artifact.location == ArtifactLocation.FINAL and not self.allow_final_publication:
                errors.append(f"final publication is disabled: {artifact.path!r}")
            if artifact.location == ArtifactLocation.STAGED and not self.allow_staged_artifacts:
                errors.append(f"staged artifacts are disabled: {artifact.path!r}")
        for change in transaction.ownership_changes:
            errors.extend(validate_ownership_transfer(self._ledger, change))
        if transaction.decision == RenderDecisionKind.PRODUCE:
            for artifact in transaction.artifacts:
                staged = transaction.staged_files.get(artifact.artifact_key)
                if staged is None and artifact.operation != ArtifactOperation.DELETE:
                    errors.append(
                        f"missing staged content for artifact_key {artifact.artifact_key!r}"
                    )
        if manifest_slot != self._commit_sequence:
            errors.append(
                f"manifest slot out of order: expected {self._commit_sequence}, got {manifest_slot}"
            )
        return errors

    async def commit_candidate_async(
        self,
        transaction: RenderNodeTransaction,
        *,
        manifest_slot: int,
        plan_digest: str,
    ) -> CoordinatorResult:
        async with self._commit_lock:
            return self.commit_candidate(
                transaction,
                manifest_slot=manifest_slot,
                plan_digest=plan_digest,
            )

    def commit_candidate(
        self,
        transaction: RenderNodeTransaction,
        *,
        manifest_slot: int,
        plan_digest: str,
    ) -> CoordinatorResult:
        errors = self.validate_candidate(transaction, manifest_slot=manifest_slot)
        if errors:
            return CoordinatorResult(committed=False, errors=errors)
        if transaction.decision is None:
            return CoordinatorResult(committed=False, errors=["missing decision"])

        decision_id = decision_id_for(
            transaction.node_id,
            transaction.phase,
            transaction.revision,
        )
        if self.dry_run:
            decision = _build_decision_record(
                transaction,
                run_id=self.run_id,
                decision_id=decision_id,
                plan_digest=plan_digest,
                commit_sequence=manifest_slot,
                committed_at=datetime.now(timezone.utc).isoformat(),
            )
            save_render_decision(self.output_dir, decision)
            self._commit_sequence = manifest_slot + 1
            return CoordinatorResult(
                committed=True,
                decision_id=decision_id,
                commit_sequence=manifest_slot,
            )

        journal_entry = CommitJournalEntry(
            transaction_id=transaction.transaction_id,
            manifest_slot=manifest_slot,
            node_id=transaction.node_id,
            status=CommitJournalEntryStatus.PREPARED,
            workspace_generation=self._state.workspace_generation,
            decision_id=decision_id,
            payload_digest=digest_text(transaction.model_dump_json()),
        )
        append_commit_journal_entry(self.output_dir, journal_entry)

        try:
            self._publish_transaction(transaction, commit_sequence=manifest_slot)
        except Exception as exc:
            journal_entry.status = CommitJournalEntryStatus.ABORTED
            append_commit_journal_entry(self.output_dir, journal_entry)
            return CoordinatorResult(committed=False, errors=[str(exc)])

        journal_entry.status = CommitJournalEntryStatus.COMMITTED
        journal_entry.published_paths = [
            artifact.path for artifact in transaction.artifacts
        ]
        append_commit_journal_entry(self.output_dir, journal_entry)

        decision = _build_decision_record(
            transaction,
            run_id=self.run_id,
            decision_id=decision_id,
            plan_digest=plan_digest,
            commit_sequence=manifest_slot,
            committed_at=datetime.now(timezone.utc).isoformat(),
        )
        save_render_decision(self.output_dir, decision)
        save_ownership_ledger(self.output_dir, self._ledger)
        self._commit_sequence = manifest_slot + 1
        return CoordinatorResult(
            committed=True,
            decision_id=decision_id,
            commit_sequence=manifest_slot,
        )

    def commit_failure_barrier(
        self,
        *,
        manifest_slot: int,
        node_id: str,
        reason: str,
    ) -> CoordinatorResult:
        """Advance manifest order after a terminal node failure without a semantic decision."""
        if manifest_slot != self._commit_sequence:
            return CoordinatorResult(
                committed=False,
                errors=[
                    f"manifest slot out of order: expected {self._commit_sequence}, got {manifest_slot}"
                ],
            )
        journal_entry = CommitJournalEntry(
            transaction_id=f"barrier-{node_id}-{manifest_slot}",
            manifest_slot=manifest_slot,
            node_id=node_id,
            status=CommitJournalEntryStatus.ABORTED,
            workspace_generation=self._state.workspace_generation,
            payload_digest=reason,
        )
        append_commit_journal_entry(self.output_dir, journal_entry)
        self._commit_sequence = manifest_slot + 1
        return CoordinatorResult(committed=True, commit_sequence=manifest_slot)

    def recover_journal(self) -> list[str]:
        recovered: list[str] = []
        for entry in load_commit_journal(self.output_dir):
            if entry.status not in {
                CommitJournalEntryStatus.PREPARED,
                CommitJournalEntryStatus.PUBLISHING,
            }:
                continue
            if entry.workspace_generation != self._state.workspace_generation:
                recovered.append(
                    f"stale journal entry {entry.transaction_id} rejected by fencing token"
                )
                continue
            recovered.append(f"recovered journal entry {entry.transaction_id}")
        return recovered

    def _publish_transaction(
        self,
        transaction: RenderNodeTransaction,
        *,
        commit_sequence: int,
    ) -> None:
        if self._state.frozen_for_review:
            raise RuntimeError("coordinator is frozen for review")
        if transaction.decision in {RenderDecisionKind.SKIP, RenderDecisionKind.DEFER}:
            return
        for artifact in transaction.artifacts:
            content = transaction.staged_files.get(artifact.artifact_key)
            if artifact.operation == ArtifactOperation.DELETE:
                destination = resolve_within_workspace(self.workspace, artifact.path)
                if destination.is_file():
                    destination.unlink()
            elif artifact.location == ArtifactLocation.FINAL:
                self._atomic_write_workspace(artifact.path, content or "")
            elif artifact.location == ArtifactLocation.STAGED:
                staged_root = render_staged_artifacts_dir(self.output_dir)
                staged_path = staged_root / artifact.path
                staged_path.parent.mkdir(parents=True, exist_ok=True)
                staged_path.write_text((content or "").rstrip() + "\n", encoding="utf-8")

            self._ledger = apply_artifact_intent(
                self._ledger,
                artifact,
                transaction_id=transaction.transaction_id,
                commit_sequence=commit_sequence,
                content=content,
            )
        for change in transaction.ownership_changes:
            self._ledger = apply_ownership_change(
                self._ledger,
                change,
                transaction_id=transaction.transaction_id,
                commit_sequence=commit_sequence,
            )

    def _atomic_write_workspace(self, relative_path: str, content: str) -> None:
        destination = resolve_within_workspace(self.workspace, relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=str(destination.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content.rstrip() + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, destination)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise


def _build_decision_record(
    transaction: RenderNodeTransaction,
    *,
    run_id: str,
    decision_id: str,
    plan_digest: str,
    commit_sequence: int | None,
    committed_at: str | None = None,
) -> RenderDecisionRecord:
    assert transaction.decision is not None
    return RenderDecisionRecord(
        run_id=run_id,
        decision_id=decision_id,
        node_id=transaction.node_id,
        phase=transaction.phase,
        revision=transaction.revision,
        plan_digest=plan_digest,
        decision=transaction.decision,
        reason=transaction.reason,
        deferred_to=transaction.deferred_to,
        resolves=list(transaction.resolves),
        context_digest=transaction.context_digest,
        read_set_digest=transaction.read_set_digest,
        commit_sequence=commit_sequence,
        artifacts=list(transaction.artifacts),
        ownership_changes=list(transaction.ownership_changes),
        committed_at=committed_at,
    )


def _validate_paths(transaction: RenderNodeTransaction, *, workspace: Path) -> list[str]:
    errors: list[str] = []
    for artifact in transaction.artifacts:
        try:
            normalized = validate_relative_path(artifact.path, label="path")
        except ValueError as exc:
            errors.append(str(exc))
            continue
        lowered = normalized.lower()
        for prefix in _FORBIDDEN_PREFIXES:
            if lowered == prefix.rstrip("/") or lowered.startswith(prefix):
                errors.append(f"path must not write into .planning-output: {artifact.path!r}")
                break
        if artifact.location == ArtifactLocation.FINAL:
            try:
                resolve_within_workspace(workspace, artifact.path)
            except ValueError as exc:
                errors.append(str(exc))
    return errors
