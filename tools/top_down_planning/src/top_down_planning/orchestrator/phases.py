"""Lifecycle phase vocabulary (proposal §3, §17.2)."""

from __future__ import annotations

PLANNING = "planning"
WHOLE_PLAN_REVIEW = "whole_plan_review"
PLAN_VALIDATED = "plan_validated"
PRODUCTION = "production"
PLAN_AMENDMENT = "plan_amendment"
WHOLE_OUTPUT_REVIEW = "whole_output_review"
OUTPUT_VALIDATED = "output_validated"

PLANNING_CONSTRUCTION_PHASES = frozenset({PLANNING})
