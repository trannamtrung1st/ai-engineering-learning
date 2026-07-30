"""Strict identifier validation and generation for run-store paths."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from core_tools.persistence import PersistenceError

_STORE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
RUN_ID_PATTERN = re.compile(r"^run-\d{8}T\d{6}-[0-9a-f]{6}$")


def new_run_id(*, now: datetime | None = None) -> str:
    """Return a lexicographically sortable run identifier."""

    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    else:
        moment = moment.astimezone(timezone.utc)
    suffix = uuid.uuid4().hex[:6]
    run_id = f"run-{moment.strftime('%Y%m%dT%H%M%S')}-{suffix}"
    return validate_run_id(run_id)


def validate_run_id(value: str) -> str:
    """Validate a run identifier in canonical ``run-YYYYMMDDTHHMMSS-<6hex>`` form."""

    validated = validate_store_id(value, label="run_id")
    if not RUN_ID_PATTERN.fullmatch(validated):
        raise PersistenceError(
            "run_id must match run-YYYYMMDDTHHMMSS-<6hex> (UTC timestamp + random suffix)"
        )
    return validated


def validate_store_id(value: str, *, label: str = "id") -> str:
    """Validate a user- or agent-supplied store identifier."""

    if not isinstance(value, str):
        raise PersistenceError(f"{label} must be a string")
    stripped = value.strip()
    if not stripped:
        raise PersistenceError(f"{label} must not be empty")
    if stripped != value:
        raise PersistenceError(f"{label} must not contain leading or trailing whitespace")
    if "/" in stripped or "\\" in stripped or ".." in stripped:
        raise PersistenceError(f"{label} must not contain path separators or '..'")
    if any(ord(char) < 32 for char in stripped):
        raise PersistenceError(f"{label} must not contain control characters")
    if not _STORE_ID_PATTERN.fullmatch(stripped):
        raise PersistenceError(
            f"{label} must match [A-Za-z0-9][A-Za-z0-9._-]{{0,127}}"
        )
    return stripped
