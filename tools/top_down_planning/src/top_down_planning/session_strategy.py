"""Planning mode and session strategy resolution."""

from __future__ import annotations

from top_down_planning.input_loader import LoadedInput, LoadedOutputGoal, LoadedStopHint
from top_down_planning.models import PlanningMode, ReviewCheckpoint, SessionStrategy


def default_session_strategy() -> SessionStrategy:
    return SessionStrategy()


def resolve_session_strategy(
    strategy: SessionStrategy | None,
    *,
    planning_mode: PlanningMode,
) -> SessionStrategy:
    base = strategy.model_copy(deep=True) if strategy is not None else default_session_strategy()
    if planning_mode == PlanningMode.SIMPLE:
        base.review_checkpoints = []
        base.final_adversarial_review = False
        return base
    if planning_mode == PlanningMode.LIGHTWEIGHT:
        base.review_checkpoints = [ReviewCheckpoint.FINAL_CANDIDATE]
        base.final_adversarial_review = True
        return base
    return base


def resolve_planning_mode(
    requested: PlanningMode,
    *,
    loaded_input: LoadedInput,
    output_goal: LoadedOutputGoal,
    stop_hint: LoadedStopHint | None,
) -> PlanningMode:
    if requested != PlanningMode.AUTO:
        return requested
    text = "\n".join(
        [
            loaded_input.text,
            output_goal.text,
            stop_hint.text if stop_hint is not None else "",
        ]
    ).lower()
    signals = 0
    if len(text) > 6000:
        signals += 1
    if any(
        marker in text
        for marker in (
            "migration",
            "architecture",
            "cross-cutting",
            "multiple teams",
            "hard cutover",
        )
    ):
        signals += 2
    if signals >= 2:
        return PlanningMode.FULL
    if signals == 1:
        return PlanningMode.LIGHTWEIGHT
    return PlanningMode.SIMPLE


def checkpoint_enabled(
    strategy: SessionStrategy,
    checkpoint: ReviewCheckpoint,
) -> bool:
    return checkpoint in strategy.review_checkpoints
