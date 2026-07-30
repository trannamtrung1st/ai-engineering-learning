"""Persistence-layer errors."""

from __future__ import annotations


class PersistenceError(Exception):
    """Unrecoverable persistence failure."""
