"""Live-process run ownership and revision CAS helpers (proposal §18.1)."""

from __future__ import annotations

import contextvars
import json
import os
import uuid
from contextlib import contextmanager
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from top_down_planning.domain.errors import DomainError

DEFAULT_OWNERSHIP_STALE_SECONDS = 4 * 60 * 60

_RESUME_LOCK_FILENAME = ".resume.lock"
_PROCESS_REGISTRY: dict[str, str] = {}
_NESTED_OWNERSHIP: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar(
    "_NESTED_OWNERSHIP",
    default=None,
)


class RunOwnershipError(DomainError):
    """Another live process owns the run or revision CAS failed."""

    def __init__(self, message: str, *, code: str = "run_ownership_conflict") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ResumeLockRecord:
    run_id: str
    pid: int
    owner_token: str
    acquired_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "pid": self.pid,
            "owner_token": self.owner_token,
            "acquired_at": self.acquired_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ResumeLockRecord:
        return cls(
            run_id=str(payload["run_id"]),
            pid=int(payload["pid"]),
            owner_token=str(payload["owner_token"]),
            acquired_at=str(payload["acquired_at"]),
        )


def resume_lock_path(run_dir: Path) -> Path:
    return run_dir / _RESUME_LOCK_FILENAME


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def read_resume_lock(run_dir: Path) -> ResumeLockRecord | None:
    path = resume_lock_path(run_dir)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return ResumeLockRecord.from_dict(payload)
    except (KeyError, TypeError, ValueError):
        return None


def is_resume_lock_stale(
    lock: ResumeLockRecord,
    *,
    stale_after_seconds: float = DEFAULT_OWNERSHIP_STALE_SECONDS,
) -> bool:
    if not is_pid_alive(lock.pid):
        return True
    try:
        acquired_at = _parse_timestamp(lock.acquired_at)
    except ValueError:
        return True
    return datetime.now(UTC) - acquired_at > timedelta(seconds=stale_after_seconds)


def clear_stale_resume_lock(
    run_dir: Path,
    *,
    stale_after_seconds: float = DEFAULT_OWNERSHIP_STALE_SECONDS,
) -> bool:
    """Remove a stale on-disk lock. Returns True when a stale lock was cleared."""

    lock = read_resume_lock(run_dir)
    if lock is None:
        return False
    if not is_resume_lock_stale(lock, stale_after_seconds=stale_after_seconds):
        return False
    _PROCESS_REGISTRY.pop(lock.run_id, None)
    path = resume_lock_path(run_dir)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return False
    return True


def assert_expected_run_revision(
    run: dict[str, Any],
    expected_revision: int,
) -> None:
    actual_revision = int(run.get("revision") or 0)
    if actual_revision != int(expected_revision):
        raise RunOwnershipError(
            "resume plan revision is stale "
            f"(expected {expected_revision}, found {actual_revision})",
            code="run_revision_mismatch",
        )


def assert_no_live_process_owns_run(
    run_id: str,
    *,
    run_dir: Path | None = None,
) -> None:
    """Refuse resume mutation when another live process owns the run."""

    active_token = _PROCESS_REGISTRY.get(run_id)
    if active_token is not None:
        raise RunOwnershipError(
            f"run {run_id} is owned by a live in-process continuation",
            code="run_owned_by_live_process",
        )

    if run_dir is None:
        return

    clear_stale_resume_lock(run_dir)
    lock = read_resume_lock(run_dir)
    if lock is None:
        return
    if lock.run_id != run_id:
        raise RunOwnershipError(
            f"run {run_id} resume lock belongs to {lock.run_id}",
            code="run_owned_by_live_process",
        )
    if is_pid_alive(lock.pid):
        raise RunOwnershipError(
            f"run {run_id} is owned by live process pid={lock.pid}",
            code="run_owned_by_live_process",
        )


def acquire_run_ownership(
    run_id: str,
    *,
    run_dir: Path,
) -> str:
    """Acquire in-process and on-disk ownership for a run continuation or apply."""

    assert_no_live_process_owns_run(run_id, run_dir=run_dir)
    owner_token = uuid.uuid4().hex
    record = ResumeLockRecord(
        run_id=run_id,
        pid=os.getpid(),
        owner_token=owner_token,
        acquired_at=_utc_now(),
    )
    path = resume_lock_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(record.to_dict(), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _PROCESS_REGISTRY[run_id] = owner_token
    return owner_token


def release_run_ownership(
    run_id: str,
    *,
    run_dir: Path,
    owner_token: str,
) -> None:
    """Release ownership acquired by ``acquire_run_ownership``."""

    if _PROCESS_REGISTRY.get(run_id) == owner_token:
        _PROCESS_REGISTRY.pop(run_id, None)

    lock = read_resume_lock(run_dir)
    if lock is None:
        return
    if lock.owner_token != owner_token:
        return
    resume_lock_path(run_dir).unlink(missing_ok=True)


@contextmanager
def run_ownership(run_id: str, *, run_dir: Path) -> Iterator[str]:
    """Hold live-process ownership for the duration of a run-driving operation.

    Nested scopes in the same execution context reuse the outer token so session
    replacement can run under an active ``continue_run`` continuation.
    """

    nested = _NESTED_OWNERSHIP.get()
    if nested is not None and run_id in nested:
        yield nested[run_id]
        return

    owner_token = acquire_run_ownership(run_id, run_dir=run_dir)
    new_nested = {} if nested is None else dict(nested)
    new_nested[run_id] = owner_token
    reset_token = _NESTED_OWNERSHIP.set(new_nested)
    try:
        yield owner_token
    finally:
        _NESTED_OWNERSHIP.reset(reset_token)
        release_run_ownership(run_id, run_dir=run_dir, owner_token=owner_token)


def resolve_run_dir(store: Any, run_id: str) -> Path | None:
    run_dir_fn = getattr(store, "run_dir", None)
    if not callable(run_dir_fn):
        return None
    return Path(run_dir_fn(run_id))


def is_run_orchestrator_alive(run_dir: Path) -> bool:
    """Return True when a live process holds the run resume lock."""

    clear_stale_resume_lock(run_dir)
    lock = read_resume_lock(run_dir)
    if lock is None:
        return False
    return is_pid_alive(lock.pid)
