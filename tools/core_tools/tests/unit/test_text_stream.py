"""Unit tests for agent text streaming helpers."""

from __future__ import annotations

from core_tools.observability.text_stream import (
    AgentTextStreamBuffer,
    AgentTextStreamController,
    normalize_text_delta,
    pop_complete_sentences,
)


def test_normalize_text_delta_handles_cumulative_text() -> None:
    cumulative, delta = normalize_text_delta("Hello", "Hello world")
    assert cumulative == "Hello world"
    assert delta == " world"


def test_pop_complete_sentences_splits_on_punctuation() -> None:
    sentences, remainder = pop_complete_sentences("First sentence. Still typing")
    assert sentences == ["First sentence."]
    assert remainder == "Still typing"


def test_agent_text_stream_buffer_emits_complete_sentences() -> None:
    buffer = AgentTextStreamBuffer()
    assert buffer.ingest("Hello") == []
    assert buffer.ingest("Hello world. Next") == ["Hello world."]
    assert buffer.flush() == ["Next"]


def test_agent_text_stream_buffer_dedupes_cumulative_chunks() -> None:
    buffer = AgentTextStreamBuffer()
    assert buffer.ingest("Beginning work:") == []
    assert buffer.ingest("Beginning work: installing") == []
    flushed = buffer.flush()
    assert flushed == ["Beginning work: installing"]


def test_agent_text_stream_controller_flushes_on_tool_call() -> None:
    controller = AgentTextStreamController()
    controller.ingest_thinking("Still planning")
    controller.response.ingest("Partial reply")
    flushed_thinking, flushed_response = controller.flush_for_tool_call()
    assert flushed_thinking == ["Still planning"]
    assert flushed_response == ["Partial reply"]
