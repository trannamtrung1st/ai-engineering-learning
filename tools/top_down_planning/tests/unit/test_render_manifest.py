from top_down_planning.digest import compute_plan_digest
from top_down_planning.input_loader import load_output_goal
from top_down_planning.models import (
    DecompositionStatus,
    RenderBatchArtifact,
    RenderBatchStateEntry,
    RenderBatchStatus,
    RenderBatchTransaction,
    RenderConfig,
    RenderState,
)
from top_down_planning.render_flow import _expand_rerender_batch_ids
from top_down_planning.render_manifest import (
    FINAL_BATCH_ID,
    apply_final_transaction_to_manifest,
    build_render_manifest,
    manifest_finals_are_committed,
    manifest_is_valid,
    scheduled_batch_ids,
)
from tests.plan_factory import make_root_plan


def test_build_render_manifest_intermediates_only_for_one_line_goal() -> None:
    loaded_goal = load_output_goal(inline="Produce an actionable implementation plan")
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
    assert all(item.artifact_role == "intermediate" for item in manifest.items)
    assert FINAL_BATCH_ID in scheduled_batch_ids(manifest)
    assert manifest_is_valid(manifest)


def test_apply_final_transaction_adds_agent_declared_items() -> None:
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
    transaction = RenderBatchTransaction(
        batch_id=FINAL_BATCH_ID,
        plan_digest=plan_digest,
        output_goal_digest=loaded_goal.digest,
        render_config_digest=manifest.render_config_digest,
        artifacts=[
            RenderBatchArtifact(
                plan_item_id="final-indexmd",
                artifact_key="final-indexmd",
                relative_path="plans/demo/todos/INDEX.md",
                content="# Demo index\n",
            ),
            RenderBatchArtifact(
                plan_item_id="final-manifestyaml",
                artifact_key="final-manifestyaml",
                relative_path="plans/demo/todos/manifest.yaml",
                content="kind: implementation_todo_set\n",
            ),
        ],
    )
    updated = apply_final_transaction_to_manifest(manifest, transaction)
    final_items = [item for item in updated.items if item.artifact_role == "final"]
    assert len(final_items) == 2
    assert {item.relative_path for item in final_items} == {
        "plans/demo/todos/INDEX.md",
        "plans/demo/todos/manifest.yaml",
    }
    assert manifest_is_valid(updated)


def test_manifest_is_valid_rejects_stale_intermediate_roles() -> None:
    loaded_goal = load_output_goal(inline="goal")
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
    stale = manifest.model_copy(
        update={
            "items": [
                item.model_copy(update={"artifact_role": "leaf"})
                for item in manifest.items
            ]
        }
    )
    assert not manifest_is_valid(stale)


def test_manifest_finals_require_committed_final_batch() -> None:
    loaded_goal = load_output_goal(inline="goal")
    plan = make_root_plan(
        output_goal=loaded_goal.text,
        output_goal_digest=loaded_goal.digest,
    )
    plan.plan[0].decomposition_status = DecompositionStatus.ACTIONABLE
    plan_digest = compute_plan_digest(plan)
    base = build_render_manifest(
        plan,
        plan_digest=plan_digest,
        output_goal_digest=loaded_goal.digest,
        render_config=RenderConfig(),
    )
    stale = apply_final_transaction_to_manifest(
        base,
        RenderBatchTransaction(
            batch_id=FINAL_BATCH_ID,
            plan_digest=plan_digest,
            output_goal_digest=loaded_goal.digest,
            render_config_digest=base.render_config_digest,
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
    assert not manifest_finals_are_committed(stale, RenderState())
    render_state = RenderState(
        batches={
            FINAL_BATCH_ID: RenderBatchStateEntry(status=RenderBatchStatus.VALID)
        }
    )
    assert manifest_finals_are_committed(stale, render_state)


def test_expand_rerender_batch_ids_includes_final_when_intermediate_affected() -> None:
    loaded_goal = load_output_goal(inline="Produce a plan")
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
    intermediate = next(item for item in manifest.items if item.artifact_role == "intermediate")
    expanded = _expand_rerender_batch_ids({intermediate.assigned_batch_id}, manifest)
    assert FINAL_BATCH_ID in expanded

    final_only = _expand_rerender_batch_ids({FINAL_BATCH_ID}, manifest)
    assert final_only == {FINAL_BATCH_ID}
