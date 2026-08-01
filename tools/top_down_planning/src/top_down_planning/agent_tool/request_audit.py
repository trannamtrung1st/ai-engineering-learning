"""Agent request read/completion audit events and request consumption."""

from __future__ import annotations

import hashlib
import json
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core_tools.persistence import load_yaml

from top_down_planning.agent_tool.errors import (
    AgentToolError,
    CapabilityDeniedError,
    OperationError,
    RequestError,
    RevisionConflictError,
)
from top_down_planning.agent_tool.request_paths import (
    assert_run_id_env_matches,
    classify_request_source,
    resolve_request_path,
)
from top_down_planning.persistence.interface import RunStore

RequestResult = str  # applied | rejected | failed


@dataclass(frozen=True)
class AgentRequestContext:
    request_id: str
    operation: str
    source_kind: str
    source: str
    sha256: str
    size_bytes: int


def new_request_id() -> str:
    return f"req-{uuid.uuid4()}"


def _parse_structured_text(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        return load_yaml(text)
    except ValueError as exc:
        raise RequestError(f"failed to parse request body: {exc}") from exc


def _read_stdin_bytes(stdin: Any | None) -> bytes:
    stream = stdin if stdin is not None else sys.stdin
    data = stream.read()
    if isinstance(data, str):
        return data.encode("utf-8")
    return bytes(data)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def emit_agent_request_read(
    store: RunStore,
    run_id: str,
    context: AgentRequestContext,
) -> None:
    store.append_event(
        run_id,
        {
            "type": "agent_request_read",
            "run_id": run_id,
            "request_id": context.request_id,
            "operation": context.operation,
            "source_kind": context.source_kind,
            "source": context.source,
            "sha256": context.sha256,
            "size_bytes": context.size_bytes,
        },
    )


def complete_agent_request(
    store: RunStore,
    run_id: str,
    context: AgentRequestContext,
    *,
    result: RequestResult,
) -> None:
    store.append_event(
        run_id,
        {
            "type": "agent_request_completed",
            "run_id": run_id,
            "request_id": context.request_id,
            "operation": context.operation,
            "sha256": context.sha256,
            "result": result,
        },
    )


def map_exception_to_result(exc: BaseException) -> RequestResult:
    if isinstance(
        exc,
        (
            RequestError,
            CapabilityDeniedError,
            RevisionConflictError,
            OperationError,
        ),
    ):
        return "rejected"
    return "failed"


def map_response_to_result(response: dict[str, Any]) -> RequestResult:
    if response.get("ok") is True:
        return "applied"
    return "rejected"


def apply_request_audit_fields(
    event: dict[str, Any],
    request_audit: AgentRequestContext | None,
) -> dict[str, Any]:
    if request_audit is None:
        return event
    updated = dict(event)
    updated["request_id"] = request_audit.request_id
    updated["request_sha256"] = request_audit.sha256
    return updated


def _attach_request_context(exc: RequestError, context: AgentRequestContext) -> None:
    exc.request_context = context  # type: ignore[attr-defined]


def consume_agent_request(
    store: RunStore,
    run_id: str,
    *,
    operation: str,
    request_path: str | None = None,
    stdin: Any | None = None,
    capability_token: str | None = None,
) -> tuple[dict[str, Any], AgentRequestContext]:
    """Read, hash, audit, and parse a mutating agent request."""

    assert_run_id_env_matches(run_id, capability_token=capability_token)
    agent_requests_dir = store.agent_requests_dir(run_id)

    resolved_path: Path | None = None
    if request_path:
        resolved_path = resolve_request_path(
            request_path,
            agent_requests_dir=agent_requests_dir,
        )

    if resolved_path is not None:
        raw_bytes = resolved_path.read_bytes()
    else:
        raw_bytes = _read_stdin_bytes(stdin)

    source_kind, source = classify_request_source(
        resolved_path,
        agent_requests_dir=agent_requests_dir,
    )

    context = AgentRequestContext(
        request_id=new_request_id(),
        operation=operation,
        source_kind=source_kind,
        source=source,
        sha256=_sha256_hex(raw_bytes),
        size_bytes=len(raw_bytes),
    )
    emit_agent_request_read(store, run_id, context)

    if not raw_bytes.strip():
        exc = RequestError(
            "request body is empty; provide JSON or YAML via stdin or --request"
        )
        _attach_request_context(exc, context)
        raise exc

    try:
        text = raw_bytes.decode("utf-8").strip()
        payload = _parse_structured_text(text)
        if not isinstance(payload, dict):
            raise RequestError("request body must be a JSON or YAML object")
        return payload, context
    except RequestError as exc:
        _attach_request_context(exc, context)
        raise
    except UnicodeDecodeError as exc:
        error = RequestError(f"request body is not valid UTF-8: {exc}")
        _attach_request_context(error, context)
        raise error from exc


__all__ = [
    "AgentRequestContext",
    "RequestResult",
    "apply_request_audit_fields",
    "complete_agent_request",
    "consume_agent_request",
    "emit_agent_request_read",
    "map_exception_to_result",
    "map_response_to_result",
    "new_request_id",
]
