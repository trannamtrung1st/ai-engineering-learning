"""Run-record schema version gate (proposal §3)."""

from __future__ import annotations

from typing import Any

from core_tools.persistence import PersistenceError

# Versions the complete persisted run-record contract, including nested
# context snapshot bindings. Independent of config document ``version``.
CURRENT_RUN_SCHEMA_VERSION = 3

UNSUPPORTED_RUN_SCHEMA_MESSAGE = (
    "Unsupported run schema version. Recreate the run using the current TDP version."
)

_REQUIRED_V3_DIGEST_KEYS = frozenset({"config_contract", "config_execution"})


class UnsupportedRunSchemaVersionError(PersistenceError):
    """Persisted run.json uses a missing or unsupported schema_version."""

    code = "unsupported_run_schema"

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


def validate_run_digests(payload: dict[str, Any]) -> None:
    """Validate v3 run digest fields before nested digest interpretation."""

    digests = payload.get("digests")
    if not isinstance(digests, dict):
        raise PersistenceError("digests must be an object on schema v3 run records")
    if "config" in digests:
        raise PersistenceError(
            "digests.config is not supported on schema v3; use config_contract and config_execution"
        )
    for key in _REQUIRED_V3_DIGEST_KEYS:
        value = digests.get(key)
        if not value or not str(value).strip():
            raise PersistenceError(f"digests.{key} is required on schema v3 run records")


__all__ = [
    "CURRENT_RUN_SCHEMA_VERSION",
    "UNSUPPORTED_RUN_SCHEMA_MESSAGE",
    "UnsupportedRunSchemaVersionError",
    "validate_run_digests",
    "validate_run_schema_version",
]
