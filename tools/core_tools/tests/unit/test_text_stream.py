"""Unit tests for agent text streaming helpers."""

from __future__ import annotations

from core_tools.observability.text_stream import (
    AgentTextStreamBuffer,
    AgentTextStreamController,
    normalize_text_delta,
)


def test_normalize_text_delta_handles_cumulative_text() -> None:
    cumulative, delta = normalize_text_delta("Hello", "Hello world")
    assert cumulative == "Hello world"
    assert delta == " world"


def test_agent_text_stream_buffer_emits_incremental_deltas() -> None:
    buffer = AgentTextStreamBuffer()
    assert buffer.ingest("Hello") == "Hello"
    assert buffer.ingest("Hello world. Next") == " world. Next"
    buffer.reset()
    assert buffer.cumulative == ""


def test_agent_text_stream_buffer_dedupes_cumulative_chunks() -> None:
    buffer = AgentTextStreamBuffer()
    assert buffer.ingest("Beginning work:") == "Beginning work:"
    assert buffer.ingest("Beginning work: installing") == " installing"


def test_agent_text_stream_controller_resets_on_tool_call() -> None:
    controller = AgentTextStreamController()
    controller.ingest_thinking("Still planning")
    controller.response.ingest("Partial reply")
    controller.reset_turn_buffers()
    assert controller.thinking.cumulative == ""
    assert controller.response.cumulative == ""
