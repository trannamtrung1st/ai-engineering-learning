"""Top Down Planning observability bridges and wiring."""

from __future__ import annotations

import time
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core_tools.observability import (
    AgentTextStreamController,
    ColorizedConsoleSink,
    CompositeSink,
    ConsoleEvent,
    EventSink,
    FilteredSink,
    JsonlEventSink,
    LogLevel,
    NullSink,
)
from top_down_planning.persistence.interface import RunStore

@dataclass
class ObservabilityOptions:
    """Runtime observability configuration."""

    log_level: LogLevel = "normal"
    log_format: str = "console"
    color: str = "auto"
    show_timestamps: bool = True
    no_agent_text: bool = False
    agent_transcript: bool = False


@dataclass
class ObservabilityContext:
    """Active observability sinks and bridges for a CLI run."""

    sink: EventSink = field(default_factory=NullSink)
    options: ObservabilityOptions = field(default_factory=ObservabilityOptions)
    run_id: str | None = None
    _provider_bridge: ProviderToConsoleBridge | None = field(default=None, repr=False)
    _jsonl_sink: JsonlEventSink | None = field(default=None, repr=False)
    _transcript_sink: JsonlEventSink | None = field(default=None, repr=False)

    def emit(self, event: ConsoleEvent) -> None:
        if self.run_id and event.run_id is None:
            event = ConsoleEvent(
                category=event.category,
                message=event.message,
                ts=event.ts,
                fields=dict(event.fields),
                level=event.level,
                run_id=self.run_id,
                session_id=event.session_id,
            )
        self.sink.emit(event)

    def provider_callback(self) -> Any:
        bridge = self._ensure_provider_bridge()
        return bridge.handle

    def close(self) -> None:
        if self._jsonl_sink is not None:
            self._jsonl_sink.close()
        if self._transcript_sink is not None:
            self._transcript_sink.close()

    def _ensure_provider_bridge(self) -> ProviderToConsoleBridge:
        if self._provider_bridge is None:
            self._provider_bridge = ProviderToConsoleBridge(self)
        return self._provider_bridge


def build_observability_context(
    *,
    options: ObservabilityOptions,
    run_id: str | None = None,
    run_dir: Path | None = None,
) -> ObservabilityContext:
    """Construct filtered sinks for a CLI invocation."""

    sinks: list[EventSink] = []
    jsonl_sink: JsonlEventSink | None = None
    transcript_sink: JsonlEventSink | None = None

    if options.log_format == "jsonl":
        jsonl_sink = JsonlEventSink(sys.stderr, log_level=options.log_level)
        sinks.append(jsonl_sink)
    else:
        sinks.append(
            ColorizedConsoleSink(
                color=options.color,  # type: ignore[arg-type]
                show_timestamps=options.show_timestamps,
                log_level=options.log_level,
            )
        )

    if options.agent_transcript and run_dir is not None:
        transcript_sink = JsonlEventSink(
            run_dir / "agent-transcript.jsonl",
            log_level=options.log_level,
        )
        sinks.append(
            FilteredSink(
                transcript_sink,
                log_level="trace",
                allowed_categories=frozenset(
                    {
                        "thinking",
                        "response",
                        "tool:start",
                        "tool:end",
                        "tool:error",
                        "retry",
                        "error",
                    }
                ),
            )
        )

    composite = CompositeSink(*sinks) if sinks else NullSink()
    filtered = FilteredSink(
        composite,
        log_level=options.log_level,
        no_agent_text=options.no_agent_text,
    )
    return ObservabilityContext(
        sink=filtered,
        options=options,
        run_id=run_id,
        _jsonl_sink=jsonl_sink,
        _transcript_sink=transcript_sink,
    )


