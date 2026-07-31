"""Digest keys bound on mandatory whole-plan and whole-output approval records."""

from __future__ import annotations

PLAN_APPROVAL_DIGEST_KEYS = frozenset(
    {"plan", "config", "input", "output_goal", "context_spec"}
)
OUTPUT_APPROVAL_DIGEST_KEYS = PLAN_APPROVAL_DIGEST_KEYS | frozenset(
    {"output", "context_snapshot"}
)

__all__ = ["PLAN_APPROVAL_DIGEST_KEYS", "OUTPUT_APPROVAL_DIGEST_KEYS"]
