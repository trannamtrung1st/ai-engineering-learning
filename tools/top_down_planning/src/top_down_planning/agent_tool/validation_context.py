"""Shared plan approval validation context for agent and user CLI paths."""

from __future__ import annotations

from typing import Any

from top_down_planning.config import compute_input_digest, compute_output_goal_digest
from top_down_planning.domain.models import Plan
from top_down_planning.domain.reviews import find_whole_plan_approval
from top_down_planning.domain.validators import (
    DigestBundle,
    ReviewState,
    ValidationMode,
    build_plan_approval_validation_context,
)
from top_down_planning.workspace import run_workspace
from top_down_planning.persistence.digests import compute_config_digest, compute_plan_digest
from top_down_planning.persistence.interface import RunStore


def compute_plan_approval_actual_digests(
    store: RunStore,
    run_id: str,
    run: dict[str, Any],
    plan: Plan,
) -> tuple[str, str, str, str, str | None]:
    """Recompute digests for approval-mode comparison against reviewed bindings."""

    config = store.load_resolved_config(run_id)
    base_dir = run_workspace(run)
    run_digests = run.get("digests") or {}
    return (
        compute_plan_digest(plan),
        compute_config_digest(config),
        compute_input_digest(config, base_dir=base_dir),
        compute_output_goal_digest(config, base_dir=base_dir),
        run_digests.get("context"),
    )


def plan_approval_validation_context(
    store: RunStore,
    run_id: str,
    plan: Plan,
    mode: ValidationMode,
) -> tuple[ReviewState | None, DigestBundle | None]:
    """Load whole-plan approval bindings when ``mode`` is ``approval``."""

    if mode != "approval":
        return None, None

    approval = find_whole_plan_approval(store.list_reviews(run_id), plan.revision)
    if approval is None:
        return _approval_hooks_not_checked_context(store, run_id, plan)

    run = store.load_run(run_id)
    (
        actual_plan_digest,
        actual_config_digest,
        actual_input_digest,
        actual_output_goal_digest,
        actual_context_digest,
    ) = compute_plan_approval_actual_digests(store, run_id, run, plan)
    return build_plan_approval_validation_context(
        plan=plan,
        approval=approval,
        actual_plan_digest=actual_plan_digest,
        actual_config_digest=actual_config_digest,
        actual_input_digest=actual_input_digest,
        actual_output_goal_digest=actual_output_goal_digest,
        actual_context_digest=actual_context_digest,
    )


def _approval_hooks_not_checked_context(
    store: RunStore,
    run_id: str,
    plan: Plan,
) -> tuple[ReviewState, DigestBundle]:
    """Surface approval-mode hooks as not checked when no binding approval exists."""

    run = store.load_run(run_id)
    digests = run.get("digests") or {}
    return (
        ReviewState(),
        DigestBundle(
            plan_revision=plan.revision,
            expected_plan_digest=None,
            actual_plan_digest=compute_plan_digest(plan),
            input_digest=digests.get("input"),
            expected_input_digest=None,
            output_goal_digest=digests.get("output_goal"),
            expected_output_goal_digest=None,
            config_digest=compute_config_digest(store.load_resolved_config(run_id)),
            expected_config_digest=None,
            context_digest=digests.get("context"),
            expected_context_digest=None,
        ),
    )


def user_validate_mode_and_context(
    store: RunStore,
    run_id: str,
    run: dict[str, Any],
    plan: Plan,
) -> tuple[ValidationMode, ReviewState | None, DigestBundle | None]:
    """Resolve validation mode for ``tdp validate`` from stored whole-plan approval."""

    approval = find_whole_plan_approval(store.list_reviews(run_id), plan.revision)
    if approval is None:
        return "draft", None, None

    (
        actual_plan_digest,
        actual_config_digest,
        actual_input_digest,
        actual_output_goal_digest,
        actual_context_digest,
    ) = compute_plan_approval_actual_digests(store, run_id, run, plan)
    review_state, digest_bundle = build_plan_approval_validation_context(
        plan=plan,
        approval=approval,
        actual_plan_digest=actual_plan_digest,
        actual_config_digest=actual_config_digest,
        actual_input_digest=actual_input_digest,
        actual_output_goal_digest=actual_output_goal_digest,
        actual_context_digest=actual_context_digest,
    )
    return "approval", review_state, digest_bundle
