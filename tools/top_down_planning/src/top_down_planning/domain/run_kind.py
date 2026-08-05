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


def resolve_run_kind(run: dict[str, Any]) -> str:
    """Return persisted run kind."""

    explicit = str(run.get("run_kind") or "").strip()
    if explicit in ALL_RUN_KINDS:
        return explicit
    phase = str(run.get("phase") or "")
    if phase == "planning":
        return RUN_KIND_PLANNING
    return RUN_KIND_SINGLE_EXECUTION


__all__ = [
    "ALL_RUN_KINDS",
    "RUN_KIND_PARENT_EXECUTION",
    "RUN_KIND_PLANNING",
    "RUN_KIND_SINGLE_EXECUTION",
    "RUN_KIND_SUB_TDP_EXECUTION",
    "resolve_run_kind",
]
