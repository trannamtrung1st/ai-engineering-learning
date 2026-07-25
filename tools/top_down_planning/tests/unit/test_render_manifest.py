from top_down_planning.digest import compute_plan_digest
from top_down_planning.input_loader import load_output_goal
from top_down_planning.models import DecompositionStatus, RenderConfig
from top_down_planning.render_manifest import build_render_manifest, manifest_matches_output_goal
from tests.plan_factory import make_root_plan


def test_manifest_matches_output_goal_requires_set_level_items() -> None:
    goal = """# Goal

## Output artifacts

- `plans/demo/todos/INDEX.md`
- `plans/demo/todos/manifest.yaml`
"""
    loaded_goal = load_output_goal(inline=goal)
    plan = make_root_plan(
        output_goal=loaded_goal.text,
        output_goal_digest=loaded_goal.digest,
    )
    plan.plan[0].decomposition_status = DecompositionStatus.ACTIONABLE
    manifest = build_render_manifest(
        plan,
        plan_digest=compute_plan_digest(plan),
        output_goal_digest=loaded_goal.digest,
        output_goal_text=loaded_goal.text,
        render_config=RenderConfig(),
    )
    assert manifest_matches_output_goal(manifest, loaded_goal.text)

    stale_manifest = manifest.model_copy(
        update={
            "items": [item for item in manifest.items if item.artifact_role == "leaf"]
        }
    )
    assert not manifest_matches_output_goal(stale_manifest, loaded_goal.text)
