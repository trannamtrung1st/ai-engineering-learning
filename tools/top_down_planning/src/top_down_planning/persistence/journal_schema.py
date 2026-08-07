"""Strict transaction journal schema for recovery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core_tools.persistence import PersistenceError, TransactionRecoveryError, digest_bytes

from top_down_planning.persistence.path_containment import validate_journal_basename
from top_down_planning.persistence.path_ids import validate_store_id

_KNOWN_FILE_KINDS = frozenset(
    {"run", "plan", "production", "resolved_config", "invocation", "review"}
)
_KIND_CANONICAL_NAMES = {
    "run": "run.json",
    "plan": "plan.json",
    "production": "production.json",
    "resolved_config": "resolved-config.yaml",
    "invocation": "invocation.json",
}
_REQUIRED_JOURNAL_FIELDS = ("status", "files", "events", "backups", "replaced")


@dataclass(frozen=True)
class JournalFileEntry:
    kind: str
    name: str
    digest: str
    had_destination: bool
    review_id: str | None = None


@dataclass(frozen=True)
class ParsedRecoveryJournal:
    txn_id: str
    status: str
    files: list[JournalFileEntry]
    events: list[dict[str, Any]]
    backups: list[str]
    replaced: list[str]
    events_base_size: int
    events_base_digest: str


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


def _journal_store_id(value: str, *, label: str, run_id: str, txn_id: str) -> str:
    try:
        return validate_store_id(value, label=label)
    except PersistenceError as exc:
        raise _recovery_error(str(exc), run_id=run_id, txn_id=txn_id) from exc


def _journal_basename(value: str, *, label: str, run_id: str, txn_id: str) -> str:
    try:
        return validate_journal_basename(value, label=label)
    except PersistenceError as exc:
        raise _recovery_error(str(exc), run_id=run_id, txn_id=txn_id) from exc


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
        parsed.append(_journal_basename(value, label=f"{field}[{index}]", run_id=run_id, txn_id=txn_id))
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
        name = _journal_basename(
            str(entry.get("name") or "").strip(),
            label=f"files[{index}].name",
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
        had_destination = entry.get("had_destination")
        if not isinstance(had_destination, bool):
            raise _recovery_error(
                f"transaction journal files[{index}] missing had_destination",
                run_id=run_id,
                txn_id=txn_id,
            )
        review_id: str | None = None
        if kind == "review":
            review_id = _journal_store_id(
                str(entry.get("review_id") or "").strip(),
                label="review_id",
                run_id=run_id,
                txn_id=txn_id,
            )
        parsed.append(
            JournalFileEntry(
                kind=kind,
                name=name,
                digest=digest,
                had_destination=had_destination,
                review_id=review_id,
            )
        )
    return parsed


def _parse_event_entries(
    entries: list[Any],
    *,
    run_id: str,
    txn_id: str,
    expected_txn_id: str,
) -> list[dict[str, Any]]:
    event_count = len(entries)
    parsed: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise _recovery_error(
                f"transaction journal events[{index}] must be a mapping",
                run_id=run_id,
                txn_id=txn_id,
            )
        journal_txn_id = entry.get("txn_id")
        if not isinstance(journal_txn_id, str) or journal_txn_id.strip() != expected_txn_id:
            raise _recovery_error(
                f"transaction journal events[{index}] txn_id mismatch",
                run_id=run_id,
                txn_id=txn_id,
            )
        event_index = entry.get("event_index")
        if isinstance(event_index, bool) or not isinstance(event_index, int):
            raise _recovery_error(
                f"transaction journal events[{index}] event_index must be an integer",
                run_id=run_id,
                txn_id=txn_id,
            )
        if event_index != index:
            raise _recovery_error(
                f"transaction journal events[{index}] event_index must equal list position",
                run_id=run_id,
                txn_id=txn_id,
            )
        raw_event_count = entry.get("event_count")
        if isinstance(raw_event_count, bool) or not isinstance(raw_event_count, int):
            raise _recovery_error(
                f"transaction journal events[{index}] event_count must be an integer",
                run_id=run_id,
                txn_id=txn_id,
            )
        if raw_event_count != event_count:
            raise _recovery_error(
                f"transaction journal events[{index}] event_count must equal journal event list length",
                run_id=run_id,
                txn_id=txn_id,
            )
        ts = entry.get("ts")
        if not isinstance(ts, str) or not ts.strip():
            raise _recovery_error(
                f"transaction journal events[{index}] ts must be a non-empty string",
                run_id=run_id,
                txn_id=txn_id,
            )
        event_type = entry.get("type")
        if not isinstance(event_type, str) or not event_type.strip():
            raise _recovery_error(
                f"transaction journal events[{index}] type must be a non-empty string",
                run_id=run_id,
                txn_id=txn_id,
            )
        parsed.append(dict(entry))
    return parsed


def validate_parsed_recovery_journal_invariants(
    parsed: ParsedRecoveryJournal,
    *,
    run_id: str,
    txn_id: str,
) -> None:
    seen_names: set[str] = set()
    for index, entry in enumerate(parsed.files):
        if entry.name in seen_names:
            raise _recovery_error(
                f"transaction journal files contains duplicate file name {entry.name!r}",
                run_id=run_id,
                txn_id=txn_id,
            )
        seen_names.add(entry.name)

        if entry.kind == "review":
            expected_name = f"review__{entry.review_id}.json"
            if entry.name != expected_name:
                raise _recovery_error(
                    f"transaction journal files[{index}] review name must be {expected_name!r}",
                    run_id=run_id,
                    txn_id=txn_id,
                )
        else:
            expected_name = _KIND_CANONICAL_NAMES.get(entry.kind)
            if expected_name is None or entry.name != expected_name:
                raise _recovery_error(
                    f"transaction journal files[{index}] kind/name mismatch: "
                    f"kind={entry.kind!r}, name={entry.name!r}",
                    run_id=run_id,
                    txn_id=txn_id,
                )

    if len(parsed.backups) != len(set(parsed.backups)):
        raise _recovery_error(
            "transaction journal backups contains duplicate names",
            run_id=run_id,
            txn_id=txn_id,
        )
    if len(parsed.replaced) != len(set(parsed.replaced)):
        raise _recovery_error(
            "transaction journal replaced contains duplicate names",
            run_id=run_id,
            txn_id=txn_id,
        )

    for name in parsed.backups:
        if name not in seen_names:
            raise _recovery_error(
                f"transaction journal backups references unknown file {name!r}",
                run_id=run_id,
                txn_id=txn_id,
            )
    for name in parsed.replaced:
        if name not in seen_names:
            raise _recovery_error(
                f"transaction journal replaced references unknown file {name!r}",
                run_id=run_id,
                txn_id=txn_id,
            )

    if parsed.status == "prepared" and (parsed.backups or parsed.replaced):
        raise _recovery_error(
            "prepared transaction journal cannot list replaced or backup files",
            run_id=run_id,
            txn_id=txn_id,
        )

    backup_names = set(parsed.backups)
    replaced_names = set(parsed.replaced)
    if parsed.status in {"replacing", "appending_events", "committed"}:
        for entry in parsed.files:
            if parsed.status == "replacing" and entry.name not in replaced_names:
                continue
            if entry.had_destination and entry.name not in backup_names:
                raise _recovery_error(
                    f"transaction journal file {entry.name!r} had_destination requires backup",
                    run_id=run_id,
                    txn_id=txn_id,
                )
            if not entry.had_destination and entry.name in backup_names:
                raise _recovery_error(
                    f"transaction journal file {entry.name!r} is new and cannot have backup",
                    run_id=run_id,
                    txn_id=txn_id,
                )

    if parsed.status in {"appending_events", "committed"} and replaced_names != seen_names:
        raise _recovery_error(
            "transaction journal replaced must include every staged file",
            run_id=run_id,
            txn_id=txn_id,
        )


def _parse_events_append_boundary(
    journal: dict[str, Any],
    *,
    events: list[dict[str, Any]],
    status: str,
    run_id: str,
    txn_id: str,
) -> tuple[int, str]:
    if not events:
        return 0, digest_bytes(b"")
    if "events_base_size" not in journal or "events_base_digest" not in journal:
        raise _recovery_error(
            "transaction journal missing events append boundary",
            run_id=run_id,
            txn_id=txn_id,
        )
    raw_size = journal["events_base_size"]
    raw_digest = journal["events_base_digest"]

    if not isinstance(raw_size, int) or isinstance(raw_size, bool) or raw_size < 0:
        raise _recovery_error(
            "transaction journal events_base_size must be a non-negative integer",
            run_id=run_id,
            txn_id=txn_id,
        )
    if not isinstance(raw_digest, str) or not raw_digest.strip():
        raise _recovery_error(
            "transaction journal events_base_digest must be a non-empty string",
            run_id=run_id,
            txn_id=txn_id,
        )
    return raw_size, raw_digest.strip()


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
        expected_txn_id=expected_txn_id,
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
    events_base_size, events_base_digest = _parse_events_append_boundary(
        journal,
        events=events,
        status=status,
        run_id=run_id,
        txn_id=expected_txn_id,
    )

    parsed = ParsedRecoveryJournal(
        txn_id=expected_txn_id,
        status=status,
        files=files,
        backups=backups,
        events=events,
        replaced=replaced,
        events_base_size=events_base_size,
        events_base_digest=events_base_digest,
    )
    validate_parsed_recovery_journal_invariants(parsed, run_id=run_id, txn_id=expected_txn_id)
    return parsed


def journal_file_entry_as_dict(entry: JournalFileEntry) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": entry.kind,
        "name": entry.name,
        "digest": entry.digest,
        "had_destination": entry.had_destination,
    }
    if entry.review_id is not None:
        payload["review_id"] = entry.review_id
    return payload
