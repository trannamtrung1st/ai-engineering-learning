from pathlib import Path

from top_down_planning.models import RenderStage, RenderState, RunState
from top_down_planning.render_deliverables import collect_deliverable_output
from top_down_planning.render_flow import existing_deliverable_artifacts


def test_existing_deliverables_rejects_digest_mismatch(tmp_path: Path) -> None:
    workspace = tmp_path
    (workspace / "plan.md").write_text("# original\n", encoding="utf-8")
    digest = collect_deliverable_output(workspace, ["plan.md"]).digest
    render_state = RenderState(
        stage=RenderStage.COMPLETE,
        deliverable_output_digest=digest,
    )
    run_state = RunState(generated_artifacts=["plan.md"])

    assert existing_deliverable_artifacts(
        workspace,
        run_state,
        render_state,
        output_dir=tmp_path / "out",
    ) == [str(workspace / "plan.md")]

    (workspace / "plan.md").write_text("# changed\n", encoding="utf-8")
    assert existing_deliverable_artifacts(
        workspace,
        run_state,
        render_state,
        output_dir=tmp_path / "out",
    ) is None
