"""Extract and validate structured review decisions."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from todos_tool.errors import ReviewError
from todos_tool.models import ReviewDecision, TodoItem

FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
JSON_OBJECT_RE = re.compile(r"\{(?:[^{}]|(?:\{[^{}]*\}))*\}", re.DOTALL)


def extract_json_objects(text: str) -> list[dict[str, Any]]:
    """Extract candidate JSON objects from assistant text."""
    candidates: list[dict[str, Any]] = []
    for match in FENCE_RE.finditer(text):
        try:
            obj = json.loads(match.group(1))
            if isinstance(obj, dict):
                candidates.append(obj)
        except json.JSONDecodeError:
            continue

    # Also try last brace-balanced object
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(text):
        start = text.find("{", idx)
        if start < 0:
            break
        try:
            obj, end = decoder.raw_decode(text[start:])
            if isinstance(obj, dict) and "decision" in obj:
                candidates.append(obj)
            idx = start + end
        except json.JSONDecodeError:
            idx = start + 1
    return candidates


def parse_review_decision(text: str) -> ReviewDecision:
    candidates = extract_json_objects(text)
    if not candidates:
        raise ReviewError("No JSON review decision found in session output")

    # Prefer the last candidate that looks like a review decision
    last_error: Exception | None = None
    for obj in reversed(candidates):
        if "decision" not in obj and "schema_version" not in obj:
            continue
        try:
            return ReviewDecision.model_validate(obj)
        except PydanticValidationError as exc:
            last_error = exc
            continue
    if last_error:
        raise ReviewError(f"Malformed review decision: {last_error}") from last_error
    raise ReviewError("No valid review decision JSON found")


def validate_pass(
    decision: ReviewDecision,
    item: TodoItem,
    logical_attempt: int,
) -> None:
    """Raise ReviewError if a claimed pass is not actually valid."""
    if decision.item_id != item.id:
        raise ReviewError(
            f"Review item_id mismatch: got {decision.item_id}, expected {item.id}"
        )
    if decision.logical_attempt != logical_attempt:
        raise ReviewError(
            f"Review logical_attempt mismatch: got {decision.logical_attempt}, "
            f"expected {logical_attempt}"
        )

    if decision.decision != "pass":
        return

    if not decision.acceptance_criteria:
        raise ReviewError("Pass requires acceptance_criteria results")

    expected = {c.strip() for c in item.acceptance_criteria}
    reported = {c.criterion.strip() for c in decision.acceptance_criteria}
    if not expected.issubset(reported) and len(decision.acceptance_criteria) < len(
        item.acceptance_criteria
    ):
        raise ReviewError("Pass missing acceptance criteria coverage")

    if not all(c.passed for c in decision.acceptance_criteria):
        raise ReviewError("Pass requires every acceptance criterion to pass")

    if item.validation.commands:
        if not decision.validation:
            raise ReviewError("Pass requires validation results for mandatory commands")
        if not all(v.passed for v in decision.validation):
            raise ReviewError("Pass requires all mandatory validation to pass")

    if not decision.instruction_compliance.passed:
        raise ReviewError("Pass requires instruction_compliance.passed=true")

    blocking = [issue.display() for issue in decision.issues if issue.is_blocking]
    if blocking:
        raise ReviewError(
            "Pass cannot have unresolved blocking issues: "
            + "; ".join(blocking)
        )

    if decision.recommended_next_action != "mark_done":
        raise ReviewError("Pass requires recommended_next_action=mark_done")


def accept_decision(
    decision: ReviewDecision,
    item: TodoItem,
    logical_attempt: int,
) -> ReviewDecision:
    validate_pass(decision, item, logical_attempt)
    return decision
