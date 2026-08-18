"""Validate agent CLI request payloads against published schemas."""

from __future__ import annotations

from typing import Any

from core_tools.schema import validate_against_schema

from top_down_planning.agent_tool.errors import RequestError

_OPERATION_SCHEMAS: dict[str, str] = {
    "plan_apply": "plan-transaction",
    "production_apply": "production-apply",
    "production_request_amendment": "amendment-request",
    "production_submit_completion": "completion-claim",
    "production_report_blocked": "blocker-report",
    "review_respond": "review-respond",
    "review_record_finding_actions": "review-record-finding-actions",
    "review_request": "focused-review-request",
}


def validate_agent_request(operation: str, request: dict[str, Any]) -> None:
    """Raise RequestError when request does not match the operation schema."""

    from top_down_planning.schema_docs import SCHEMAS

    schema_name = _OPERATION_SCHEMAS.get(operation)
    if schema_name is None:
        raise RequestError(f"unknown agent operation for schema validation: {operation!r}")

    schema = SCHEMAS.get(schema_name)
    if schema is None:
        raise RequestError(f"missing schema definition: {schema_name!r}")

    issues = validate_against_schema(request, schema)
    if issues:
        raise RequestError("; ".join(issues))


__all__ = ["validate_agent_request"]
