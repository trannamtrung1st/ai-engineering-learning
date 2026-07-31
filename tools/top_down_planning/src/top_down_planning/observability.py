"""Top Down Planning observability bridges and wiring."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

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
from core_tools.provider.events import is_tool_call_end, is_tool_call_start
from top_down_planning.persistence.interface import RunStore


def cancel_console_event(*, run_id: str, phase: str) -> ConsoleEvent:
    """Console event emitted when the user interrupts a blocking run."""

    return ConsoleEvent(
        category="session:cancel",
        message=(
            f"Run cancelled by user during {phase} "
            f"(agent sessions stopped; resume with `tdp resume --run {run_id}`)."
        ),
        fields={"phase": phase},
        run_id=run_id,
    )


_SESSION_START_EVENT_TYPES = frozenset(
    {
        "planner_session_started",
        "producer_session_started",
        "reviewer_session_started",
    }
)

_SESSION_RESUME_EVENT_TYPES = frozenset(
    {
        "planner_session_resumed",
        "producer_session_resumed",
        "reviewer_session_resumed",
    }
)


def session_lifecycle_event(
    *,
    category: Literal["session:start", "session:end", "session:resume"],
    role: str,
    phase: str,
    session_id: str,
    run_id: str | None = None,
    **extra_fields: Any,
) -> ConsoleEvent:
    """Build a consistent agent session start/end console event."""

    if category == "session:resume":
        verb = "resumed"
    else:
        verb = "started" if category == "session:start" else "ended"
    fields: dict[str, Any] = {"phase": phase, "role": role, **extra_fields}
    if run_id is not None:
        fields.setdefault("run_id", run_id)
    return ConsoleEvent(
        category=category,
        message=f"{role} session {verb}",
        fields=fields,
        run_id=run_id,
        session_id=session_id,
    )


@dataclass
class ObservabilityOptions:
    """Runtime observability configuration."""

    log_level: LogLevel = "normal"
    log_format: str = "console"
    color: str = "auto"
    show_timestamps: bool = False
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
        self._agent_text = AgentTextStreamController()
        self._seen_tool_starts: set[str] = set()
        self._seen_tool_ends: set[str] = set()

    def handle(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "")
        session_id = event.get("session_id")
        session = str(session_id) if session_id else None
        if event_type == "thinking":
            self._emit_delta(
                "thinking",
                self._agent_text.ingest_thinking(str(event.get("text") or "")),
                session_id=session,
            )
            return
        if event_type == "assistant":
            self._emit_delta(
                "response",
                self._agent_text.ingest_response(str(event.get("text") or "")),
                session_id=session,
            )
            return
        if event_type == "tool_call":
            if is_tool_call_start(event):
                self._agent_text.reset_turn_buffers()
                self._emit_tool_event("tool:start", event, session_id=session)
            elif is_tool_call_end(event):
                self._emit_tool_event("tool:end", event, session_id=session)
            return
        if event_type == "retry":
            fields = self._provider_fields(event)
            fields.update(
                {
                    "attempt": event.get("attempt"),
                    "max_retries": event.get("max_retries"),
                }
            )
            self._context.emit(
                ConsoleEvent(
                    category="retry",
                    message=str(event.get("text") or "provider retry"),
                    fields=fields,
                )
            )
            return
        if event_type == "error":
            self._context.emit(
                ConsoleEvent(
                    category="error",
                    message=str(event.get("text") or "provider error"),
                    session_id=session,
                    fields=self._provider_fields(event),
                )
            )
            return
        if event_type == "done":
            self._agent_text.reset_turn_buffers()
            self._seen_tool_starts.clear()
            self._seen_tool_ends.clear()
            if event.get("is_error"):
                self._context.emit(
                    ConsoleEvent(
                        category="error",
                        message=str(event.get("text") or "provider turn failed"),
                        session_id=session,
                        fields=self._provider_fields(event),
                    )
                )
            return

    def _provider_fields(self, event: dict[str, Any]) -> dict[str, str]:
        model = event.get("model")
        if isinstance(model, str) and model:
            return {"model": model}
        return {}

    def _emit_delta(
        self,
        category: str,
        delta: str,
        *,
        session_id: str | None,
    ) -> None:
        if not delta:
            return
        self._context.emit(
            ConsoleEvent(
                category=category,
                message=delta,
                session_id=session_id,
            )
        )

    def _emit_tool_event(
        self,
        category: str,
        event: dict[str, Any],
        *,
        session_id: str | None,
    ) -> None:
        summary = str(event.get("summary") or "")
        if not summary:
            return
        key = _tool_call_key(event, summary)
        seen = self._seen_tool_starts if category == "tool:start" else self._seen_tool_ends
        if key in seen:
            return
        seen.add(key)
        self._context.emit(
            ConsoleEvent(
                category=category,
                message=summary,
                session_id=session_id,
                fields=self._provider_fields(event),
            )
        )


def _tool_call_key(event: dict[str, Any], summary: str) -> str:
    call_id = event.get("call_id")
    if call_id:
        return f"call:{call_id}"
    return f"summary:{summary}"


def map_audit_event(payload: dict[str, Any]) -> ConsoleEvent | None:
    """Map a persisted audit event to a console event."""

    event_type = str(payload.get("type") or "")
    fields = {k: v for k, v in payload.items() if k not in {"type", "ts", "txn_id"}}

    if event_type in _SESSION_START_EVENT_TYPES:
        session_id = fields.get("session_id")
        role = fields.get("role")
        phase = fields.get("phase")
        if not all(isinstance(value, str) and value for value in (session_id, role, phase)):
            return None
        run_id = fields.get("run_id")
        extra = {
            k: v
            for k, v in fields.items()
            if k not in {"session_id", "role", "phase", "run_id"}
        }
        return session_lifecycle_event(
            category="session:start",
            role=role,
            phase=phase,
            session_id=session_id,
            run_id=str(run_id) if isinstance(run_id, str) else None,
            **extra,
        )

    if event_type in _SESSION_RESUME_EVENT_TYPES:
        session_id = fields.get("session_id")
        role = fields.get("role")
        phase = fields.get("phase")
        if not all(isinstance(value, str) and value for value in (session_id, role, phase)):
            return None
        run_id = fields.get("run_id")
        extra = {
            k: v
            for k, v in fields.items()
            if k not in {"session_id", "role", "phase", "run_id"}
        }
        return session_lifecycle_event(
            category="session:resume",
            role=role,
            phase=phase,
            session_id=session_id,
            run_id=str(run_id) if isinstance(run_id, str) else None,
            **extra,
        )

    mapping: dict[str, tuple[str, str]] = {
        "run_created": ("run:start", "run created"),
        "production_phase_started": ("phase:start", "production phase started"),
        "production_completed": ("phase:end", "production completed"),
        "production_failed": ("error", "production failed"),
        "planning_candidate_ready": ("state", "planning candidate ready"),
        "planning_expansion_recorded": ("state", "planning expansion recorded"),
        "planning_limit_exceeded": ("warning", "planning limit exceeded"),
        "focused_review_approved": ("review", "focused review approved"),
        "focused_review_failed": ("review", "focused review failed"),
        "phase_entry_attempted": ("state", "phase entry attempted"),
        "phase_entry_blocked": ("error", "phase entry blocked"),
        "context_snapshot_rebased": ("state", "context snapshot rebased"),
        "context_snapshot_collected": ("state", "context snapshot collected"),
        "whole_plan_review_started": ("phase:start", "whole plan review started"),
        "whole_plan_blocker_review_started": ("phase:start", "whole plan blocker review started"),
        "whole_plan_review_approved": ("review", "whole plan review approved"),
        "whole_plan_review_failed": ("error", "whole plan review failed"),
        "whole_output_review_started": ("phase:start", "whole output review started"),
        "whole_output_blocker_review_started": (
            "phase:start",
            "whole output blocker review started",
        ),
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
    if event_type == "context_snapshot_collected":
        summary = fields.get("summary")
        if isinstance(summary, str) and summary.strip():
            # Concise multi-line summary stays in fields; console uses first line.
            message = summary.splitlines()[0]
    session_id = fields.get("session_id")
    run_id = fields.get("run_id")
    return ConsoleEvent(
        category=category,
        message=message,
        fields=fields,
        run_id=str(run_id) if isinstance(run_id, str) else None,
        session_id=str(session_id) if isinstance(session_id, str) else None,
    )


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
