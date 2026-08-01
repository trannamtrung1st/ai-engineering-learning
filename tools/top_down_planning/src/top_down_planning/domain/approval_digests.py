"""Digest keys bound on mandatory whole-plan and whole-output approval records."""

from __future__ import annotations

PLAN_APPROVAL_DIGEST_KEYS = frozenset(
    {"plan", "config_contract", "input", "output_goal", "context_spec"}
)
OUTPUT_APPROVAL_DIGEST_KEYS = PLAN_APPROVAL_DIGEST_KEYS | frozenset(
    {"output", "context_snapshot"}
)

_LEGACY_APPROVED_CONFIG_DIGEST_KEY = "config"


def reject_legacy_approved_config_digest(approved_digests: dict[str, str] | None) -> None:
    """Reject approval records that still bind the monolithic config digest key."""

    if isinstance(approved_digests, dict) and _LEGACY_APPROVED_CONFIG_DIGEST_KEY in approved_digests:
        raise ValueError(
            "legacy approved digest key 'config' is not accepted; use config_contract"
        )


__all__ = [
    "OUTPUT_APPROVAL_DIGEST_KEYS",
    "PLAN_APPROVAL_DIGEST_KEYS",
    "reject_legacy_approved_config_digest",
]