class ProviderToConsoleBridge:
    """Map normalized provider events to ConsoleEvents."""

    def __init__(self, context: ObservabilityContext) -> None:
        self._context = context
        self._tool_starts: dict[str, tuple[float, str]] = {}
        self._agent_text = AgentTextStreamController()

    def handle(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "")
        session_id = event.get("session_id")
        session = str(session_id) if session_id else None
        if event_type == "thinking":
            self._emit_sentences(
                "thinking",
                self._agent_text.ingest_thinking(str(event.get("text") or "")),
                session_id=session,
            )
            return
        if event_type == "assistant":
            flushed_thinking, response = self._agent_text.ingest_response(
                str(event.get("text") or "")
            )
            self._emit_sentences("thinking", flushed_thinking, session_id=session)
            self._emit_sentences("response", response, session_id=session)
            return
        if event_type == "tool_call":
            flushed_thinking, flushed_response = self._agent_text.flush_for_tool_call()
            self._emit_sentences("thinking", flushed_thinking, session_id=session)
            self._emit_sentences("response", flushed_response, session_id=session)
            call_id = str(event.get("call_id") or f"call-{len(self._tool_starts) + 1}")
            tool_name = str(event.get("tool") or "tool")
            self._tool_starts[call_id] = (time.monotonic(), tool_name)
            self._context.emit(
                ConsoleEvent(
                    category="tool:start",
                    message=tool_name,
                    session_id=session,
                    fields=_tool_start_fields(event, call_id=call_id),
                )
            )
            return
        if event_type == "tool_result":
            call_id = str(event.get("call_id") or "")
            started = self._tool_starts.pop(call_id, None)
            duration_ms = _duration_ms(started[0] if started else None)
            ok = event.get("ok")
            if ok is None:
                ok = not bool(event.get("is_error"))
            category = "tool:end" if ok else "tool:error"
            self._context.emit(
                ConsoleEvent(
                    category=category,
                    message=str(event.get("tool") or "tool"),
                    session_id=session,
                    fields=_tool_end_fields(event, call_id=call_id, duration_ms=duration_ms, ok=bool(ok)),
                )
            )
            return
        if event_type == "retry":
            self._context.emit(
                ConsoleEvent(
                    category="retry",
                    message=str(event.get("text") or "provider retry"),
                    fields={
                        "attempt": event.get("attempt"),
                        "max_retries": event.get("max_retries"),
                    },
                )
            )
            return
        if event_type == "error":
            self._context.emit(
                ConsoleEvent(
                    category="error",
                    message=str(event.get("text") or "provider error"),
                    session_id=session,
                )
            )
            return
        if event_type == "done":
            flushed_thinking, flushed_response = self._agent_text.flush_for_done()
            self._emit_sentences("thinking", flushed_thinking, session_id=session)
            self._emit_sentences("response", flushed_response, session_id=session)
            if event.get("is_error"):
                self._context.emit(
                    ConsoleEvent(
                        category="error",
                        message=str(event.get("text") or "provider turn failed"),
                        session_id=session,
                    )
                )
            else:
                self._flush_open_tools(ok=True)
            return

    def _emit_sentences(
        self,
        category: str,
        sentences: list[str],
        *,
        session_id: str | None,
    ) -> None:
        for sentence in sentences:
            self._context.emit(
                ConsoleEvent(
                    category=category,
                    message=sentence,
                    session_id=session_id,
                )
            )

    def _flush_open_tools(self, *, ok: bool) -> None:
        for call_id, (started_at, tool_name) in list(self._tool_starts.items()):
            self._tool_starts.pop(call_id, None)
            self._context.emit(
                ConsoleEvent(
                    category="tool:end" if ok else "tool:error",
                    message=tool_name,
                    fields={
                        "call_id": call_id,
                        "ok": ok,
                        "duration_ms": _duration_ms(started_at),
                    },
                )
            )

