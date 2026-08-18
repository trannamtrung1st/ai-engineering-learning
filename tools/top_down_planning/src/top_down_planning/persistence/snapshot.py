"""Coherent canonical snapshot loaded under one run lock."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CanonicalRunSnapshot:
    run: dict[str, Any]
    plan: dict[str, Any]
    production: dict[str, Any]
    reviews: list[dict[str, Any]]
    resolved_config: dict[str, Any]
