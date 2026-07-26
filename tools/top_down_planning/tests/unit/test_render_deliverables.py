from top_down_planning.digest import compute_plan_digest
from top_down_planning.input_loader import load_output_goal
from top_down_planning.models import (
    DecompositionStatus,
    OutputMode,
    RenderBatchArtifact,
    RenderBatchTransaction,
    RenderConfig,
)
from top_down_planning.render_assembly import assemble_render_output
from top_down_planning.render_manifest import (
    FINAL_BATCH_ID,
    apply_final_transaction_to_manifest,
    build_render_manifest,
)
from top_down_planning.render_deliverables import (
    collect_deliverable_output,
    finalize_deliverables,
    materialize_final_deliverables,
)
from top_down_planning.render_manifest import strip_final_items_from_manifest
from tests.plan_factory import make_root_plan


def _intermediate_transaction(plan_digest, loaded_goal, manifest, item):
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
                content=f"Notes and partials for {item.title}.\n",
            )
        ],
    )


def _agent_final_transaction(plan_digest, loaded_goal, manifest, artifacts):
    return RenderBatchTransaction(
        batch_id=FINAL_BATCH_ID,
        plan_digest=plan_digest,
        output_goal_digest=loaded_goal.digest,
        render_config_digest=manifest.render_config_digest,
        artifacts=artifacts,
    )


def _manifest_with_agent_finals(base_manifest, plan_digest, loaded_goal, artifacts):
    transaction = _agent_final_transaction(plan_digest, loaded_goal, base_manifest, artifacts)
    return apply_final_transaction_to_manifest(base_manifest, transaction)


def test_manifest_schedules_intermediates_and_final_batch() -> None:
    loaded_goal = load_output_goal(
        inline="""Produce TODO folder.

## Output artifacts

- `plans/demo/todos/INDEX.md`
- `plans/demo/todos/manifest.yaml`
"""
    )
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
    manifest = build_render_manifest(
        plan,
        plan_digest=compute_plan_digest(plan),
        output_goal_digest=loaded_goal.digest,
        render_config=RenderConfig(),
    )
    intermediate_items = [
        item for item in manifest.items if item.artifact_role == "intermediate"
    ]
    assert len(intermediate_items) == 1
    assert intermediate_items[0].relative_path.startswith("intermediates/")
    assert not any(item.artifact_role == "final" for item in manifest.items)


def test_assembly_includes_intermediates_only() -> None:
    loaded_goal = load_output_goal(inline="Produce TODO output")
    plan = make_root_plan(
        output_goal=loaded_goal.text,
        output_goal_digest=loaded_goal.digest,
    )
    plan.plan[0].decomposition_status = DecompositionStatus.ACTIONABLE
    plan_digest = compute_plan_digest(plan)
    base_manifest = build_render_manifest(
        plan,
        plan_digest=plan_digest,
        output_goal_digest=loaded_goal.digest,
        render_config=RenderConfig(),
    )
    intermediate = next(
        item for item in base_manifest.items if item.artifact_role == "intermediate"
    )
    final_artifacts = [
        RenderBatchArtifact(
            plan_item_id="final-manifestyaml",
            artifact_key="final-manifestyaml",
            relative_path="plans/demo/todos/manifest.yaml",
            content="kind: implementation_todo_set\nid: demo-feature\ntitle: Demo\n",
        ),
        RenderBatchArtifact(
            plan_item_id="final-indexmd",
            artifact_key="final-indexmd",
            relative_path="plans/demo/todos/INDEX.md",
            content="# Demo index\n",
        ),
    ]
    manifest = _manifest_with_agent_finals(
        base_manifest, plan_digest, loaded_goal, final_artifacts
    )
    transactions = {
        intermediate.assigned_batch_id: _intermediate_transaction(
            plan_digest, loaded_goal, manifest, intermediate
        ),
        FINAL_BATCH_ID: _agent_final_transaction(
            plan_digest, loaded_goal, manifest, final_artifacts
        ),
    }
    assembled = assemble_render_output(manifest, transactions)
    assert intermediate.relative_path in assembled.files
    assert "plans/demo/todos/manifest.yaml" not in assembled.files
    assert "plans/demo/todos/INDEX.md" not in assembled.files


def test_finalize_deliverables_records_workspace_files(tmp_path) -> None:
    workspace = tmp_path
    output_dir = workspace / "planning-output"
    output_dir.mkdir()
    loaded_goal = load_output_goal(inline="Produce TODO output")
    plan = make_root_plan(
        output_goal=loaded_goal.text,
        output_goal_digest=loaded_goal.digest,
    )
    plan.plan[0].decomposition_status = DecompositionStatus.ACTIONABLE
    plan_digest = compute_plan_digest(plan)
    base_manifest = build_render_manifest(
        plan,
        plan_digest=plan_digest,
        output_goal_digest=loaded_goal.digest,
        render_config=RenderConfig(),
    )
    intermediate = next(
        item for item in base_manifest.items if item.artifact_role == "intermediate"
    )
    final_artifacts = [
        RenderBatchArtifact(
            plan_item_id="final-indexmd",
            artifact_key="final-indexmd",
            relative_path="plans/demo/todos/INDEX.md",
            content="# Demo index\n",
        )
    ]
    manifest = _manifest_with_agent_finals(
        base_manifest, plan_digest, loaded_goal, final_artifacts
    )
    final_txn = _agent_final_transaction(
        plan_digest, loaded_goal, manifest, final_artifacts
    )
    materialize_final_deliverables(workspace, final_txn)
    result = finalize_deliverables(
        output_dir=output_dir,
        workspace=workspace,
        manifest=manifest,
        previous_ledger=None,
    )
    deliverable_index = workspace / "plans/demo/todos/INDEX.md"
    assert deliverable_index.is_file()
    assert "plans/demo/todos/INDEX.md" in result.artifacts
    assert intermediate.relative_path not in result.artifacts


