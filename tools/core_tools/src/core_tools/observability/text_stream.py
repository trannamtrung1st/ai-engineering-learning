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


def pop_complete_sentences(buffer: str) -> tuple[list[str], str]:
    """Split leading complete sentences from a text buffer."""

    if not buffer:
        return [], ""

    sentences: list[str] = []
    start = 0
    index = 0
    length = len(buffer)

    while index < length:
        character = buffer[index]
        if character in ".!?…":
            end = index + 1
            while end < length and buffer[end] in "\"')`]}":
                end += 1
            if end >= length or buffer[end] in " \n\t\r":
                chunk = buffer[start:end].strip()
                if chunk:
                    sentences.append(chunk)
                while end < length and buffer[end] in " \n\t\r":
                    end += 1
                start = end
                index = end
                continue
        elif character == "\n":
            chunk = buffer[start:index].strip()
            if chunk:
                sentences.append(chunk)
            start = index + 1
        index += 1

    return sentences, buffer[start:]


@dataclass
class AgentTextStreamBuffer:
    """Accumulate provider text deltas and emit complete sentences."""

    cumulative: str = ""
    pending: str = ""

    def ingest(self, text: str) -> list[str]:
        if not text:
            return []
        self.cumulative, delta = normalize_text_delta(self.cumulative, text)
        if not delta:
            return []
        self.pending += delta
        sentences, self.pending = pop_complete_sentences(self.pending)
        return sentences

    def flush(self) -> list[str]:
        remaining = self.pending.strip()
        self.reset()
        if remaining:
            return [remaining]
        return []

    def reset(self) -> None:
        self.cumulative = ""
        self.pending = ""


@dataclass
class AgentTextStreamController:
    """Coordinate thinking/response sentence streaming across provider turns."""

    thinking: AgentTextStreamBuffer = field(default_factory=AgentTextStreamBuffer)
    response: AgentTextStreamBuffer = field(default_factory=AgentTextStreamBuffer)

    def ingest_thinking(self, text: str) -> list[str]:
        return self.thinking.ingest(text)

    def ingest_response(self, text: str) -> tuple[list[str], list[str]]:
        flushed_thinking = self.thinking.flush()
        response_sentences = self.response.ingest(text)
        return flushed_thinking, response_sentences

    def flush_for_tool_call(self) -> tuple[list[str], list[str]]:
        return self.thinking.flush(), self.response.flush()

    def flush_for_done(self) -> tuple[list[str], list[str]]:
        return self.thinking.flush(), self.response.flush()
