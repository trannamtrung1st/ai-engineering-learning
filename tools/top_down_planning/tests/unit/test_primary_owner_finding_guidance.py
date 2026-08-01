"""Primary-agent review handoff guidance and review_budget disclosure."""

from __future__ import annotations

import pytest

from top_down_planning.domain.reviews import (
    ReviewFinding,
    build_primary_owner_finding_guidance,
    build_review_budget_fields,
    primary_review_resume_fields,
)
from tests.helpers import make_review_loop, minimal_resolved_config


def _finding(finding_id: str, *, severity: str) -> ReviewFinding:
    return ReviewFinding(
        id=finding_id,
        severity=severity,  # type: ignore[arg-type]
        category="other",
        target_refs=["item-a"],
        issue=f"issue-{finding_id}",
        recommended_change="fix",
        status="unresolved",
    )


def test_review_budget_fields_for_whole_plan_review() -> None:
    loop = make_review_loop(
        id="loop-whole-plan",
        type="whole_plan",
        target_revision=1,
        scope={"kind": "whole_plan"},
        revision_cycles=3,
        scope_review_rounds=2,
    )
    config = {
        "limits": {
            "whole_plan_review": {
                "max_revision_cycles": 5,
                "max_scope_review_rounds": 3,
            }
        }
    }
    budget = build_review_budget_fields(loop, config)
    assert budget["revision_cycles"] == {
        "consumed": 3,
        "max": 5,
        "remaining": 2,
    }
    assert budget["scope_review_rounds"] == {
        "consumed": 2,
        "max": 3,
        "remaining": 1,
    }


def test_review_budget_fields_for_focused_output_review() -> None:
    loop = make_review_loop(
        id="loop-focused-output",
        type="focused_output",
        target_revision=1,
        scope={"kind": "focused_output", "item_ids": ["item-a"]},
        revision_cycles=2,
    )
    config = {
        "limits": {
            "focused_output_review": {
                "max_revision_cycles_per_loop": 3,
            }
        }
    }
    budget = build_review_budget_fields(loop, config)
    assert budget == {
        "revision_cycles": {
            "consumed": 2,
            "max": 3,
            "remaining": 1,
        }
    }


def test_primary_review_resume_fields_includes_review_budget() -> None:
    loop = make_review_loop(
        id="loop-whole-output",
        type="whole_output",
        target_revision=1,
        scope={"kind": "whole_output"},
        revision_cycles=4,
        scope_review_rounds=1,
        revise_at="major",
    )
    config = minimal_resolved_config()
    fields = primary_review_resume_fields(loop, config=config)
    assert fields["review_budget"]["revision_cycles"]["remaining"] == 1
    assert fields["review_budget"]["scope_review_rounds"]["remaining"] == 2


def test_primary_review_resume_fields_requires_config() -> None:
    loop = make_review_loop(
        id="loop-whole-plan-2",
        type="whole_plan",
        target_revision=1,
        scope={"kind": "whole_plan"},
    )
    with pytest.raises(TypeError):
        primary_review_resume_fields(loop)  # type: ignore[call-arg]


def test_revision_guidance_prefers_defer_or_accept_for_optionals() -> None:
    loop = make_review_loop(
        id="loop-revision",
        type="whole_plan",
        target_revision=1,
        scope={"kind": "whole_plan"},
        revise_at="major",
        findings=[
            _finding("f-major", severity="major"),
            _finding("f-minor", severity="minor"),
        ],
        revision_cycles=4,
    )
    config = {
        "limits": {
            "whole_plan_review": {
                "max_revision_cycles": 5,
                "max_scope_review_rounds": 3,
            }
        }
    }
    guidance = build_primary_owner_finding_guidance(
        handoff="revision",
        loop=loop,
        config=config,
    )
    assert "required finding" in guidance.lower()
    assert "defer or accept_as_is" in guidance
    assert "1 optional finding(s)" in guidance
    assert "1 revision cycle(s) remaining" in guidance


def test_advisory_guidance_mentions_default_optional_action() -> None:
    loop = make_review_loop(
        id="loop-advisory",
        type="focused_plan",
        target_revision=1,
        scope={"kind": "focused_plan", "item_ids": ["item-a"]},
        revise_at="major",
        findings=[_finding("f-minor", severity="minor")],
        revision_cycles=0,
    )
    config = {
        "limits": {
            "focused_plan_review": {
                "max_revision_cycles_per_loop": 3,
            }
        }
    }
    guidance = build_primary_owner_finding_guidance(
        handoff="advisory",
        loop=loop,
        config=config,
    )
    assert "default_optional_action" in guidance
    assert "accept_as_is" in guidance


def test_build_review_budget_fields_rejects_unknown_loop_type() -> None:
    loop = make_review_loop(
        id="loop-unknown",
        type="whole_plan",
        target_revision=1,
        scope={"kind": "whole_plan"},
    )
    loop = loop.__class__.from_dict({**loop.to_dict(), "type": "unknown"})
    with pytest.raises(ValueError, match="unsupported review loop type"):
        build_review_budget_fields(loop, {})
