from top_down_planning.digest import compute_plan_digest
from top_down_planning.input_loader import load_output_goal
from top_down_planning.models import DecompositionStatus, OutputMode, RenderConfig
from top_down_planning.render_assembly import assemble_render_output
from top_down_planning.render_manifest import SET_LEVEL_BATCH_ID, build_render_manifest
from top_down_planning.render_publication import publish_assembled_output
from tests.plan_factory import make_root_plan


def _multi_file_goal() -> str:
    return """# Goal

## Output artifacts

- `plans/demo/todos/INDEX.md`
- `plans/demo/todos/manifest.yaml`
- `plans/demo/todos/planning-summary.md`
"""


def _multi_file_goal_with_auxiliary() -> str:
    return """# Goal

Produce `tools/implement_todos` output.

## Output artifacts

```text
plans/demo/todos/
  manifest.yaml
  INDEX.md
```

```text
temp/tools/planning-summary.md
```
"""


def _leaf_transaction(plan_digest, loaded_goal, manifest, item):
    from top_down_planning.models import RenderBatchArtifact, RenderBatchTransaction

    return RenderBatchTransaction(
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
                    f"kind: implementation_todo_item\n"
                    f"id: first-leaf\n"
                    f"title: {item.title}\n"
                    f"order: '{item.set_order:02d}'\n"
                ),
            )
        ],
    )


def _set_level_transaction(plan_digest, loaded_goal, manifest, set_level_items):
    from top_down_planning.models import RenderBatchArtifact, RenderBatchTransaction

    return RenderBatchTransaction(
        batch_id=SET_LEVEL_BATCH_ID,
        plan_digest=plan_digest,
        output_goal_digest=loaded_goal.digest,
        render_config_digest=manifest.render_config_digest,
        artifacts=[
            RenderBatchArtifact(
                plan_item_id=item.plan_item_id,
                artifact_key=item.artifact_key,
                relative_path=item.relative_path,
                content=_set_level_content(item.relative_path or ""),
            )
            for item in set_level_items
        ],
    )


def _set_level_content(relative_path: str) -> str:
    if relative_path.endswith("manifest.yaml"):
        return "kind: implementation_todo_set\nid: demo-feature\ntitle: Demo\n"
    if relative_path.endswith("INDEX.md"):
        return "# Demo index\n"
    return "# Planning summary\n"


def test_manifest_assigns_set_order_publish_paths_and_set_level_batch() -> None:
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
    leaf_items = [item for item in manifest.items if item.artifact_role == "leaf"]
    set_level_items = [item for item in manifest.items if item.artifact_role == "set_level"]
    assert len(leaf_items) == 1
    assert {item.relative_path for item in set_level_items} == {
        "INDEX.md",
        "manifest.yaml",
        "planning-summary.md",
    }
    assert all(item.assigned_batch_id == SET_LEVEL_BATCH_ID for item in set_level_items)
    assert leaf_items[0].publish_relative_path == "01-first-leaf.yaml"


def test_assembly_uses_agent_rendered_set_level_files() -> None:
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
    leaf = next(item for item in manifest.items if item.artifact_role == "leaf")
    set_level_items = [item for item in manifest.items if item.artifact_role == "set_level"]
    transactions = {
        leaf.assigned_batch_id: _leaf_transaction(plan_digest, loaded_goal, manifest, leaf),
        SET_LEVEL_BATCH_ID: _set_level_transaction(
            plan_digest, loaded_goal, manifest, set_level_items
        ),
    }
    assembled = assemble_render_output(manifest, transactions)
    assert assembled.files["manifest.yaml"].startswith("kind: implementation_todo_set")
    assert assembled.files["INDEX.md"].startswith("# Demo index")
    assert "deliverable_root:" not in assembled.files["manifest.yaml"]


def test_auxiliary_artifacts_parsed_and_assigned_to_set_level_batch() -> None:
    loaded_goal = load_output_goal(inline=_multi_file_goal_with_auxiliary())
    from top_down_planning.output_goal_artifacts import parse_output_goal_artifacts

    artifacts = parse_output_goal_artifacts(loaded_goal.text)
    assert artifacts.auxiliary_artifacts == ["temp/tools/planning-summary.md"]

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
    auxiliary_items = [
        item
        for item in manifest.items
        if item.relative_path == "temp/tools/planning-summary.md"
    ]
    assert len(auxiliary_items) == 1
    assert auxiliary_items[0].assigned_batch_id == SET_LEVEL_BATCH_ID


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
    leaf = next(item for item in manifest.items if item.artifact_role == "leaf")
    set_level_items = [item for item in manifest.items if item.artifact_role == "set_level"]
    assembled = assemble_render_output(
        manifest,
        {
            leaf.assigned_batch_id: _leaf_transaction(plan_digest, loaded_goal, manifest, leaf),
            SET_LEVEL_BATCH_ID: _set_level_transaction(
                plan_digest, loaded_goal, manifest, set_level_items
            ),
        },
    )
    result = publish_assembled_output(
        output_dir=output_dir,
        workspace=workspace,
        assembled=assembled,
        manifest=manifest,
        previous_ledger=None,
    )
    published_leaf = workspace / "plans/demo/todos" / leaf.publish_relative_path
    published_index = workspace / "plans/demo/todos/INDEX.md"
    assert published_leaf.is_file()
    assert published_index.is_file()
    assert f"plans/demo/todos/{leaf.publish_relative_path}" in result.artifacts
    assert "plans/demo/todos/INDEX.md" in result.artifacts


def test_publication_writes_auxiliary_artifacts(tmp_path) -> None:
    workspace = tmp_path
    output_dir = workspace / "planning-output"
    output_dir.mkdir()
    loaded_goal = load_output_goal(inline=_multi_file_goal_with_auxiliary())
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
    leaf = next(item for item in manifest.items if item.artifact_role == "leaf")
    set_level_items = [item for item in manifest.items if item.artifact_role == "set_level"]
    assembled = assemble_render_output(
        manifest,
        {
            leaf.assigned_batch_id: _leaf_transaction(plan_digest, loaded_goal, manifest, leaf),
            SET_LEVEL_BATCH_ID: _set_level_transaction(
                plan_digest, loaded_goal, manifest, set_level_items
            ),
        },
    )
    result = publish_assembled_output(
        output_dir=output_dir,
        workspace=workspace,
        assembled=assembled,
        manifest=manifest,
        previous_ledger=None,
    )
    published_summary = workspace / "temp/tools/planning-summary.md"
    assert published_summary.is_file()
    assert "temp/tools/planning-summary.md" in result.artifacts