def map_audit_event(payload: dict[str, Any]) -> ConsoleEvent | None:
    """Map a persisted audit event to a console event."""

    event_type = str(payload.get("type") or "")
    fields = {k: v for k, v in payload.items() if k not in {"type", "ts", "txn_id"}}

    mapping: dict[str, tuple[str, str]] = {
        "run_created": ("session:start", "run created"),
        "planner_session_started": ("session:start", "planner session started"),
        "producer_session_started": ("session:start", "producer session started"),
        "reviewer_session_started": ("session:start", "reviewer session started"),
        "production_phase_started": ("phase:start", "production phase started"),
        "production_completed": ("phase:end", "production completed"),
        "production_failed": ("error", "production failed"),
        "planning_candidate_ready": ("state", "planning candidate ready"),
        "planning_expansion_recorded": ("state", "planning expansion recorded"),
        "planning_limit_exceeded": ("warning", "planning limit exceeded"),
        "focused_review_started": ("review", "focused review started"),
        "focused_review_approved": ("review", "focused review approved"),
        "focused_review_failed": ("review", "focused review failed"),
        "whole_plan_review_started": ("phase:start", "whole plan review started"),
        "whole_plan_review_approved": ("review", "whole plan review approved"),
        "whole_plan_review_failed": ("error", "whole plan review failed"),
        "whole_output_review_started": ("phase:start", "whole output review started"),
        "whole_output_review_approved": ("review", "whole output review approved"),
        "whole_output_review_failed": ("error", "whole output review failed"),
        "plan_amendment_started": ("phase:start", "plan amendment started"),
        "plan_amendment_revision_ready": ("state", "plan amendment revision ready"),
        "plan_amendment_production_resumed": ("phase:end", "production resumed after amendment"),
        "plan_amendment_completed": ("phase:end", "plan amendment completed"),
        "plan_amendment_failed": ("error", "plan amendment failed"),
        "outcome_resolved": ("state", "outcome resolved"),
        "run_failed": ("error", "run failed"),
    }
    mapped = mapping.get(event_type)
    if mapped is None:
        return None
    category, message = mapped
    return ConsoleEvent(category=category, message=message, fields=fields)


class ObservingRunStore:
    """RunStore decorator that mirrors append_event calls to observability."""

    def __init__(self, store: RunStore, context: ObservabilityContext) -> None:
        self._store = store
        self._context = context

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)

    def append_event(self, run_id: str, event: dict[str, Any]) -> None:
        self._store.append_event(run_id, event)
        mapped = map_audit_event(event)
        if mapped is not None:
            self._context.emit(
                ConsoleEvent(
                    category=mapped.category,
                    message=mapped.message,
                    fields=mapped.fields,
                    level=mapped.level,
                    run_id=run_id,
                    session_id=mapped.session_id,
                )
            )


def wrap_store_with_observability(
    store: RunStore,
    context: ObservabilityContext,
) -> RunStore:
    """Mirror append_event audit records to the active observability sink."""

    if isinstance(store, ObservingRunStore):
        return store
    return ObservingRunStore(store, context)


def _tool_start_fields(event: dict[str, Any], *, call_id: str) -> dict[str, Any]:
    fields: dict[str, Any] = {"call_id": call_id}
    tool = event.get("tool")
    if tool:
        fields["tool"] = tool
    request = event.get("request")
    if isinstance(request, dict):
        if "base_revision" in request:
            fields["base_revision"] = request["base_revision"]
        operations = request.get("operations")
        if isinstance(operations, list):
            fields["operations"] = len(operations)
        if "loop_id" in request:
            fields["loop_id"] = request["loop_id"]
        if "review_type" in request:
            fields["review_type"] = request["review_type"]
    return fields


def _tool_end_fields(
    event: dict[str, Any],
    *,
    call_id: str,
    duration_ms: int | None,
    ok: bool,
) -> dict[str, Any]:
    fields: dict[str, Any] = {"ok": ok}
    if call_id:
        fields["call_id"] = call_id
    tool = event.get("tool")
    if tool:
        fields["tool"] = tool
    if duration_ms is not None:
        fields["duration_ms"] = duration_ms
    if event.get("duration_ms") is not None:
        fields["duration_ms"] = int(event["duration_ms"])
    return fields


def _duration_ms(started_at: float | None) -> int | None:
    if started_at is None:
        return None
    return int((time.monotonic() - started_at) * 1000)