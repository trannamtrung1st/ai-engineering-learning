"""Explicit run-kind classification for resume dispatch (proposal §17)."""

from __future__ import annotations

from typing import Any

RUN_KIND_PLANNING = "planning"
RUN_KIND_SINGLE_EXECUTION = "single_execution"
RUN_KIND_PARENT_EXECUTION = "parent_execution"
RUN_KIND_SUB_TDP_EXECUTION = "sub_tdp_execution"

ALL_RUN_KINDS = frozenset(
    {
        RUN_KIND_PLANNING,
        RUN_KIND_SINGLE_EXECUTION,
        RUN_KIND_PARENT_EXECUTION,
        RUN_KIND_SUB_TDP_EXECUTION,
    }
)


_PLANNING_DEFAULT_PHASES = frozenset({"planning", "plan_validated", "whole_plan_review"})


def default_run_kind_for_phase(phase: str) -> str:
    """Canonical run_kind assigned at run creation when callers omit one."""

    if str(phase or "") in _PLANNING_DEFAULT_PHASES:
        return RUN_KIND_PLANNING
    return RUN_KIND_SINGLE_EXECUTION


def resolve_run_kind(run: dict[str, Any]) -> str:
    """Return persisted run kind. Missing or unknown values are errors."""

    raw = run.get("run_kind")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raise ValueError("run_kind is required")
    explicit = str(raw).strip()
    if explicit not in ALL_RUN_KINDS:
        raise ValueError(f"invalid run_kind: {explicit!r}")
    return explicit


__all__ = [
    "ALL_RUN_KINDS",
    "RUN_KIND_PARENT_EXECUTION",
    "RUN_KIND_PLANNING",
    "RUN_KIND_SINGLE_EXECUTION",
    "RUN_KIND_SUB_TDP_EXECUTION",
    "default_run_kind_for_phase",
    "resolve_run_kind",
]
