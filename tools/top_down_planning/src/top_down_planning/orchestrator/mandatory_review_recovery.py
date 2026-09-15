"""Recovery detection for mandatory review loops after partial persistence."""

from __future__ import annotations

from typing import Any

from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.orchestrator.provider_turns import owner_revision_complete


def pending_verification_owner_cycle_charge(
    store: Any,
    run_id: str,
    loop: ReviewLoop,
) -> bool:
    """True when verification ``needs_revision`` reopened owner work without charging the next cycle.

    Crash between ``mark_findings_open()`` and ``enter_revision_cycle()`` leaves
    ``revision_in_progress`` at the prior ``revision_cycles`` with a consumed
    verification decision still on the loop. Resume must charge the next cycle
    before treating prior-cycle owner work as complete.

    Legitimate resume states keep ``status`` at ``pending`` while production
    advances past ``target_revision``; those paths prepare recheck instead.
    """

    if loop.lifecycle_status != "revision_in_progress":
        return False
    if loop.status != "needs_revision":
        return False
    verification = loop.verification_result
    if not isinstance(verification, dict):
        return False
    if str(verification.get("decision") or "").strip() != "needs_revision":
        return False
    return owner_revision_complete(store, run_id, loop.id)
