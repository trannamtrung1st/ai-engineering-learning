"""Tests for render publication reset heuristics."""

from __future__ import annotations

from top_down_planning.models import RenderStage, RenderState
from top_down_planning.render_flow import _should_reset_publication_state


def test_resume_in_progress_waves_without_reset() -> None:
    state = RenderState(
        stage=RenderStage.WAVES,
        plan_digest="a",
        output_goal_digest="b",
        render_config_digest="c",
    )
    assert not _should_reset_publication_state(
        state,
        plan_digest="a",
        output_goal_digest="b",
        render_config_digest="c",
        force_rerender=False,
    )


def test_force_rerender_always_resets() -> None:
    state = RenderState(stage=RenderStage.WAVES)
    assert _should_reset_publication_state(
        state,
        plan_digest="a",
        output_goal_digest="b",
        render_config_digest="c",
        force_rerender=True,
    )


def test_digest_mismatch_resets() -> None:
    state = RenderState(
        stage=RenderStage.WAVES,
        plan_digest="old",
        output_goal_digest="b",
        render_config_digest="c",
    )
    assert _should_reset_publication_state(
        state,
        plan_digest="new",
        output_goal_digest="b",
        render_config_digest="c",
        force_rerender=False,
    )
