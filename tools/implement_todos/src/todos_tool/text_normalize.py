"""Shared text normalization for acceptance-criterion matching."""

from __future__ import annotations

import re
import unicodedata

_MULTIPLY_SIGNS = str.maketrans(
    {
        "\u00d7": "x",  # ×
        "\u2715": "x",  # ✕
        "\u2716": "x",  # ✖
        "\u2573": "x",  # ╳
    }
)


def normalize_acceptance_criterion(text: str) -> str:
    """Normalize criterion text for set-equality checks.

    Collapses whitespace, lowercases, applies NFKC, and maps common
    multiplication-sign variants to ASCII ``x`` (e.g. ``1440×900`` → ``1440x900``).
    """
    normalized = unicodedata.normalize("NFKC", text.strip())
    normalized = normalized.translate(_MULTIPLY_SIGNS)
    return " ".join(normalized.split()).lower()
