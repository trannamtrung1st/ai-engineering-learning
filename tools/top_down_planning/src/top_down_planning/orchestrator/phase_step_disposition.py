"""How a phase orchestrator step relates to outer run continuation."""

from __future__ import annotations

from enum import Enum
from typing import Any


class PhaseStepDisposition(str, Enum):
    """Classification of a single phase invocation outcome for the continuation loop."""

    ADVANCED = "advanced"
    """Phase invocation completed its local work successfully."""

    INTERNAL_HANDOFF = "internal_handoff"
    """Recoverable orchestration boundary; multi-step ``until`` may drive another step."""

    STOPPED = "stopped"
    """External block, durable pause/failure, or unsupported state — do not auto-continue."""


def disposition_from_phase_result(result: Any) -> PhaseStepDisposition:
    explicit = getattr(result, "disposition", None)
    if isinstance(explicit, PhaseStepDisposition):
        return explicit
    if explicit is None:
        if bool(getattr(result, "ok", False)):
            return PhaseStepDisposition.ADVANCED
        return PhaseStepDisposition.STOPPED
    return PhaseStepDisposition.STOPPED


def phase_result_handoff_loop_id(result: Any) -> str | None:
    loop_id = getattr(result, "handoff_loop_id", None)
    if loop_id is None:
        return None
    text = str(loop_id).strip()
    return text or None


__all__ = [
    "PhaseStepDisposition",
    "disposition_from_phase_result",
    "phase_result_handoff_loop_id",
]
