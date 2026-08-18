"""Read-only classification of incomplete run-store transactions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from core_tools.persistence import PersistenceError, TransactionRecoveryError

from top_down_planning.persistence.journal_schema import (
    KNOWN_TXN_STATUSES,
    parse_recovery_journal,
)
from top_down_planning.persistence.path_containment import (
    lexical_txn_owned_path,
    validate_journal_basename,
)

TransactionPresence = Literal["none", "recoverable", "unrecoverable"]


def list_txn_candidate_dirs(run_dir: Path) -> list[Path]:
    """Return active ``.txn-*`` paths, including symlink candidates."""

    found: list[Path] = []
    for path in sorted(run_dir.glob(".txn-*")):
        if path.is_symlink() or path.is_dir():
            found.append(path)
    return found


def _txn_journal_path(txn_dir: Path) -> Path:
    return lexical_txn_owned_path(txn_dir, txn_dir / "journal.json")


def _txn_backups_dir(txn_dir: Path) -> Path:
    backups_dir = lexical_txn_owned_path(txn_dir, txn_dir / "backups")
    if backups_dir.is_symlink():
        raise PersistenceError("transaction backups directory must not be a symlink")
    return backups_dir


def _txn_backup_path(txn_dir: Path, name: str) -> Path:
    validated_name = validate_journal_basename(name, label="backup name")
    backups_dir = _txn_backups_dir(txn_dir)
    return lexical_txn_owned_path(txn_dir, backups_dir / validated_name)


def _txn_staged_path(txn_dir: Path, name: str) -> Path:
    validated_name = validate_journal_basename(name, label="staged file name")
    return lexical_txn_owned_path(txn_dir, txn_dir / validated_name)


def _read_transaction_journal(
    journal_path: Path,
    run_id: str,
    expected_txn_id: str,
) -> dict:
    try:
        payload = json.loads(journal_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TransactionRecoveryError(
            f"transaction journal is malformed: {exc}",
            run_id=run_id,
            txn_id=expected_txn_id,
        ) from exc
    if not isinstance(payload, dict):
        raise TransactionRecoveryError(
            "transaction journal must be a mapping",
            run_id=run_id,
            txn_id=expected_txn_id,
        )
    journal_txn_id = str(payload.get("txn_id") or "").strip()
    if not journal_txn_id:
        raise TransactionRecoveryError(
            "transaction journal missing txn_id",
            run_id=run_id,
            txn_id=expected_txn_id,
        )
    if journal_txn_id != expected_txn_id:
        raise TransactionRecoveryError(
            "transaction journal txn_id mismatch with staging directory",
            run_id=run_id,
            txn_id=expected_txn_id,
        )
    return payload


def validate_run_transactions_for_recovery(run_dir: Path, run_id: str) -> Path | None:
    """Raise if transaction state is unrecoverable. Return the txn dir or None."""

    txn_dirs = list_txn_candidate_dirs(run_dir)
    if not txn_dirs:
        return None
    if any(path.is_symlink() for path in txn_dirs):
        raise PersistenceError("transaction directory must not be a symlink")
    if len(txn_dirs) > 1:
        raise TransactionRecoveryError(
            "multiple active transaction directories for run",
            run_id=run_id,
            txn_id="unknown",
        )
    txn_dir = txn_dirs[0]
    txn_id = txn_dir.name.removeprefix(".txn-")
    if not txn_id:
        raise TransactionRecoveryError(
            "invalid transaction directory name",
            run_id=run_id,
            txn_id="unknown",
        )
    journal_path = _txn_journal_path(txn_dir)
    if not journal_path.is_file():
        raise TransactionRecoveryError(
            "transaction journal missing",
            run_id=run_id,
            txn_id=txn_id,
        )
    journal = _read_transaction_journal(journal_path, run_id, txn_id)
    parsed = parse_recovery_journal(journal, run_id=run_id, expected_txn_id=txn_id)
    if parsed.status not in KNOWN_TXN_STATUSES:
        raise TransactionRecoveryError(
            f"unknown transaction status: {parsed.status}",
            run_id=run_id,
            txn_id=txn_id,
        )
    for entry in parsed.files:
        staged = _txn_staged_path(txn_dir, entry.name)
        if parsed.status == "prepared" and not staged.is_file():
            raise TransactionRecoveryError(
                f"transaction journal staged file missing on disk: {entry.name}",
                run_id=run_id,
                txn_id=txn_id,
            )
    _txn_backups_dir(txn_dir)
    for name in parsed.backups:
        backup_path = _txn_backup_path(txn_dir, name)
        if not backup_path.is_file():
            raise TransactionRecoveryError(
                f"transaction journal backup missing on disk: {name}",
                run_id=run_id,
                txn_id=txn_id,
            )
    return txn_dir


def classify_run_transactions(run_dir: Path, run_id: str) -> TransactionPresence:
    """Classify incomplete transactions without mutating the run directory."""

    try:
        txn_dir = validate_run_transactions_for_recovery(run_dir, run_id)
    except (
        OSError,
        json.JSONDecodeError,
        UnicodeDecodeError,
        PersistenceError,
        TypeError,
        ValueError,
    ):
        return "unrecoverable"
    return "none" if txn_dir is None else "recoverable"
