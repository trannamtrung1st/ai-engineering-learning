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
from top_down_planning.persistence.digests import compute_config_contract_digest, compute_plan_digest
from top_down_planning.persistence.interface import RunStore
from top_down_planning.persistence.snapshot import CanonicalRunSnapshot


def plan_approval_validation_context(
    snapshot: CanonicalRunSnapshot,
    plan: Plan,
    mode: ValidationMode,
) -> tuple[ReviewState | None, DigestBundle | None]:
    """Build whole-plan approval bindings from one canonical snapshot."""

    if mode != "approval":
        return None, None

    approval = find_whole_plan_approval(snapshot.reviews, plan.revision)
    if approval is None:
        return _approval_hooks_not_checked_context(snapshot, plan)

    (
        actual_plan_digest,
        actual_config_contract_digest,
        actual_input_digest,
        actual_output_goal_digest,
        actual_context_spec_digest,
    ) = compute_plan_approval_actual_digests_from_snapshot(snapshot, plan)
    return build_plan_approval_validation_context(
        plan=plan,
        approval=approval,
        actual_plan_digest=actual_plan_digest,
        actual_config_contract_digest=actual_config_contract_digest,
        actual_input_digest=actual_input_digest,
        actual_output_goal_digest=actual_output_goal_digest,
        actual_context_spec_digest=actual_context_spec_digest,
    )


def compute_plan_approval_actual_digests_from_snapshot(
    snapshot: CanonicalRunSnapshot,
    plan: Plan,
) -> tuple[str, str, str, str, str | None]:
    """Recompute digests for whole-plan approval-mode comparison."""

    config = snapshot.resolved_config
    base_dir = run_workspace(snapshot.run)
    run_digests = snapshot.run.get("digests") or {}
    return (
        compute_plan_digest(plan),
        compute_config_contract_digest(config),
        compute_input_digest(config, base_dir=base_dir),
        compute_output_goal_digest(config, base_dir=base_dir),
        run_digests.get("context_spec"),
    )


def compute_plan_approval_actual_digests(
    store: RunStore,
    run_id: str,
    run: dict[str, Any],
    plan: Plan,
) -> tuple[str, str, str, str, str | None]:
    """Recompute digests for whole-plan approval-mode comparison."""

    snapshot = CanonicalRunSnapshot(
        run=run,
        plan=plan.to_dict(),
        production={},
        reviews=[],
        resolved_config=store.load_resolved_config(run_id),
    )
    return compute_plan_approval_actual_digests_from_snapshot(snapshot, plan)


def _approval_hooks_not_checked_context(
    snapshot: CanonicalRunSnapshot,
    plan: Plan,
) -> tuple[ReviewState, DigestBundle]:
    """Surface approval-mode hooks as not checked when no binding approval exists."""

    run = snapshot.run
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
            config_contract_digest=compute_config_contract_digest(snapshot.resolved_config),
            expected_config_contract_digest=None,
            context_spec_digest=digests.get("context_spec"),
            expected_context_spec_digest=None,
        ),
    )


def user_validate_mode_and_context_from_snapshot(
    snapshot: CanonicalRunSnapshot,
    plan: Plan,
) -> tuple[ValidationMode, ReviewState | None, DigestBundle | None]:
    """Resolve ``tdp validate`` mode from one canonical snapshot."""

    approval = find_whole_plan_approval(snapshot.reviews, plan.revision)
    if approval is None:
        return "draft", None, None
    return "approval", *plan_approval_validation_context(snapshot, plan, "approval")


def user_validate_mode_and_context(
    store: RunStore,
    run_id: str,
    run: dict[str, Any],
    plan: Plan,
) -> tuple[ValidationMode, ReviewState | None, DigestBundle | None]:
    """Resolve validation mode for ``tdp validate`` from stored whole-plan approval."""

    snapshot = CanonicalRunSnapshot(
        run=run,
        plan=plan.to_dict(),
        production={},
        reviews=store.list_reviews(run_id),
        resolved_config=store.load_resolved_config(run_id),
    )
    return user_validate_mode_and_context_from_snapshot(snapshot, plan)
