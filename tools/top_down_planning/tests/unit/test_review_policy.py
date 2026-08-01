"""Domain tests for severity ranking and revise_at resolution."""

from __future__ import annotations

import itertools
from typing import get_args

import pytest

from top_down_planning.domain.review_policy import (
    BUILTIN_REVISE_AT,
    CATEGORY_DEFINITIONS,
    FINDING_CATEGORY_ORDER,
    FindingCategory,
    SEVERITY_ORDER,
    SEVERITY_RANK,
    resolved_revise_at,
    severity_at_or_above,
    severity_rank,
    validate_finding_category,
    validate_review_severity,
)


def test_severity_order_matches_proposal() -> None:
    assert SEVERITY_ORDER == ("suggestion", "minor", "major", "blocker")
    assert SEVERITY_RANK == {
        "suggestion": 0,
        "minor": 1,
        "major": 2,
        "blocker": 3,
    }
    for lower, higher in zip(SEVERITY_ORDER, SEVERITY_ORDER[1:], strict=False):
        assert severity_rank(lower) < severity_rank(higher)


def test_severity_ordering_for_all_pairs() -> None:
    for left, right in itertools.product(SEVERITY_ORDER, repeat=2):
        expected = SEVERITY_RANK[left] >= SEVERITY_RANK[right]
        assert severity_at_or_above(left, right) is expected


def test_validate_review_severity_accepts_known_values() -> None:
    for severity in SEVERITY_ORDER:
        assert validate_review_severity(severity) == severity
        assert validate_review_severity(f"  {severity}  ") == severity


def test_validate_review_severity_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="review severity must be one of"):
        validate_review_severity("critical")
    with pytest.raises(ValueError, match="review severity must be one of"):
        validate_review_severity("blocking")


def test_builtin_revise_at_encodes_ac6_defaults() -> None:
    assert BUILTIN_REVISE_AT == {
        "focused_plan": "blocker",
        "focused_output": "blocker",
        "whole_plan": "major",
        "whole_output": "major",
    }


def test_resolved_revise_at_falls_back_to_builtin() -> None:
    config = {"review": {"revise_at": None, "whole_plan": {"revise_at": None}}}
    assert resolved_revise_at(config, "whole_plan") == "major"
    assert resolved_revise_at(config, "focused_plan") == "blocker"
    assert resolved_revise_at({}, "whole_output") == "major"
    assert resolved_revise_at({"review": {}}, "focused_output") == "blocker"


def test_resolved_revise_at_global_override_when_per_type_null() -> None:
    config = {
        "review": {
            "revise_at": "minor",
            "focused_plan": {"revise_at": None},
            "focused_output": {"revise_at": None},
            "whole_plan": {"revise_at": None},
            "whole_output": {"revise_at": None},
        }
    }
    for review_type in BUILTIN_REVISE_AT:
        assert resolved_revise_at(config, review_type) == "minor"


def test_resolved_revise_at_per_type_wins_over_global() -> None:
    config = {
        "review": {
            "revise_at": "minor",
            "whole_plan": {"revise_at": "blocker"},
            "focused_plan": {"revise_at": None},
        }
    }
    assert resolved_revise_at(config, "whole_plan") == "blocker"
    assert resolved_revise_at(config, "focused_plan") == "minor"


def test_resolved_revise_at_rejects_invalid_severity() -> None:
    with pytest.raises(ValueError, match="review severity must be one of"):
        resolved_revise_at({"review": {"revise_at": "critical"}}, "whole_plan")
    with pytest.raises(ValueError, match="review severity must be one of"):
        resolved_revise_at(
            {"review": {"whole_plan": {"revise_at": "blocking"}}},
            "whole_plan",
        )


def test_resolved_revise_at_rejects_unknown_review_type() -> None:
    with pytest.raises(ValueError, match="review_type must be one of"):
        resolved_revise_at({}, "ad_hoc_review")


def test_finding_category_literal_matches_definitions() -> None:
    assert frozenset(get_args(FindingCategory)) == frozenset(CATEGORY_DEFINITIONS)


def test_builtin_finding_categories_include_other() -> None:
    assert FINDING_CATEGORY_ORDER == tuple(sorted(CATEGORY_DEFINITIONS))
    assert "other" in CATEGORY_DEFINITIONS
    for category in FINDING_CATEGORY_ORDER:
        assert validate_finding_category(category) == category


def test_category_definitions_cover_builtin_categories() -> None:
    for category in FINDING_CATEGORY_ORDER:
        definition = CATEGORY_DEFINITIONS[category]
        assert isinstance(definition, str)
        assert definition.strip()


def test_validate_finding_category_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="finding category must be one of"):
        validate_finding_category("style")
    with pytest.raises(ValueError, match="acceptance, architecture"):
        validate_finding_category("style")
