"""Role-specific recovery manifests for provider session replacement (§12.4–§12.5)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from top_down_planning.agent_tool.config import planning_limits_from_config
from top_down_planning.agent_tool.views import build_plan_review_snapshot
from top_down_planning.domain.amendment_recovery import pending_amendment_recovery_state
from top_down_planning.domain.models import Plan
from top_down_planning.domain.production import (
    build_production_review_snapshot,
    latest_reconciliation_report,
)
from top_down_planning.domain.reviews import (
    ReviewLoop,
    build_active_findings_view,
    loop_revise_at,
    required_open_findings,
    review_gate_budgets_for_package,
)
from top_down_planning.persistence.interface import RunStore

REPLACEMENT_SESSION_NOTICE = (
    "The previous provider session is unavailable or produced no stream output "
    "within the configured idle window. Continue from the canonical durable run "
    "state below. Do not assume access to prior hidden conversation history. "
    "Reconcile the next action with the supplied revisions, findings, evidence, "
    "and phase contract."
)


def recent_durable_event_summary(
    store: RunStore,
    run_id: str,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return the most recent orchestration audit events for recovery context."""

    run_dir_fn = getattr(store, "run_dir", None)
    if not callable(run_dir_fn):
        return []

    events_path = Path(run_dir_fn(run_id)) / "events.jsonl"
    if not events_path.is_file():
        return []

    lines = events_path.read_text(encoding="utf-8").splitlines()
    summary: list[dict[str, Any]] = []
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        summary.append(
            {
                "type": payload.get("type"),
                "ts": payload.get("ts"),
                "phase": payload.get("phase"),
                "role": payload.get("role"),
            }
        )
        if len(summary) >= limit:
            break
    summary.reverse()
    return summary


def _base_recovery_fields(
    *,
    run_id: str,
    run: dict[str, Any],
    role: str,
    session_kind: str,
    phase: str,
    phase_action_id: str,
    expected_next_action: str,
    store: RunStore,
    target_digest: str | None = None,
) -> dict[str, Any]:
    digests = dict(run.get("digests") or {})
    payload: dict[str, Any] = {
        "run_id": run_id,
        "phase": phase,
        "role": role,
        "session_kind": session_kind,
        "phase_action_id": phase_action_id,
        "expected_next_action": expected_next_action,
        "replacement_session_notice": REPLACEMENT_SESSION_NOTICE,
        "revisions": {
            "run_revision": int(run.get("revision") or 0),
            "plan_revision": int(run.get("plan_revision") or 0),
            "production_revision": int(run.get("production_revision") or 0),
        },
    }
    if target_digest is not None:
        payload["target_digest"] = target_digest
    else:
        plan_digest = digests.get("plan")
        if plan_digest:
            payload["target_digest"] = plan_digest
    return payload


def _open_findings_payload(loop: ReviewLoop) -> dict[str, Any]:
    threshold = loop_revise_at(loop)
    open_required = required_open_findings(loop.findings, threshold)
    active = build_active_findings_view(loop)
    return {
        "finding_set_id": loop.finding_set_id,
        "open_findings": [finding.to_dict() for finding in open_required],
        **active,
    }


def build_planner_recovery_manifest(
    store: RunStore,
    run_id: str,
    config: dict[str, Any],
    plan: Plan,
    *,
    phase_action_id: str,
    expected_next_action: str,
    activity: str = "initial_plan",
) -> dict[str, Any]:
    """Build planner replacement context from durable run state."""

    from top_down_planning.orchestrator.planning import build_planner_context_manifest

    run = store.load_run(run_id)
    planning = run.get("planning") or {}
    limits = (config.get("limits") or {}).get("planning") or {}
    manifest = build_planner_context_manifest(
        run_id,
        run,
        config,
        plan,
        activity=activity,
    )
    manifest.update(
        _base_recovery_fields(
            run_id=run_id,
            run=run,
            role="planner",
            session_kind="primary",
            phase=str(run.get("phase") or "planning"),
            phase_action_id=phase_action_id,
            expected_next_action=expected_next_action,
            store=store,
        )
    )
    manifest["plan_snapshot"] = build_plan_review_snapshot(
        plan,
        limits=planning_limits_from_config(config),
    )
    manifest["planning_budget"] = {
        "consumed": {
            "agent_turns": int(planning.get("agent_turns") or 0),
            "items_added": int(planning.get("items_added") or 0),
        },
        "remaining": {
            "max_agent_turns": int(limits.get("max_agent_turns") or 0),
            "max_items_added": int(limits.get("max_items_added") or 0),
        },
    }
    manifest["open_review_findings"] = _collect_open_review_findings(
        store,
        run_id,
        review_types={"focused_plan", "whole_plan"},
    )
    return manifest


