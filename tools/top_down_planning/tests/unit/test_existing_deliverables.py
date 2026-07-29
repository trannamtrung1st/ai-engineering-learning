from pathlib import Path

from top_down_planning.models import RenderStage, RenderState, RunState
from top_down_planning.render_deliverables import build_artifact_ignore_matcher, collect_deliverable_output
from top_down_planning.render_flow import existing_deliverable_artifacts


def test_existing_deliverables_rejects_digest_mismatch(tmp_path: Path) -> None:
    workspace = tmp_path
    output_dir = workspace / "planning-output"
    output_dir.mkdir()
    (workspace / "plan.md").write_text("# original\n", encoding="utf-8")
    matcher = build_artifact_ignore_matcher(workspace, output_dir, [])
    digest = collect_deliverable_output(workspace, ["plan.md"], matcher).digest
    render_state = RenderState(
        stage=RenderStage.COMPLETE,
        deliverable_output_digest=digest,
    )
    run_state = RunState(generated_artifacts=["plan.md"])

    assert existing_deliverable_artifacts(
        workspace,
        run_state,
        render_state,
        output_dir=output_dir,
        artifact_ignore_patterns=[],
    ) == [str(workspace / "plan.md")]

    (workspace / "plan.md").write_text("# changed\n", encoding="utf-8")
    assert existing_deliverable_artifacts(
        workspace,
        run_state,
        render_state,
        output_dir=output_dir,
        artifact_ignore_patterns=[],
    ) is None
