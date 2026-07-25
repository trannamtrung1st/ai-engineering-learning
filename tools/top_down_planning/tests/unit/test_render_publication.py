from top_down_planning.digest import compute_plan_digest
from top_down_planning.input_loader import load_output_goal
from top_down_planning.models import DecompositionStatus, OutputMode, RenderConfig
from top_down_planning.render_assembly import assemble_render_output
from top_down_planning.render_manifest import build_render_manifest
from top_down_planning.render_publication import publish_assembled_output
from tests.plan_factory import make_root_plan


def _multi_file_goal() -> str:
    return """# Goal

## Output artifacts

- `plans/demo/todos/INDEX.md`
- `plans/demo/todos/manifest.yaml`
- `plans/demo/todos/planning-summary.md`
"""


def test_manifest_assigns_set_order_and_publish_paths() -> None:
    loaded_goal = load_output_goal(inline=_multi_file_goal())
    plan = make_root_plan(
        output_goal=loaded_goal.text,
        output_goal_digest=loaded_goal.digest,
    )
    plan.plan[0].decomposition_status = DecompositionStatus.ACTIONABLE
    plan.plan.append(
        plan.plan[0].model_copy(
            update={
                "id": "item-002",
                "parent_id": "item-001",
                "title": "First leaf",
                "depth": 1,
                "order": 2,
                "decomposition_status": DecompositionStatus.ACTIONABLE,
            }
        )
    )
    plan_digest = compute_plan_digest(plan)
    manifest = build_render_manifest(
        plan,
        plan_digest=plan_digest,
        output_goal_digest=loaded_goal.digest,
        output_goal_text=loaded_goal.text,
        render_config=RenderConfig(),
    )
    assert manifest.output_mode == OutputMode.MULTI_FILE
    assert manifest.deliverable_root == "plans/demo/todos/"
    assert manifest.items[0].set_order == 1
    assert manifest.items[0].publish_relative_path == "01-first-leaf.yaml"
    assert manifest.items[0].relative_path == "items/002-first-leaf.yaml"


def test_assembly_synthesizes_declared_set_level_files(tmp_path) -> None:
    loaded_goal = load_output_goal(inline=_multi_file_goal())
    plan = make_root_plan(
        output_goal=loaded_goal.text,
        output_goal_digest=loaded_goal.digest,
    )
    plan.plan[0].decomposition_status = DecompositionStatus.ACTIONABLE
    plan_digest = compute_plan_digest(plan)
    manifest = build_render_manifest(
        plan,
        plan_digest=plan_digest,
        output_goal_digest=loaded_goal.digest,
        output_goal_text=loaded_goal.text,
        render_config=RenderConfig(),
    )
    item = manifest.items[0]
    from top_down_planning.models import RenderBatchArtifact, RenderBatchTransaction

    transaction = RenderBatchTransaction(
        batch_id=item.assigned_batch_id,
        plan_digest=plan_digest,
        output_goal_digest=loaded_goal.digest,
        render_config_digest=manifest.render_config_digest,
        artifacts=[
            RenderBatchArtifact(
                plan_item_id=item.plan_item_id,
                artifact_key=item.artifact_key,
                relative_path=item.relative_path,
                content=(
                    f"id: first-leaf\n"
                    f"title: {item.title}\n"
                    f"order: '{item.set_order:02d}'\n"
                ),
            )
        ],
    )
    assembled = assemble_render_output(
        manifest,
        {item.assigned_batch_id: transaction},
        plan_summary="Summary text",
    )
    assert "INDEX.md" in assembled.files
    assert "manifest.yaml" in assembled.files
    assert "planning-summary.md" in assembled.files
    assert ".internal/index.yaml" in assembled.files


def test_publication_writes_to_output_goal_root(tmp_path) -> None:
    workspace = tmp_path
    output_dir = workspace / "planning-output"
    output_dir.mkdir()
    loaded_goal = load_output_goal(inline=_multi_file_goal())
    plan = make_root_plan(
        output_goal=loaded_goal.text,
        output_goal_digest=loaded_goal.digest,
    )
    plan.plan[0].decomposition_status = DecompositionStatus.ACTIONABLE
    plan_digest = compute_plan_digest(plan)
    manifest = build_render_manifest(
        plan,
        plan_digest=plan_digest,
        output_goal_digest=loaded_goal.digest,
        output_goal_text=loaded_goal.text,
        render_config=RenderConfig(),
    )
    item = manifest.items[0]
    from top_down_planning.models import RenderBatchArtifact, RenderBatchTransaction

    transaction = RenderBatchTransaction(
        batch_id=item.assigned_batch_id,
        plan_digest=plan_digest,
        output_goal_digest=loaded_goal.digest,
        render_config_digest=manifest.render_config_digest,
        artifacts=[
            RenderBatchArtifact(
                plan_item_id=item.plan_item_id,
                artifact_key=item.artifact_key,
                relative_path=item.relative_path,
                content=(
                    f"id: first-leaf\n"
                    f"title: {item.title}\n"
                    f"order: '{item.set_order:02d}'\n"
                ),
            )
        ],
    )
    assembled = assemble_render_output(manifest, {item.assigned_batch_id: transaction})
    result = publish_assembled_output(
        output_dir=output_dir,
        workspace=workspace,
        assembled=assembled,
        manifest=manifest,
        previous_ledger=None,
    )
    published_leaf = workspace / "plans/demo/todos" / item.publish_relative_path
    published_index = workspace / "plans/demo/todos/INDEX.md"
    assert published_leaf.is_file()
    assert published_index.is_file()
    assert f"plans/demo/todos/{item.publish_relative_path}" in result.artifacts
    assert "plans/demo/todos/INDEX.md" in result.artifacts