def build_producer_recovery_manifest(
    store: RunStore,
    run_id: str,
    config: dict[str, Any],
    plan: Plan,
    *,
    phase_action_id: str,
    expected_next_action: str,
    activity: str = "production",
) -> dict[str, Any]:
    """Build producer replacement context from durable run state."""

    from top_down_planning.orchestrator.production import build_producer_context_manifest

    run = store.load_run(run_id)
    production = store.load_production(run_id)
    manifest = build_producer_context_manifest(
        run_id,
        run,
        config,
        plan,
        production=production,
        activity=activity,
    )
    manifest.update(
        _base_recovery_fields(
            run_id=run_id,
            run=run,
            role="producer",
            session_kind="primary",
            phase=str(run.get("phase") or "production"),
            phase_action_id=phase_action_id,
            expected_next_action=expected_next_action,
            store=store,
        )
    )
    manifest["production_snapshot"] = build_production_review_snapshot(production)
    manifest["pending_amendment"] = pending_amendment_recovery_state(production)
    reconciliation = latest_reconciliation_report(production)
    if reconciliation is not None:
        manifest["reconciliation"] = reconciliation
    manifest["open_review_findings"] = _collect_open_review_findings(
        store,
        run_id,
        review_types={"focused_output", "whole_output"},
    )
    return manifest


def build_reviewer_recovery_manifest(
    store: RunStore,
    run_id: str,
    config: dict[str, Any],
    loop: ReviewLoop,
    *,
    review_package: dict[str, Any],
    phase_action_id: str,
    expected_next_action: str,
) -> dict[str, Any]:
    """Build reviewer replacement context from durable review-loop state."""

    run = store.load_run(run_id)
    manifest = dict(review_package)
    manifest.update(
        _base_recovery_fields(
            run_id=run_id,
            run=run,
            role="reviewer",
            session_kind="reviewer",
            phase=str(run.get("phase") or ""),
            phase_action_id=phase_action_id,
            expected_next_action=expected_next_action,
            store=store,
        )
    )
    manifest["active_review_loop"] = {
        "loop_id": loop.id,
        "type": loop.type,
        "status": loop.status,
        "active_stage": loop.active_stage,
    }
    manifest["finding_set"] = _open_findings_payload(loop)
    manifest["verification_state"] = loop.verification_result
    manifest["review_limits"] = review_gate_budgets_for_package(loop, config)
    return manifest


def _collect_open_review_findings(
    store: RunStore,
    run_id: str,
    *,
    review_types: set[str],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for review in store.list_reviews(run_id):
        review_type = str(review.get("type") or "")
        if review_type not in review_types:
            continue
        loop = ReviewLoop.from_dict(review)
        payload = _open_findings_payload(loop)
        if (
            not payload["open_findings"]
            and not payload.get("carried_open_findings")
            and not payload.get("new_findings")
            and not payload.get("current_finding_actions")
        ):
            continue
        findings.append(
            {
                "loop_id": loop.id,
                "type": loop.type,
                "status": loop.status,
                **payload,
            }
        )
    return findings


__all__ = [
    "REPLACEMENT_SESSION_NOTICE",
    "build_planner_recovery_manifest",
    "build_producer_recovery_manifest",
    "build_reviewer_recovery_manifest",
    "recent_durable_event_summary",
]
