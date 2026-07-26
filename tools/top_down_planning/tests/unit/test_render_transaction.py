from top_down_planning.input_loader import load_output_goal
from top_down_planning.models import RenderBatchArtifact, RenderBatchTransaction, RenderConfig
from top_down_planning.render_manifest import FINAL_BATCH_ID, build_render_manifest
from top_down_planning.render_transaction import (
    validate_batch_transaction,
    validate_final_batch_transaction,
)
from tests.plan_factory import make_root_plan


def _final_transaction(*artifacts: RenderBatchArtifact) -> RenderBatchTransaction:
    return RenderBatchTransaction(
        batch_id=FINAL_BATCH_ID,
        plan_digest="a" * 64,
        output_goal_digest="b" * 64,
        render_config_digest="c" * 64,
        artifacts=list(artifacts),
    )


def test_final_batch_allows_empty_artifacts() -> None:
    transaction = _final_transaction()
    assert validate_final_batch_transaction(transaction) == []


def test_final_batch_rejects_unsafe_paths() -> None:
    transaction = _final_transaction(
        RenderBatchArtifact(
            plan_item_id="final-evil",
            artifact_key="final-evil",
            relative_path=".planning-output/plan.yaml",
            content="nope\n",
        )
    )
    errors = validate_final_batch_transaction(transaction)
    assert any(".planning-output" in error for error in errors)


def test_final_batch_rejects_duplicate_paths() -> None:
    transaction = _final_transaction(
        RenderBatchArtifact(
            plan_item_id="final-a",
            artifact_key="final-a",
            relative_path="plans/demo/a.md",
            content="a\n",
        ),
        RenderBatchArtifact(
            plan_item_id="final-b",
            artifact_key="final-b",
            relative_path="plans/demo/a.md",
            content="b\n",
        ),
    )
    errors = validate_final_batch_transaction(transaction)
    assert any("duplicate relative_path" in error for error in errors)


def test_validate_batch_transaction_routes_final_batch() -> None:
    loaded_goal = load_output_goal(inline="goal")
    plan = make_root_plan(
        output_goal=loaded_goal.text,
        output_goal_digest=loaded_goal.digest,
    )
    manifest = build_render_manifest(
        plan,
        plan_digest="a" * 64,
        output_goal_digest=loaded_goal.digest,
        render_config=RenderConfig(),
    )
    transaction = _final_transaction()
    errors = validate_batch_transaction(
        transaction,
        manifest=manifest,
        assigned_items=[],
        expected_batch_id=FINAL_BATCH_ID,
        expected_plan_digest="a" * 64,
        expected_output_goal_digest="b" * 64,
        expected_render_config_digest="c" * 64,
    )
    assert errors == []
