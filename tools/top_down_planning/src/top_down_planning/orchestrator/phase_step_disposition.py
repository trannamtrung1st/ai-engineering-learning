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
    if bool(getattr(result, "ok", False)):
        return PhaseStepDisposition.ADVANCED
    return PhaseStepDisposition.STOPPED


__all__ = [
    "PhaseStepDisposition",
    "disposition_from_phase_result",
]
