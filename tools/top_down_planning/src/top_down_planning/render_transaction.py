"""Validate structured per-node render transactions."""

from __future__ import annotations

from top_down_planning.models import RenderNodeTransaction
from top_down_planning.render_decisions import validate_node_transaction


def validate_node_render_transaction(
    transaction: RenderNodeTransaction,
    *,
    expected_node_id: str,
    expected_plan_digest: str,
    expected_output_goal_digest: str,
    expected_render_config_digest: str,
    expected_context_digest: str,
) -> list[str]:
    errors: list[str] = []
    if transaction.node_id != expected_node_id:
        errors.append(
            f"node_id mismatch: expected {expected_node_id!r}, got {transaction.node_id!r}"
        )
    if transaction.plan_digest != expected_plan_digest:
        errors.append("plan_digest mismatch")
    if transaction.output_goal_digest != expected_output_goal_digest:
        errors.append("output_goal_digest mismatch")
    if transaction.render_config_digest != expected_render_config_digest:
        errors.append("render_config_digest mismatch")
    if transaction.context_digest != expected_context_digest:
        errors.append("context_digest mismatch")
    if transaction.read_set_digest != expected_context_digest:
        errors.append("read_set_digest mismatch")
    errors.extend(validate_node_transaction(transaction))
    return errors
