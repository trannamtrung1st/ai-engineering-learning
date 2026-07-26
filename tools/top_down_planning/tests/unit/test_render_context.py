from pathlib import Path

import yaml

from top_down_planning.digest import compute_plan_digest
from top_down_planning.models import DecompositionStatus, RenderConfig
from top_down_planning.persistence import render_batch_transaction_path
from top_down_planning.render_context import prepare_render_batch_context
from top_down_planning.render_manifest import FINAL_BATCH_ID, build_render_manifest
from tests.helpers import render_output_goal
from tests.plan_factory import make_root_plan


def test_final_batch_context_lists_intermediate_inputs(tmp_path: Path) -> None:
    loaded_goal = render_output_goal()
    plan = make_root_plan(
        output_goal=loaded_goal.text,
        output_goal_digest=loaded_goal.digest,
    )
    plan.plan[0].decomposition_status = DecompositionStatus.ACTIONABLE
    manifest = build_render_manifest(
        plan,
        plan_digest=compute_plan_digest(plan),
        output_goal_digest=loaded_goal.digest,
        render_config=RenderConfig(),
    )
    intermediate = next(
        item for item in manifest.items if item.artifact_role == "intermediate"
    )
    txn_path = render_batch_transaction_path(tmp_path, intermediate.assigned_batch_id)
    txn_path.parent.mkdir(parents=True, exist_ok=True)
    txn_path.write_text(
        yaml.safe_dump(
            {
                "batch_id": intermediate.assigned_batch_id,
                "plan_digest": manifest.plan_digest,
                "output_goal_digest": manifest.output_goal_digest,
                "render_config_digest": manifest.render_config_digest,
                "artifacts": [
                    {
                        "plan_item_id": intermediate.plan_item_id,
                        "artifact_key": intermediate.artifact_key,
                        "relative_path": intermediate.relative_path,
                        "content": "Intermediate notes.\n",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    prepared = prepare_render_batch_context(
        plan=plan,
        manifest=manifest,
        assigned_items=[],
        output_dir=tmp_path,
        workspace=tmp_path,
        output_goal=loaded_goal,
        whole_plan_context=RenderConfig().whole_plan_context,
        embed_threshold=4000,
        batch_id=FINAL_BATCH_ID,
        manifest_digest="d" * 64,
    )

    assert "## Final deliverable synthesis" in prepared.batch_context_markdown
    assert "## Intermediate inputs" in prepared.batch_context_markdown
    assert intermediate.relative_path in prepared.batch_context_markdown
    assert "Intermediate batch transactions" in prepared.batch_context_markdown
