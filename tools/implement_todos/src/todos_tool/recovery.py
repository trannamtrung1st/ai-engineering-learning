"""Worker session replacement when continuity degrades."""

from __future__ import annotations

from todos_tool.models import RunState


def replace_worker_session(state: RunState) -> RunState:
    """Start a replacement worker chat from durable artifacts."""
    state.worker_chat_id = None
    state.continuity_check_pending = True
    state.worker_replacement_count += 1
    state.worker_session_count += 1
    return state


def should_replace_worker(
    state: RunState,
    *,
    max_replacements: int,
    scope_violation: bool = False,
) -> bool:
    if scope_violation and state.worker_replacement_count < max_replacements:
        return True
    return False


def can_continue_worker_corrections(
    state: RunState,
    *,
    max_corrections: int,
) -> bool:
    return state.worker_correction_count < max_corrections
