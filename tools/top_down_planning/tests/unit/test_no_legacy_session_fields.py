"""Guard against legacy flat session-id fields in production code (proposal §11)."""

from __future__ import annotations

from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "top_down_planning"

_LEGACY_SESSION_PATTERNS = (
    "migrate_sessions_payload",
    "enrich_sessions_for_runtime",
    "binding_from_legacy_provider_session_id",
    "reviewer_binding_from_legacy_session_id",
    "LEGACY_PRIMARY_SESSION_FIELDS",
    "deferred_until_phase_4",
)

_LEGACY_PRIMARY_FIELD_PATTERNS = (
    "primary_planner_session_id",
    "primary_producer_session_id",
)

_ALLOWED_LEGACY_FIELD_PATHS = frozenset(
    {
        Path("persistence/session_bindings.py"),
    }
)


def test_no_legacy_session_field_usage_in_production_code() -> None:
    violations: list[str] = []
    for path in _SRC_ROOT.rglob("*.py"):
        rel = path.relative_to(_SRC_ROOT)
        text = path.read_text(encoding="utf-8")
        for pattern in _LEGACY_SESSION_PATTERNS:
            if pattern in text:
                violations.append(f"{rel}: {pattern}")
        for pattern in _LEGACY_PRIMARY_FIELD_PATTERNS:
            if pattern in text and rel not in _ALLOWED_LEGACY_FIELD_PATHS:
                violations.append(f"{rel}: {pattern}")
    assert not violations, "legacy session compatibility remnants:\n" + "\n".join(violations)
