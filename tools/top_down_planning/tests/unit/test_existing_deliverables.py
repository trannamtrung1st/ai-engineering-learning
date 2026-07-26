from pathlib import Path

from top_down_planning.input_loader import load_output_goal
from top_down_planning.models import (
    DecompositionStatus,
    RenderBatchArtifact,
    RenderBatchTransaction,
    RenderConfig,
    RenderStage,
    RenderState,
    RunState,
)
from top_down_planning.render_deliverables import materialize_final_deliverables
from top_down_planning.render_flow import existing_deliverable_artifacts
from top_down_planning.render_manifest import (
    FINAL_BATCH_ID,
    apply_final_transaction_to_manifest,
    build_render_manifest,
)
from tests.plan_factory import make_root_plan


def test_existing_deliverables_rejects_digest_mismatch(tmp_path: Path) -> None:
    workspace = tmp_path
    loaded_goal = load_output_goal(inline="goal")
    plan = make_root_plan(
        output_goal=loaded_goal.text,
        output_goal_digest=loaded_goal.digest,
    )
    plan.plan[0].decomposition_status = DecompositionStatus.ACTIONABLE
    manifest = build_render_manifest(
        plan,
        plan_digest="a" * 64,
        output_goal_digest=loaded_goal.digest,
        render_config=RenderConfig(),
    )
    final_artifacts = [
        RenderBatchArtifact(
            plan_item_id="final-planmd",
            artifact_key="final-planmd",
            relative_path="plan.md",
            content="# original\n",
        )
    ]
    manifest = apply_final_transaction_to_manifest(
        manifest,
        RenderBatchTransaction(
            batch_id=FINAL_BATCH_ID,
            plan_digest="a" * 64,
            output_goal_digest=loaded_goal.digest,
            render_config_digest=manifest.render_config_digest,
            artifacts=final_artifacts,
        ),
    )
    materialize_final_deliverables(
        workspace,
        RenderBatchTransaction(
            batch_id=FINAL_BATCH_ID,
            plan_digest="a" * 64,
            output_goal_digest=loaded_goal.digest,
            render_config_digest=manifest.render_config_digest,
            artifacts=final_artifacts,
        ),
    )
    from top_down_planning.render_deliverables import collect_deliverable_output

    digest = collect_deliverable_output(workspace, manifest).digest
    render_state = RenderState(
        stage=RenderStage.COMPLETE,
        deliverable_output_digest=digest,
    )
    run_state = RunState(generated_artifacts=["plan.md"])

    assert existing_deliverable_artifacts(
        workspace,
        run_state,
        render_state,
        manifest=manifest,
    ) == [str(workspace / "plan.md")]

    (workspace / "plan.md").write_text("# changed\n", encoding="utf-8")
    assert existing_deliverable_artifacts(
        workspace,
        run_state,
        render_state,
        manifest=manifest,
    ) is None
