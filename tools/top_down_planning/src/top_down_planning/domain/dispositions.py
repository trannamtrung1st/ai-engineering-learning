"""Production disposition types shared across readiness and production (proposal §10.3)."""

from __future__ import annotations

from typing import Literal

TerminalDisposition = Literal[
    "completed",
    "satisfied_without_change",
    "not_applicable",
    "superseded",
    "blocked",
]

TERMINAL_DISPOSITIONS: frozenset[TerminalDisposition] = frozenset(
    {
        "completed",
        "satisfied_without_change",
        "not_applicable",
        "superseded",
        "blocked",
    }
)

SATISFIED_DISPOSITIONS: frozenset[TerminalDisposition] = frozenset(
    {
        "completed",
        "satisfied_without_change",
        "not_applicable",
        "superseded",
    }
)

DispositionMap = dict[str, TerminalDisposition]


def is_terminal_disposition(disposition: TerminalDisposition) -> bool:
    return disposition in TERMINAL_DISPOSITIONS


def is_satisfied_disposition(disposition: TerminalDisposition) -> bool:
    return disposition in SATISFIED_DISPOSITIONS
