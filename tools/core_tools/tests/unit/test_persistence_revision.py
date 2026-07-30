"""Unit tests for optimistic revision helpers."""

from __future__ import annotations

import pytest

from core_tools.persistence import (
    PersistenceError,
    StoreRevisionConflictError,
    assert_next_revision,
    require_revision_field,
)


def test_require_revision_field() -> None:
    assert require_revision_field({"revision": 3}, "run") == 3


def test_require_revision_field_missing() -> None:
    with pytest.raises(PersistenceError, match="must include an explicit revision"):
        require_revision_field({}, "run")


def test_assert_next_revision_success() -> None:
    assert_next_revision(2, 3)


def test_assert_next_revision_conflict() -> None:
    with pytest.raises(StoreRevisionConflictError, match="expected 3"):
        assert_next_revision(2, 5)
