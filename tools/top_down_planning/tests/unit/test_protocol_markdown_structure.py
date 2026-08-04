"""Unit tests for rendered protocol Markdown structure."""

from __future__ import annotations

import re

import pytest

from top_down_planning.orchestrator.planner_session import build_planner_protocol_instructions
from top_down_planning.orchestrator.producer_session import build_producer_protocol_instructions
from top_down_planning.orchestrator.reviewer_session import build_reviewer_protocol_instructions

_CONCATENATED_BULLET = re.compile(r"[\.\)`]\s*-")


def _assert_distinct_markdown_bullets(protocol: str) -> None:
    assert isinstance(protocol, str)
    for line in protocol.splitlines():
        assert _CONCATENATED_BULLET.search(line) is None, line[:160]


def test_planner_protocol_uses_distinct_markdown_bullets() -> None:
    _assert_distinct_markdown_bullets(build_planner_protocol_instructions())


def test_producer_protocol_uses_distinct_markdown_bullets() -> None:
    _assert_distinct_markdown_bullets(build_producer_protocol_instructions())


@pytest.mark.parametrize(
    ("stage", "review_type"),
    [
        (None, "whole_plan"),
        ("initial_review", "whole_output"),
        ("scope_review", "whole_plan"),
        ("finding_verification", "whole_plan"),
        (None, "focused_plan"),
        ("finding_verification", "focused_output"),
    ],
)
def test_reviewer_protocol_uses_distinct_markdown_bullets(
    stage: str | None,
    review_type: str,
) -> None:
    _assert_distinct_markdown_bullets(
        build_reviewer_protocol_instructions(stage=stage, review_type=review_type)
    )
