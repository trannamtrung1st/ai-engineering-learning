"""Built-in and custom review rule identifiers for finding families."""

from __future__ import annotations

import re
from typing import Literal

RULE_REGISTRY_VERSION = 1
CUSTOM_RULE_PREFIX = "custom."
_FINGERPRINT_PROTOCOL_VERSION = 1

BuiltinRuleId = Literal[
    "dependency.acceptance_capability_available",
    "hierarchy.aggregate_executable_work",
    "requirements.modality_preservation",
    "acceptance.branch_completeness",
    "hierarchy.executable_parent_overlap",
    "dependencies.duplicate_target",
    "dependencies.cycle",
    "contract.ownership_placement",
    "coverage.traceability_gap",
    "scope.field_placement",
]

KNOWN_RULE_IDS: frozenset[str] = frozenset(
    {
        "dependency.acceptance_capability_available",
        "hierarchy.aggregate_executable_work",
        "requirements.modality_preservation",
        "acceptance.branch_completeness",
        "hierarchy.executable_parent_overlap",
        "dependencies.duplicate_target",
        "dependencies.cycle",
        "contract.ownership_placement",
        "coverage.traceability_gap",
        "scope.field_placement",
    }
)

_CUSTOM_RULE_PATTERN = re.compile(r"^custom\.[a-z0-9]+(?:-[a-z0-9]+)*$")


def is_builtin_rule_id(rule_id: str) -> bool:
    return rule_id in KNOWN_RULE_IDS


def is_custom_rule_id(rule_id: str) -> bool:
    normalized = str(rule_id or "").strip()
    return normalized.startswith(CUSTOM_RULE_PREFIX) and bool(
        _CUSTOM_RULE_PATTERN.match(normalized)
    )


def validate_rule_id(rule_id: str) -> str:
    normalized = str(rule_id or "").strip()
    if not normalized:
        raise ValueError("rule_id is required")
    if is_builtin_rule_id(normalized) or is_custom_rule_id(normalized):
        return normalized
    raise ValueError(
        f"rule_id {normalized!r} must be a built-in rule or match custom.<slug>"
    )


def normalize_subject_key(subject_key: str) -> str:
    normalized = re.sub(r"\s+", " ", str(subject_key or "").casefold().strip())
    if not normalized:
        raise ValueError("subject_key must be non-empty after normalization")
    return normalized


def normalize_rule_definition(rule_definition: str) -> str:
    normalized = re.sub(
        r"\s+",
        " ",
        str(rule_definition or "").casefold().strip(),
    )
    if not normalized:
        raise ValueError("rule_definition must be non-empty after normalization")
    return normalized


def fingerprint_protocol_version() -> int:
    return _FINGERPRINT_PROTOCOL_VERSION
