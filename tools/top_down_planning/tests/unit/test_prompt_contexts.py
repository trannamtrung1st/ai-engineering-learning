"""Unit tests for reviewer prompt context validation."""

from __future__ import annotations

import pytest

from top_down_planning.prompts.contexts import reviewer_protocol_context


def test_reviewer_protocol_context_rejects_unknown_stage() -> None:
    with pytest.raises(ValueError, match="unsupported reviewer stage"):
        reviewer_protocol_context(stage="bogus", review_type="whole_plan")


def test_reviewer_protocol_context_rejects_unknown_review_type() -> None:
    with pytest.raises(ValueError, match="unsupported review_type"):
        reviewer_protocol_context(stage="initial_review", review_type="bogus")
