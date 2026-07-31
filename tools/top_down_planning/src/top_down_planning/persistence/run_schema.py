"""Run-record schema version gate (proposal §3)."""

from __future__ import annotations

from typing import Any

from core_tools.persistence import PersistenceError

# Versions the complete persisted run-record contract, including nested
# context snapshot bindings. Independent of config document ``version``.
CURRENT_RUN_SCHEMA_VERSION = 2

UNSUPPORTED_RUN_SCHEMA_MESSAGE = (
    "Unsupported run schema version. Recreate the run using the current TDP version."
)


class UnsupportedRunSchemaVersionError(PersistenceError):
    """Persisted run.json uses a missing or unsupported schema_version."""

    def __init__(self, message: str = UNSUPPORTED_RUN_SCHEMA_MESSAGE) -> None:
        super().__init__(message)


def validate_run_schema_version(payload: dict[str, Any]) -> int:
    """Validate top-level run ``schema_version`` before nested field use.

    Missing or unsupported values fail at this boundary with the recreate
    message so callers do not surface incidental nested-field errors first.
    """

    if "schema_version" not in payload:
        raise UnsupportedRunSchemaVersionError(UNSUPPORTED_RUN_SCHEMA_MESSAGE)

    raw = payload["schema_version"]
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise UnsupportedRunSchemaVersionError(UNSUPPORTED_RUN_SCHEMA_MESSAGE)
    if raw != CURRENT_RUN_SCHEMA_VERSION:
        raise UnsupportedRunSchemaVersionError(UNSUPPORTED_RUN_SCHEMA_MESSAGE)
    return raw


__all__ = [
    "CURRENT_RUN_SCHEMA_VERSION",
    "UNSUPPORTED_RUN_SCHEMA_MESSAGE",
    "UnsupportedRunSchemaVersionError",
    "validate_run_schema_version",
]
