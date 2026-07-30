"""Transactional commit contract for run-store mutations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CommitSpec:
    """Single logical store transaction."""

    events: list[dict[str, Any]] = field(default_factory=list)
    run: dict[str, Any] | None = None
    run_expected_revision: int | None = None
    plan: dict[str, Any] | None = None
    plan_expected_revision: int | None = None
    production: dict[str, Any] | None = None
    production_expected_revision: int | None = None
    reviews: list[dict[str, Any]] = field(default_factory=list)
