"""Tests for acceptance-criterion text normalization."""

from __future__ import annotations

from todos_tool.text_normalize import normalize_acceptance_criterion


def test_normalizes_whitespace_and_case() -> None:
    assert normalize_acceptance_criterion("  Crit   A  ") == "crit a"


def test_maps_multiplication_sign_to_ascii_x() -> None:
    assert (
        normalize_acceptance_criterion("Overview renders at 1440×900")
        == normalize_acceptance_criterion("Overview renders at 1440x900")
    )
