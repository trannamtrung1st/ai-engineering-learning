"""Incremental agent text streaming helpers."""

from __future__ import annotations

from dataclasses import dataclass, field


def normalize_text_delta(previous: str, text: str) -> tuple[str, str]:
    """Return updated cumulative text and the newly appended delta."""

    if not text:
        return previous, ""
    if previous and text.startswith(previous):
        return text, text[len(previous) :]
    return previous + text, text


@dataclass
class AgentTextStreamBuffer:
    """Accumulate provider text and emit only newly appended deltas."""

    cumulative: str = ""

    def ingest(self, text: str) -> str:
        if not text:
            return ""
        self.cumulative, delta = normalize_text_delta(self.cumulative, text)
        return delta

    def reset(self) -> None:
        self.cumulative = ""


@dataclass
class AgentTextStreamController:
    """Coordinate thinking/response delta streaming across provider turns."""

    thinking: AgentTextStreamBuffer = field(default_factory=AgentTextStreamBuffer)
    response: AgentTextStreamBuffer = field(default_factory=AgentTextStreamBuffer)

    def ingest_thinking(self, text: str) -> str:
        return self.thinking.ingest(text)

    def ingest_response(self, text: str) -> str:
        self.thinking.reset()
        return self.response.ingest(text)

    def reset_turn_buffers(self) -> None:
        self.thinking.reset()
        self.response.reset()
