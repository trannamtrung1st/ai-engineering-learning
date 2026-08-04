"""Unit tests for reviewer prompt context validation."""

from __future__ import annotations

import pytest

from top_down_planning.prompts.contexts import (
    FORBIDDEN_SCOPE_REVIEW_STAGE_LABELS,
    reviewer_protocol_context,
)


def test_reviewer_protocol_context_rejects_unknown_stage() -> None:
    with pytest.raises(ValueError, match="unsupported reviewer stage"):
        reviewer_protocol_context(stage="bogus", review_type="whole_plan")


def test_reviewer_protocol_context_rejects_unknown_review_type() -> None:
    with pytest.raises(ValueError, match="unsupported review_type"):
        reviewer_protocol_context(stage="initial_review", review_type="bogus")


def test_reviewer_protocol_context_includes_forbidden_scope_review_phrase() -> None:
    context = reviewer_protocol_context(stage="scope_review", review_type="whole_plan")
    phrase = context["forbidden_scope_review_phrase"]
    assert isinstance(phrase, str)
    for label in FORBIDDEN_SCOPE_REVIEW_STAGE_LABELS:
        assert label in phrase
