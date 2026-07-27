from top_down_planning.models import (
    ArtifactIntent,
    ArtifactLocation,
    ArtifactOperation,
    OwnerKind,
    RenderDecisionKind,
    RenderNodeTransaction,
)
from top_down_planning.render_transaction import validate_node_render_transaction


def _node_transaction(**overrides) -> RenderNodeTransaction:
    payload = {
        "transaction_id": "txn-item-001-render",
        "node_id": "item-001",
        "context_digest": "ctx",
        "read_set_digest": "ctx",
        "plan_digest": "a" * 64,
        "output_goal_digest": "b" * 64,
        "render_config_digest": "c" * 64,
        "decision": RenderDecisionKind.SKIP,
        "reason": "not needed",
    }
    payload.update(overrides)
    return RenderNodeTransaction(**payload)


def test_validate_node_render_transaction_accepts_skip() -> None:
    transaction = _node_transaction()
    errors = validate_node_render_transaction(
        transaction,
        expected_node_id="item-001",
        expected_plan_digest="a" * 64,
        expected_output_goal_digest="b" * 64,
        expected_render_config_digest="c" * 64,
        expected_context_digest="ctx",
    )
    assert errors == []


def test_validate_node_render_transaction_rejects_node_mismatch() -> None:
    transaction = _node_transaction(node_id="item-002")
    errors = validate_node_render_transaction(
        transaction,
        expected_node_id="item-001",
        expected_plan_digest="a" * 64,
        expected_output_goal_digest="b" * 64,
        expected_render_config_digest="c" * 64,
        expected_context_digest="ctx",
    )
    assert any("node_id mismatch" in error for error in errors)


def test_validate_node_render_transaction_requires_artifacts_for_produce() -> None:
    transaction = _node_transaction(
        decision=RenderDecisionKind.PRODUCE,
        artifacts=[],
    )
    errors = validate_node_render_transaction(
        transaction,
        expected_node_id="item-001",
        expected_plan_digest="a" * 64,
        expected_output_goal_digest="b" * 64,
        expected_render_config_digest="c" * 64,
        expected_context_digest="ctx",
    )
    assert any("produce requires at least one artifact" in error for error in errors)
