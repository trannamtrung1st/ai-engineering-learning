from pathlib import Path

from top_down_planning.models import (
    ArtifactIntent,
    ArtifactLocation,
    ArtifactOperation,
    OwnerKind,
    OwnershipLedger,
    RenderDecisionKind,
    RenderNodeTransaction,
)
from top_down_planning.render_coordinator import RenderCoordinator
from top_down_planning.render_deliverables import (
    collect_deliverable_output_from_ledger,
    finalize_deliverables_from_ledger,
)


def _produce_transaction(path: str, content: str) -> RenderNodeTransaction:
    return RenderNodeTransaction(
        transaction_id="txn-item-001-render",
        node_id="item-001",
        context_digest="ctx",
        read_set_digest="ctx",
        plan_digest="a" * 64,
        output_goal_digest="b" * 64,
        render_config_digest="c" * 64,
        decision=RenderDecisionKind.PRODUCE,
        artifacts=[
            ArtifactIntent(
                artifact_key="artifact-001",
                path=path,
                location=ArtifactLocation.FINAL,
                operation=ArtifactOperation.CREATE,
                owner_kind=OwnerKind.NODE,
                owner_id="item-001",
            )
        ],
        staged_files={"artifact-001": content},
    )


def test_finalize_deliverables_from_ledger_records_workspace_files(tmp_path: Path) -> None:
    output_dir = tmp_path / "planning-output"
    output_dir.mkdir()
    workspace = tmp_path
    coordinator = RenderCoordinator(
        output_dir=output_dir,
        workspace=workspace,
        run_id="run-1",
        dry_run=False,
    )
    with coordinator.acquire():
        coordinator.commit_candidate(
            _produce_transaction("plan.md", "# Plan\n"),
            manifest_slot=1,
            plan_digest="a" * 64,
        )
    result = finalize_deliverables_from_ledger(
        output_dir=output_dir,
        ledger=coordinator._ledger,
        workspace=workspace,
    )
    assert result.artifacts == ["plan.md"]
    assert (workspace / "plan.md").read_text(encoding="utf-8") == "# Plan\n"


def test_collect_deliverable_output_from_ledger(tmp_path: Path) -> None:
    workspace = tmp_path
    (workspace / "plan.md").write_text("# Plan\n", encoding="utf-8")
    from top_down_planning.models import OwnershipLedgerEntry, OwnershipLedgerEntryState

    ledger = OwnershipLedger(
        artifacts={
            "plan.md": OwnershipLedgerEntry(
                location=ArtifactLocation.FINAL,
                state=OwnershipLedgerEntryState.ACTIVE,
                owner_kind=OwnerKind.NODE,
                owner_id="item-001",
                artifact_key="artifact-001",
            )
        }
    )
    collected = collect_deliverable_output_from_ledger(workspace, ledger)
    assert collected.files["plan.md"] == "# Plan\n"
