from top_down_planning.models import RenderStage, RenderState
from top_down_planning.render_flow import _should_reset_render_state


def test_force_rerender_always_resets() -> None:
    state = RenderState(stage=RenderStage.COMPLETE)
    assert _should_reset_render_state(
        state,
        plan_digest="a",
        output_goal_digest="b",
        render_config_digest="c",
        force_rerender=True,
    )


def test_complete_render_without_force_does_not_reset() -> None:
    state = RenderState(
        stage=RenderStage.COMPLETE,
        plan_digest="a",
        output_goal_digest="b",
        render_config_digest="c",
    )
    assert not _should_reset_render_state(
        state,
        plan_digest="a",
        output_goal_digest="b",
        render_config_digest="c",
        force_rerender=False,
    )


def test_in_progress_render_without_force_does_not_reset() -> None:
    for stage in (RenderStage.SCAFFOLD, RenderStage.BATCHES, RenderStage.FINAL_REVIEW):
        state = RenderState(
            stage=stage,
            plan_digest="a",
            output_goal_digest="b",
            render_config_digest="c",
            current_batch_index=1,
        )
        assert not _should_reset_render_state(
            state,
            plan_digest="a",
            output_goal_digest="b",
            render_config_digest="c",
            force_rerender=False,
        )
