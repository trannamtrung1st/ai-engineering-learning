"""Reviewer prompt contract constants shared by templates and tests."""

from __future__ import annotations

FORBIDDEN_SCOPE_REVIEW_STAGE_LABELS = (
    "full review",
    "confirmation review",
    "holistic review",
    "spot check",
)

__all__ = ["FORBIDDEN_SCOPE_REVIEW_STAGE_LABELS"]
