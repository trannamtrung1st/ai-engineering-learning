"""Persistence-layer errors."""

from __future__ import annotations


class PersistenceError(Exception):
    """Unrecoverable persistence failure."""


class TransactionRecoveryError(PersistenceError):
    """Journaled transaction recovery cannot proceed safely."""

    def __init__(
        self,
        message: str,
        *,
        run_id: str | None = None,
        txn_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.run_id = run_id
        self.txn_id = txn_id
