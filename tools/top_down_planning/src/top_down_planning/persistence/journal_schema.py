"""Strict transaction journal schema for recovery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core_tools.persistence import TransactionRecoveryError

_KNOWN_FILE_KINDS = frozenset(
    {"run", "plan", "production", "resolved_config", "invocation", "review"}
)
_REQUIRED_JOURNAL_FIELDS = ("status", "files", "events", "backups", "replaced")


@dataclass(frozen=True)
class JournalFileEntry:
    kind: str
    name: str
    digest: str
    review_id: str | None = None


@dataclass(frozen=True)
class ParsedRecoveryJournal:
    txn_id: str
    status: str
    files: list[JournalFileEntry]
    events: list[dict[str, Any]]
    backups: list[str]
    replaced: list[str]


def _recovery_error(
    message: str,
    *,
    run_id: str,
    txn_id: str,
) -> TransactionRecoveryError:
    return TransactionRecoveryError(message, run_id=run_id, txn_id=txn_id)


def _require_list_field(
    journal: dict[str, Any],
    field: str,
    *,
    run_id: str,
    txn_id: str,
) -> list[Any]:
    if field not in journal:
        raise _recovery_error(f"transaction journal missing {field}", run_id=run_id, txn_id=txn_id)
    raw = journal[field]
    if not isinstance(raw, list):
        raise _recovery_error(
            f"transaction journal {field} must be a list",
            run_id=run_id,
            txn_id=txn_id,
        )
    return list(raw)


def _parse_string_list(
    values: list[Any],
    *,
    field: str,
    run_id: str,
    txn_id: str,
) -> list[str]:
    parsed: list[str] = []
    for index, value in enumerate(values):
        if not isinstance(value, str) or not value.strip():
            raise _recovery_error(
                f"transaction journal {field}[{index}] must be a non-empty string",
                run_id=run_id,
                txn_id=txn_id,
            )
        parsed.append(value)
    return parsed


def _parse_file_entries(
    entries: list[Any],
    *,
    run_id: str,
    txn_id: str,
) -> list[JournalFileEntry]:
    parsed: list[JournalFileEntry] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise _recovery_error(
                f"transaction journal files[{index}] must be a mapping",
                run_id=run_id,
                txn_id=txn_id,
            )
        kind = str(entry.get("kind") or "").strip()
        if kind not in _KNOWN_FILE_KINDS:
            raise _recovery_error(
                f"transaction journal files[{index}] has unknown kind {kind!r}",
                run_id=run_id,
                txn_id=txn_id,
            )
        name = str(entry.get("name") or "").strip()
        if not name:
            raise _recovery_error(
                f"transaction journal files[{index}] missing name",
                run_id=run_id,
                txn_id=txn_id,
            )
        digest = str(entry.get("digest") or "").strip()
        if not digest:
            raise _recovery_error(
                f"transaction journal files[{index}] missing digest",
                run_id=run_id,
                txn_id=txn_id,
            )
        review_id: str | None = None
        if kind == "review":
            review_id = str(entry.get("review_id") or "").strip()
            if not review_id:
                raise _recovery_error(
                    f"transaction journal files[{index}] missing review_id",
                    run_id=run_id,
                    txn_id=txn_id,
                )
        parsed.append(
            JournalFileEntry(
                kind=kind,
                name=name,
                digest=digest,
                review_id=review_id,
            )
        )
    return parsed


def _parse_event_entries(
    entries: list[Any],
    *,
    run_id: str,
    txn_id: str,
) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise _recovery_error(
                f"transaction journal events[{index}] must be a mapping",
                run_id=run_id,
                txn_id=txn_id,
            )
        parsed.append(dict(entry))
    return parsed


def parse_recovery_journal(
    journal: dict[str, Any],
    *,
    run_id: str,
    expected_txn_id: str,
) -> ParsedRecoveryJournal:
    journal_txn_id = str(journal.get("txn_id") or "").strip()
    if not journal_txn_id:
        raise _recovery_error(
            "transaction journal missing txn_id",
            run_id=run_id,
            txn_id=expected_txn_id,
        )
    if journal_txn_id != expected_txn_id:
        raise _recovery_error(
            "transaction journal txn_id mismatch with staging directory",
            run_id=run_id,
            txn_id=expected_txn_id,
        )

    for field in _REQUIRED_JOURNAL_FIELDS:
        if field not in journal:
            raise _recovery_error(
                f"transaction journal missing {field}",
                run_id=run_id,
                txn_id=expected_txn_id,
            )

    status = str(journal["status"] or "").strip()
    if not status:
        raise _recovery_error(
            "transaction journal missing status",
            run_id=run_id,
            txn_id=expected_txn_id,
        )

    files = _parse_file_entries(
        _require_list_field(journal, "files", run_id=run_id, txn_id=expected_txn_id),
        run_id=run_id,
        txn_id=expected_txn_id,
    )
    events = _parse_event_entries(
        _require_list_field(journal, "events", run_id=run_id, txn_id=expected_txn_id),
        run_id=run_id,
        txn_id=expected_txn_id,
    )
    backups = _parse_string_list(
        _require_list_field(journal, "backups", run_id=run_id, txn_id=expected_txn_id),
        field="backups",
        run_id=run_id,
        txn_id=expected_txn_id,
    )
    replaced = _parse_string_list(
        _require_list_field(journal, "replaced", run_id=run_id, txn_id=expected_txn_id),
        field="replaced",
        run_id=run_id,
        txn_id=expected_txn_id,
    )

    return ParsedRecoveryJournal(
        txn_id=expected_txn_id,
        status=status,
        files=files,
        backups=backups,
        events=events,
        replaced=replaced,
    )


def journal_file_entry_as_dict(entry: JournalFileEntry) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": entry.kind,
        "name": entry.name,
        "digest": entry.digest,
    }
    if entry.review_id is not None:
        payload["review_id"] = entry.review_id
    return payload