def test_finalize_deliverables_allows_empty_deliverables(tmp_path) -> None:
    workspace = tmp_path
    output_dir = workspace / "planning-output"
    output_dir.mkdir()
    loaded_goal = load_output_goal(inline="Produce an actionable implementation plan")
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
        render_config=RenderConfig(),
    )
    intermediate = next(
        item for item in manifest.items if item.artifact_role == "intermediate"
    )
    transactions = {
        intermediate.assigned_batch_id: _intermediate_transaction(
            plan_digest, loaded_goal, manifest, intermediate
        ),
        FINAL_BATCH_ID: RenderBatchTransaction(
            batch_id=FINAL_BATCH_ID,
            plan_digest=plan_digest,
            output_goal_digest=loaded_goal.digest,
            render_config_digest=manifest.render_config_digest,
            artifacts=[],
        ),
    }
    result = finalize_deliverables(
        output_dir=output_dir,
        workspace=workspace,
        manifest=manifest,
        previous_ledger=None,
    )
    assert result.artifacts == []


def test_apply_final_transaction_sets_multi_file_metadata() -> None:
    loaded_goal = load_output_goal(inline="goal")
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
        render_config=RenderConfig(),
    )
    updated = apply_final_transaction_to_manifest(
        manifest,
        RenderBatchTransaction(
            batch_id=FINAL_BATCH_ID,
            plan_digest=plan_digest,
            output_goal_digest=loaded_goal.digest,
            render_config_digest=manifest.render_config_digest,
            artifacts=[
                RenderBatchArtifact(
                    plan_item_id="final-indexmd",
                    artifact_key="final-indexmd",
                    relative_path="plans/demo/todos/INDEX.md",
                    content="# index\n",
                ),
                RenderBatchArtifact(
                    plan_item_id="final-summarymd",
                    artifact_key="final-summarymd",
                    relative_path="temp/tools/planning-summary.md",
                    content="# summary\n",
                ),
            ],
        ),
    )
    assert updated.output_mode == OutputMode.MULTI_FILE
    assert updated.deliverable_root is None


def test_finalize_digest_matches_collect(tmp_path) -> None:
    workspace = tmp_path
    output_dir = workspace / "planning-output"
    output_dir.mkdir()
    loaded_goal = load_output_goal(inline="Produce TODO output")
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
        render_config=RenderConfig(),
    )
    final_artifacts = [
        RenderBatchArtifact(
            plan_item_id="final-indexmd",
            artifact_key="final-indexmd",
            relative_path="plans/demo/todos/INDEX.md",
            content="# Demo index\n",
        )
    ]
    manifest = apply_final_transaction_to_manifest(
        manifest,
        RenderBatchTransaction(
            batch_id=FINAL_BATCH_ID,
            plan_digest=plan_digest,
            output_goal_digest=loaded_goal.digest,
            render_config_digest=manifest.render_config_digest,
            artifacts=final_artifacts,
        ),
    )
    materialize_final_deliverables(
        workspace,
        RenderBatchTransaction(
            batch_id=FINAL_BATCH_ID,
            plan_digest=plan_digest,
            output_goal_digest=loaded_goal.digest,
            render_config_digest=manifest.render_config_digest,
            artifacts=final_artifacts,
        ),
    )
    collected = collect_deliverable_output(workspace, manifest)
    result = finalize_deliverables(
        output_dir=output_dir,
        workspace=workspace,
        manifest=manifest,
        previous_ledger=None,
    )
    assert result.deliverable_digest == collected.digest


def test_strip_final_items_from_manifest() -> None:
    loaded_goal = load_output_goal(inline="goal")
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
        render_config=RenderConfig(),
    )
    with_finals = apply_final_transaction_to_manifest(
        manifest,
        RenderBatchTransaction(
            batch_id=FINAL_BATCH_ID,
            plan_digest=plan_digest,
            output_goal_digest=loaded_goal.digest,
            render_config_digest=manifest.render_config_digest,
            artifacts=[
                RenderBatchArtifact(
                    plan_item_id="final-planmd",
                    artifact_key="final-planmd",
                    relative_path="plan.md",
                    content="# plan\n",
                )
            ],
        ),
    )
    stripped = strip_final_items_from_manifest(with_finals)
    assert all(item.artifact_role == "intermediate" for item in stripped.items)
    assert stripped.deliverable_root is None
