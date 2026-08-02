"""Behavior profiles for shared review-loop drivers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewLoopProfile:
    """Orchestration behavior for mandatory gates vs optional focused loops."""

    scope_review_enabled: bool
    pause_run_on_review_incomplete: bool
    is_mandatory_gate: bool
    allocate_discovery_on_any_start: bool


MANDATORY_WHOLE_PROFILE = ReviewLoopProfile(
    scope_review_enabled=True,
    pause_run_on_review_incomplete=True,
    is_mandatory_gate=True,
    allocate_discovery_on_any_start=False,
)

FOCUSED_PROFILE = ReviewLoopProfile(
    scope_review_enabled=False,
    pause_run_on_review_incomplete=False,
    is_mandatory_gate=False,
    allocate_discovery_on_any_start=True,
)
