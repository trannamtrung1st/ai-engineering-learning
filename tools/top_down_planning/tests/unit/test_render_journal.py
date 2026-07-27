"""Unit tests for commit journal recovery."""

from __future__ import annotations

from pathlib import Path

from top_down_planning.models import CommitJournalEntry, CommitJournalEntryStatus
from top_down_planning.persistence import append_commit_journal_entry, load_commit_journal
from top_down_planning.render_coordinator import RenderCoordinator


def test_recover_journal_aborts_prepared_entries(tmp_path: Path) -> None:
    output_dir = tmp_path / "planning-output"
    output_dir.mkdir()
    append_commit_journal_entry(
        output_dir,
        CommitJournalEntry(
            transaction_id="txn-1",
            manifest_slot=1,
            node_id="item-001",
            status=CommitJournalEntryStatus.COMMITTED,
            workspace_generation=1,
        ),
    )
    append_commit_journal_entry(
        output_dir,
        CommitJournalEntry(
            transaction_id="txn-2",
            manifest_slot=2,
            node_id="item-002",
            status=CommitJournalEntryStatus.PREPARED,
            workspace_generation=2,
        ),
    )

    coordinator = RenderCoordinator(
        output_dir=output_dir,
        workspace=tmp_path,
        run_id="run-1",
    )
    with coordinator.acquire():
        assert coordinator._commit_sequence == 3
        journal = load_commit_journal(output_dir)
        assert journal[-1].status == CommitJournalEntryStatus.ABORTED
