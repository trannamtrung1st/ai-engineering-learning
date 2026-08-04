"""Matrix tests for reviewer protocol template includes."""

from __future__ import annotations

import pytest

from top_down_planning.orchestrator.reviewer_session import build_reviewer_protocol_instructions


@pytest.mark.parametrize(
    ("stage", "review_type", "required", "forbidden"),
    [
        (
            "initial_review",
            "whole_plan",
            (
                "preflight_candidates",
                "audit attestation",
                "complete gap-seeking sweep produces no additional",
            ),
            ("stage: finding_verification", "family_results"),
        ),
        (
            "scope_review",
            "whole_output",
            (
                "fresh discovery",
                "traceability",
                "discovery_sweep",
            ),
            ("stage: finding_verification",),
        ),
        (
            "finding_verification",
            "whole_plan",
            (
                "family_results",
                "verification_sweep",
                "not a new broad discovery pass",
            ),
            ("audit_attestation", "preflight_candidates"),
        ),
        (
            None,
            "focused_plan",
            (
                "finding_families",
                "built-in finding-family rule_id",
            ),
            ("audit attestation", "preflight_candidates"),
        ),
        (
            None,
            "focused_output",
            (
                "built-in finding-family rule_id",
                "do not read tdp python source",
            ),
            ("audit attestation", "focused plan review"),
        ),
        (
            "scope_review",
            "whole_plan",
            (
                "do not use prior finding or family text as framing",
                "preflight_candidates",
                "audit attestation",
            ),
            ("stage: finding_verification",),
        ),
    ],
)
def test_reviewer_protocol_matrix(
    stage: str | None,
    review_type: str,
    required: tuple[str, ...],
    forbidden: tuple[str, ...],
) -> None:
    protocol = build_reviewer_protocol_instructions(
        stage=stage,
        review_type=review_type,
    ).lower()
    for phrase in required:
        assert phrase in protocol, phrase
    for phrase in forbidden:
        assert phrase not in protocol, phrase
