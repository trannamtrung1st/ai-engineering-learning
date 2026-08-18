"""Journaled commit contract for run-store mutations.

Each commit appends zero or more audit events. Journaled events carry
``txn_id``, ``event_index``, and ``event_count`` for crash-safe recovery.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core_tools.persistence import PersistenceError


class StoreAuthorizationConflictError(PersistenceError):
    """Authorized mutation is no longer valid under the commit lock."""


@dataclass
class CommitSpec:
    """Atomic multi-file mutation spec for a journaled store commit."""

    events: list[dict[str, Any]] = field(default_factory=list)
    run: dict[str, Any] | None = None
    run_expected_revision: int | None = None
    plan: dict[str, Any] | None = None
    plan_expected_revision: int | None = None
    production: dict[str, Any] | None = None
    production_expected_revision: int | None = None
    resolved_config: dict[str, Any] | None = None
    invocation: dict[str, Any] | None = None
    reviews: list[dict[str, Any]] = field(default_factory=list)
    review_expected_revisions: dict[str, int] = field(default_factory=dict)
    authorized_capability_id: str | None = None
    authorized_phase: str | None = None
