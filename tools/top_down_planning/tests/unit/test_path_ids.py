"""Unit tests for run-store identifier helpers."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core_tools.persistence import PersistenceError
from top_down_planning.persistence.path_ids import (
    RUN_ID_PATTERN,
    new_run_id,
    validate_run_id,
    validate_store_id,
)


def test_new_run_id_uses_compact_utc_timestamp_and_random_suffix() -> None:
    run_id = new_run_id(now=datetime(2026, 7, 30, 14, 56, 12, tzinfo=timezone.utc))

    assert run_id.startswith("run-20260730T145612-")
    assert RUN_ID_PATTERN.fullmatch(run_id)
    assert validate_run_id(run_id) == run_id


def test_new_run_id_sorts_chronologically() -> None:
    earlier = new_run_id(now=datetime(2026, 7, 30, 14, 56, 12, tzinfo=timezone.utc))
    later = new_run_id(now=datetime(2026, 7, 30, 15, 0, 34, tzinfo=timezone.utc))

    assert earlier < later


def test_validate_run_id_rejects_legacy_random_only_ids() -> None:
    with pytest.raises(PersistenceError, match="run_id must match"):
        validate_run_id("run-e453e4704d5d")


def test_validate_run_id_rejects_short_test_placeholders() -> None:
    with pytest.raises(PersistenceError, match="run_id must match"):
        validate_run_id("run-001")


def test_validate_store_id_still_allows_non_run_store_ids() -> None:
    assert validate_store_id("review-whole-plan-01", label="review_id") == "review-whole-plan-01"
