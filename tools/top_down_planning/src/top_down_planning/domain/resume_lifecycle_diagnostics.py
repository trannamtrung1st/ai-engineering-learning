"""Semantic lifecycle diagnostics for ``tdp resume --check``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from top_down_planning.domain.production_blockers import (
    evaluate_blocker_report,
    stale_blocked_run_is_repairable,
)
from top_down_planning.domain.reviews import (
    CLEAR_APPROVAL_STATUSES,
    ReviewLoop,
    advisory_handoff_allowed,
    is_terminal_review_loop,
    needs_advisory_handoff,
)
from top_down_planning.domain.session_recovery_state import phase_action_domain_committed_id


@dataclass(frozen=True)
class LifecycleDiagnostic:
    code: str
    message: str
    proposed_reconciliation: str
    loop_id: str | None = None
    finding_set_id: str | None = None
    target_revision: int | None = None
    target_digest: str | None = None
    phase_action_id: str | None = None
    phase_action_domain_committed_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "proposed_reconciliation": self.proposed_reconciliation,
        }
        if self.loop_id:
            payload["loop_id"] = self.loop_id
        if self.finding_set_id:
            payload["finding_set_id"] = self.finding_set_id
        if self.target_revision is not None:
            payload["target_revision"] = self.target_revision
        if self.target_digest:
            payload["target_digest"] = self.target_digest
        if self.phase_action_id:
            payload["phase_action_id"] = self.phase_action_id
        if self.phase_action_domain_committed_id:
            payload["phase_action_domain_committed_id"] = (
                self.phase_action_domain_committed_id
            )
        return payload


def collect_lifecycle_diagnostics(
    *,
    run: dict[str, Any],
    production: dict[str, Any] | None,
    reviews: list[dict[str, Any]] | None,
    events: list[dict[str, Any]] | None = None,
) -> list[LifecycleDiagnostic]:
    """Detect cross-record lifecycle inconsistencies without mutating state."""

    diagnostics: list[LifecycleDiagnostic] = []
    loops = [ReviewLoop.from_dict(raw) for raw in (reviews or [])]

    production_payload = production if isinstance(production, dict) else {}
    evaluation = evaluate_blocker_report(
        production_payload.get("blocker_report"),
        loops,
        events=events,
    )
    if evaluation.disposition == "resolved":
        report = evaluation.report or {}
        diagnostics.append(
            LifecycleDiagnostic(
                code="stale_review_bound_blocker",
                message=(
                    "stale review-bound production blocker; "
                    "blocking condition is already satisfied"
                ),
                proposed_reconciliation=(
                    "persist blocker status=resolved for the matching loop; "
                    "continue production"
                ),
                loop_id=evaluation.matching_loop_id,
                target_revision=report.get("target_revision")
                if isinstance(report.get("target_revision"), int)
                else None,
                target_digest=str(report.get("target_digest") or "") or None,
            )
        )

    if evaluation.disposition == "active_wait":
        matching = next(
            (loop for loop in loops if loop.id == evaluation.matching_loop_id),
            None,
        )
        if matching is not None and (
            is_terminal_review_loop(matching)
            or matching.status in CLEAR_APPROVAL_STATUSES
        ):
            report = evaluation.report or {}
            missing_digest = "missing review digest" in str(evaluation.reason or "")
            diagnostics.append(
                LifecycleDiagnostic(
                    code="unsatisfiable_review_bound_blocker",
                    message=(
                        "review-bound production blocker cannot be satisfied; "
                        "matching review is missing review digest"
                        if missing_digest
                        else (
                            "review-bound production blocker cannot be satisfied by "
                            "the terminal matching loop"
                        )
                    ),
                    proposed_reconciliation=(
                        "do not auto-clear; inspect loop/revision/digest identity "
                        "or report a genuine external blocker"
                    ),
                    loop_id=evaluation.matching_loop_id,
                    target_revision=report.get("target_revision")
                    if isinstance(report.get("target_revision"), int)
                    else None,
                    target_digest=str(report.get("target_digest") or "") or None,
                )
            )

    if evaluation.diagnostic_code == "ambiguous_legacy_blocker":
        report = evaluation.report or {}
        diagnostics.append(
            LifecycleDiagnostic(
                code="ambiguous_legacy_blocker",
                message=(
                    "legacy production blocker coincides with focused review "
                    "history but causal binding is ambiguous"
                ),
                proposed_reconciliation=(
                    "do not auto-clear; inspect production_blocked_reported, "
                    "focused-review request/approval, affected refs, and "
                    "evidence, then bind explicitly or keep as external"
                ),
                loop_id=evaluation.matching_loop_id,
                target_revision=report.get("target_revision")
                if isinstance(report.get("target_revision"), int)
                else None,
                target_digest=str(report.get("target_digest") or "") or None,
            )
        )

    repair = stale_blocked_run_is_repairable(
        run=run,
        production=production_payload,
        reviews=loops,
        events=events,
    )
    if repair is not None:
        report = repair.report or {}
        diagnostics.append(
            LifecycleDiagnostic(
                code="stale_blocked_run_repairable",
                message=(
                    "completed blocked outcome was caused by a stale "
                    "focused-review wait that is already satisfied"
                ),
                proposed_reconciliation=(
                    "reopen the run to running and persist blocker "
                    "status=resolved; continue production"
                ),
                loop_id=repair.matching_loop_id,
                target_revision=report.get("target_revision")
                if isinstance(report.get("target_revision"), int)
                else None,
                target_digest=str(report.get("target_digest") or "") or None,
            )
        )

    stop = run.get("stop") if isinstance(run.get("stop"), dict) else {}
    if str(stop.get("code") or "") == "provider_turn_failed":
        active = str(run.get("phase_action_id") or "").strip() or None
        committed = phase_action_domain_committed_id(run)
        if not active and committed:
            diagnostics.append(
                LifecycleDiagnostic(
                    code="misclassified_provider_turn_failed",
                    message=(
                        "provider action completed and the later failure belongs "
                        "to orchestration/state handling"
                    ),
                    proposed_reconciliation=(
                        "do not restore phase_action_id from "
                        "phase_action_domain_committed_id; treat the stop as "
                        "orchestrator_state_conflict and resume"
                    ),
                    phase_action_id=active,
                    phase_action_domain_committed_id=committed,
                )
            )

    for loop in loops:
        if needs_advisory_handoff(loop) and not advisory_handoff_allowed(loop):
            diagnostics.append(
                LifecycleDiagnostic(
                    code="advisory_handoff_identity_mismatch",
                    message=(
                        "new optional findings require owner actions but "
                        "advisory_handoff_allowed is false solely due to a prior "
                        "discovery population"
                    ),
                    proposed_reconciliation=(
                        "allocate a fresh finding_set_id for the new discovery "
                        "population; do not clear advisory_handoffs_completed"
                    ),
                    loop_id=loop.id,
                    finding_set_id=loop.finding_set_id,
                )
            )
    return diagnostics
