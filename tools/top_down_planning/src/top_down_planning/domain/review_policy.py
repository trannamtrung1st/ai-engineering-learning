"""Severity ranking, categories, and revise_at resolution helpers.

Policy primitives for review findings and revision thresholds (proposal:
Finding Model, Configuration, Policy Evaluation, Proposed Domain Helpers).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

ReviewSeverity = Literal["suggestion", "minor", "major", "blocker"]

SEVERITY_ORDER: tuple[ReviewSeverity, ...] = (
    "suggestion",
    "minor",
    "major",
    "blocker",
)

SEVERITY_RANK: dict[str, int] = {
    "suggestion": 0,
    "minor": 1,
    "major": 2,
    "blocker": 3,
}

SEVERITY_DEFINITIONS: dict[ReviewSeverity, str] = {
    "blocker": (
        "Approval would be unsafe, invalid, or plainly incorrect. "
        "The artifact cannot reasonably proceed without resolution."
    ),
    "major": (
        "A material quality, coverage, correctness, or acceptance gap "
        "likely to cause failure or substantial rework."
    ),
    "minor": (
        "A real localized issue that should be considered but does not "
        "invalidate the artifact."
    ),
    "suggestion": "An optional improvement, preference, or refinement.",
}

FindingCategory = Literal[
    "correctness",
    "requirements_coverage",
    "acceptance",
    "scope",
    "traceability",
    "architecture",
    "security",
    "reliability",
    "performance",
    "maintainability",
    "usability",
    "testing",
    "documentation",
    "other",
]

BUILTIN_FINDING_CATEGORIES: frozenset[str] = frozenset(
    {
        "correctness",
        "requirements_coverage",
        "acceptance",
        "scope",
        "traceability",
        "architecture",
        "security",
        "reliability",
        "performance",
        "maintainability",
        "usability",
        "testing",
        "documentation",
        "other",
    }
)

BUILTIN_REVISE_AT: dict[str, ReviewSeverity] = {
    "focused_plan": "blocker",
    "focused_output": "blocker",
    "whole_plan": "major",
    "whole_output": "major",
}


def validate_review_severity(value: str) -> ReviewSeverity:
    """Return a validated severity; reject unknown values."""

    normalized = str(value).strip()
    if normalized not in SEVERITY_RANK:
        raise ValueError(
            "review severity must be one of: " + ", ".join(SEVERITY_ORDER)
        )
    return normalized  # type: ignore[return-value]


def validate_finding_category(value: str) -> FindingCategory:
    """Return a validated finding category; reject unknown values."""

    normalized = str(value).strip()
    if normalized not in BUILTIN_FINDING_CATEGORIES:
        raise ValueError(
            "finding category must be one of: "
            + ", ".join(sorted(BUILTIN_FINDING_CATEGORIES))
        )
    return normalized  # type: ignore[return-value]


def severity_rank(value: ReviewSeverity) -> int:
    """Return the ordinal rank for a validated severity."""

    return SEVERITY_RANK[validate_review_severity(value)]


def severity_at_or_above(value: ReviewSeverity, threshold: ReviewSeverity) -> bool:
    """True when ``value`` is at or above the revision threshold."""

    return severity_rank(value) >= severity_rank(threshold)


def resolved_revise_at(config: Mapping[str, Any], review_type: str) -> ReviewSeverity:
    """Resolve effective revise_at via null-inheritance and built-in defaults.

    Resolution order:
    non-null review.<review_type>.revise_at
    → non-null review.revise_at
    → BUILTIN_REVISE_AT[review_type]
    """

    review_type_key = str(review_type).strip()
    if review_type_key not in BUILTIN_REVISE_AT:
        raise ValueError(
            "review_type must be one of: " + ", ".join(sorted(BUILTIN_REVISE_AT))
        )

    review_section = config.get("review") or {}
    if not isinstance(review_section, Mapping):
        review_section = {}

    type_section = review_section.get(review_type_key) or {}
    if not isinstance(type_section, Mapping):
        type_section = {}

    per_type = type_section.get("revise_at")
    if per_type is not None:
        return validate_review_severity(str(per_type))

    global_value = review_section.get("revise_at")
    if global_value is not None:
        return validate_review_severity(str(global_value))

    return BUILTIN_REVISE_AT[review_type_key]
