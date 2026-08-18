"""Read-only classification of incomplete run-store transactions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from core_tools.persistence import (
    PersistenceError,
    TransactionRecoveryError,
    digest_bytes,
    digest_file,
)

from top_down_planning.persistence.journal_schema import (
    KNOWN_TXN_STATUSES,
    JournalFileEntry,
    ParsedRecoveryJournal,
    parse_recovery_journal,
)
from top_down_planning.persistence.path_containment import (
    lexical_run_owned_path,
    lexical_txn_owned_path,
    validate_journal_basename,
)

TransactionPresence = Literal["none", "recoverable", "unrecoverable"]


@dataclass(frozen=True)
class InspectedRunTransactions:
    txn_dir: Path
    parsed: ParsedRecoveryJournal


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


def destination_for_journal_entry(run_dir: Path, entry: JournalFileEntry) -> Path:
    """Return the canonical destination for a journaled staged file."""

    if entry.kind == "review":
        return lexical_run_owned_path(
            run_dir,
            run_dir / "reviews" / f"{entry.review_id}.json",
        )
    if entry.kind == "artifact":
        return lexical_run_owned_path(
            run_dir,
            run_dir / "artifacts" / str(entry.snapshot_id) / str(entry.filename),
        )
    return lexical_run_owned_path(run_dir, run_dir / entry.name)


def journal_events_suffix_bytes(events: list[dict]) -> bytes:
    """Serialize journaled events the same way commit recovery appends them."""

    return b"".join(
        (json.dumps(dict(event), sort_keys=True) + "\n").encode("utf-8")
        for event in events
    )


def require_committed_destinations(
    run_dir: Path,
    parsed: ParsedRecoveryJournal,
    *,
    run_id: str,
    txn_id: str,
) -> None:
    """Require every published destination to exist and match its journal digest."""

    names = {entry.name for entry in parsed.files}
    if set(parsed.replaced) != names:
        raise TransactionRecoveryError(
            "transaction journal replaced must include every staged file",
            run_id=run_id,
            txn_id=txn_id,
        )
    if not parsed.files:
        return
    for entry in parsed.files:
        dest = destination_for_journal_entry(run_dir, entry)
        if not dest.is_file() or digest_file(dest) != entry.digest:
            raise TransactionRecoveryError(
                "canonical destination digest mismatch for staged transaction file",
                run_id=run_id,
                txn_id=txn_id,
            )


def verify_events_append_recoverable(
    run_dir: Path,
    parsed: ParsedRecoveryJournal,
    *,
    run_id: str,
    txn_id: str,
) -> None:
    """Require the current event log to be a recoverable prefix of the journaled batch."""

    if not parsed.events:
        return
    events_path = lexical_run_owned_path(run_dir, run_dir / "events.jsonl")
    events_base_size = parsed.events_base_size
    events_base_digest = parsed.events_base_digest
    if events_base_size == 0 and events_base_digest == digest_bytes(b""):
        if events_path.is_file() and events_path.stat().st_size > 0:
            raise TransactionRecoveryError(
                "events append boundary mismatch",
                run_id=run_id,
                txn_id=txn_id,
            )
        current = b""
    else:
        if not events_path.is_file():
            raise TransactionRecoveryError(
                "events append boundary mismatch",
                run_id=run_id,
                txn_id=txn_id,
            )
        current = events_path.read_bytes()
        if len(current) < events_base_size:
            raise TransactionRecoveryError(
                "events append boundary mismatch",
                run_id=run_id,
                txn_id=txn_id,
            )
        prefix = current[:events_base_size]
        if digest_bytes(prefix) != events_base_digest:
            raise TransactionRecoveryError(
                "events append boundary mismatch",
                run_id=run_id,
                txn_id=txn_id,
            )
    expected_suffix = journal_events_suffix_bytes(parsed.events)
    target = current[:events_base_size] + expected_suffix
    if len(current) > len(target):
        raise TransactionRecoveryError(
            "transaction event suffix exceeds journaled batch",
            run_id=run_id,
            txn_id=txn_id,
        )
    if not target.startswith(current):
        raise TransactionRecoveryError(
            "transaction event suffix mismatch",
            run_id=run_id,
            txn_id=txn_id,
        )


def replaced_destinations_match(run_dir: Path, parsed: ParsedRecoveryJournal) -> bool:
    """Return True when every staged file is replaced and matches its journal digest."""

    names = {entry.name for entry in parsed.files}
    if set(parsed.replaced) != names:
        return False
    if not parsed.files:
        return True
    for entry in parsed.files:
        dest = destination_for_journal_entry(run_dir, entry)
        if not dest.is_file() or digest_file(dest) != entry.digest:
            return False
    return True


def recovery_commits_forward(run_dir: Path, parsed: ParsedRecoveryJournal) -> bool:
    """Return True when recovery will append events and retire instead of rolling back."""

    if parsed.status in {"appending_events", "committed"}:
        return True
    return parsed.status == "replacing" and replaced_destinations_match(run_dir, parsed)


_CORE_CANONICAL_RELATIVES = (
    "run.json",
    "plan.json",
    "production.json",
    "resolved-config.yaml",
    "invocation.json",
)


def _rollback_journal_names(run_dir: Path, parsed: ParsedRecoveryJournal) -> set[str]:
    names = {str(name) for name in parsed.replaced}
    for entry in parsed.files:
        dest = destination_for_journal_entry(run_dir, entry)
        if dest.is_file() and digest_file(dest) == entry.digest:
            names.add(entry.name)
    return names


def _read_contained_file_bytes(run_dir: Path, relative: str) -> bytes | None:
    dest = lexical_run_owned_path(run_dir, run_dir / relative)
    if dest.is_symlink():
        raise PersistenceError(f"{relative} must not be a symlink")
    if not dest.is_file():
        return None
    return dest.read_bytes()


def _bytes_for_journal_entry(
    run_dir: Path,
    txn_dir: Path,
    entry: JournalFileEntry,
    *,
    commit_forward: bool,
    rollback_names: set[str],
) -> bytes | None:
    dest = destination_for_journal_entry(run_dir, entry)
    if commit_forward:
        if dest.is_file() and digest_file(dest) == entry.digest:
            return dest.read_bytes()
        staged = _txn_staged_path(txn_dir, entry.name)
        if staged.is_file():
            return staged.read_bytes()
        raise PersistenceError(f"transaction staged file missing: {entry.name}")
    if entry.name in rollback_names:
        backup = _txn_backup_path(txn_dir, entry.name)
        if backup.is_file():
            return backup.read_bytes()
        return None
    return dest.read_bytes() if dest.is_file() else None


def _post_recovery_events_bytes(
    run_dir: Path,
    parsed: ParsedRecoveryJournal,
    *,
    commit_forward: bool,
) -> bytes | None:
    events_path = lexical_run_owned_path(run_dir, run_dir / "events.jsonl")
    if events_path.is_symlink():
        raise PersistenceError("events.jsonl must not be a symlink")
    if commit_forward and parsed.events:
        current = events_path.read_bytes() if events_path.is_file() else b""
        prefix = current[: parsed.events_base_size]
        return prefix + journal_events_suffix_bytes(parsed.events)
    if not events_path.is_file():
        return None
    return events_path.read_bytes()


def materialize_post_recovery_canonical_overlay(
    run_dir: Path,
    inspected: InspectedRunTransactions,
) -> dict[str, bytes]:
    """Return the canonical bytes recovery would leave, without mutating the run."""

    parsed = inspected.parsed
    txn_dir = inspected.txn_dir
    commit_forward = recovery_commits_forward(run_dir, parsed)
    rollback_names = set() if commit_forward else _rollback_journal_names(run_dir, parsed)
    entry_by_relative: dict[str, JournalFileEntry] = {}
    for entry in parsed.files:
        dest = destination_for_journal_entry(run_dir, entry)
        entry_by_relative[dest.relative_to(run_dir).as_posix()] = entry

    overlay: dict[str, bytes] = {}
    for relative in _CORE_CANONICAL_RELATIVES:
        entry = entry_by_relative.get(relative)
        data = (
            _bytes_for_journal_entry(
                run_dir,
                txn_dir,
                entry,
                commit_forward=commit_forward,
                rollback_names=rollback_names,
            )
            if entry is not None
            else _read_contained_file_bytes(run_dir, relative)
        )
        if data is not None:
            overlay[relative] = data

    events_bytes = _post_recovery_events_bytes(
        run_dir,
        parsed,
        commit_forward=commit_forward,
    )
    if events_bytes is not None:
        overlay["events.jsonl"] = events_bytes

    review_relatives: set[str] = set()
    reviews_dir = lexical_run_owned_path(run_dir, run_dir / "reviews")
    if reviews_dir.exists():
        if reviews_dir.is_symlink():
            raise PersistenceError("reviews must not be a symlink")
        if not reviews_dir.is_dir():
            raise PersistenceError("reviews must be a directory")
        for review_path in reviews_dir.glob("*.json"):
            review_relatives.add(review_path.relative_to(run_dir).as_posix())
    for relative, entry in entry_by_relative.items():
        if entry.kind == "review":
            review_relatives.add(relative)
    for relative in review_relatives:
        entry = entry_by_relative.get(relative)
        data = (
            _bytes_for_journal_entry(
                run_dir,
                txn_dir,
                entry,
                commit_forward=commit_forward,
                rollback_names=rollback_names,
            )
            if entry is not None
            else _read_contained_file_bytes(run_dir, relative)
        )
        if data is not None:
            overlay[relative] = data
    return overlay


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


def inspect_run_transactions(
    run_dir: Path,
    run_id: str,
) -> InspectedRunTransactions | None:
    """Return the recoverable transaction, or None. Raise if unrecoverable."""

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
    if parsed.status in {"appending_events", "committed"}:
        require_committed_destinations(
            run_dir,
            parsed,
            run_id=run_id,
            txn_id=txn_id,
        )
        verify_events_append_recoverable(
            run_dir,
            parsed,
            run_id=run_id,
            txn_id=txn_id,
        )
    elif recovery_commits_forward(run_dir, parsed):
        verify_events_append_recoverable(
            run_dir,
            parsed,
            run_id=run_id,
            txn_id=txn_id,
        )
    return InspectedRunTransactions(txn_dir=txn_dir, parsed=parsed)


def validate_run_transactions_for_recovery(run_dir: Path, run_id: str) -> Path | None:
    """Raise if transaction state is unrecoverable. Return the txn dir or None."""

    inspected = inspect_run_transactions(run_dir, run_id)
    return None if inspected is None else inspected.txn_dir


def classify_run_transactions(run_dir: Path, run_id: str) -> TransactionPresence:
    """Classify incomplete transactions without mutating the run directory."""

    try:
        inspected = inspect_run_transactions(run_dir, run_id)
    except (
        OSError,
        json.JSONDecodeError,
        UnicodeDecodeError,
        PersistenceError,
        TypeError,
        ValueError,
    ):
        return "unrecoverable"
    return "none" if inspected is None else "recoverable"
