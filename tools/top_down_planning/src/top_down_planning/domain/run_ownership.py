"""Live-process run ownership and revision CAS helpers (proposal §18.1)."""

from __future__ import annotations

import contextvars
import fcntl
import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from top_down_planning.domain.errors import DomainError

DEFAULT_OWNERSHIP_STALE_SECONDS = 4 * 60 * 60
_LOCK_WAIT_ATTEMPTS = 20
_LOCK_WAIT_INTERVAL_SECONDS = 0.025

_RESUME_LOCK_FILENAME = ".resume.lock"
_RESUME_LOCK_DIRNAME = ".resume.lock.d"
_LOCK_METADATA_FILENAME = "owner.json"
_OWNER_FLOCK_FILENAME = ".owner.lock"
_PROCESS_REGISTRY: dict[str, str] = {}
_FLOCK_REGISTRY: dict[str, int] = {}
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
    process_identity: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "run_id": self.run_id,
            "pid": self.pid,
            "owner_token": self.owner_token,
            "acquired_at": self.acquired_at,
        }
        if self.process_identity is not None:
            payload["process_identity"] = self.process_identity
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ResumeLockRecord:
        process_identity = payload.get("process_identity")
        return cls(
            run_id=str(payload["run_id"]),
            pid=int(payload["pid"]),
            owner_token=str(payload["owner_token"]),
            acquired_at=str(payload["acquired_at"]),
            process_identity=(
                str(process_identity) if process_identity is not None else None
            ),
        )


def resume_lock_path(run_dir: Path) -> Path:
    return run_dir / _RESUME_LOCK_FILENAME


def resume_lock_dir(run_dir: Path) -> Path:
    return run_dir / _RESUME_LOCK_DIRNAME


def resume_lock_metadata_path(run_dir: Path) -> Path:
    return resume_lock_dir(run_dir) / _LOCK_METADATA_FILENAME


def owner_flock_path(run_dir: Path) -> Path:
    return resume_lock_dir(run_dir) / _OWNER_FLOCK_FILENAME


def holds_run_ownership(run_id: str) -> bool:
    """Return True when this process holds in-process continuation ownership."""

    nested = _NESTED_OWNERSHIP.get()
    if nested is not None and run_id in nested:
        return True
    return run_id in _PROCESS_REGISTRY


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def process_identity_for_pid(pid: int) -> str:
    proc_path = Path(f"/proc/{pid}")
    try:
        stat = os.stat(proc_path)
        return f"{pid}:{stat.st_ctime_ns}"
    except OSError:
        return f"{pid}:unknown"


def _is_lock_holder_alive(lock: ResumeLockRecord) -> bool:
    if not is_pid_alive(lock.pid):
        return False
    if lock.process_identity is None:
        return True
    return lock.process_identity == process_identity_for_pid(lock.pid)


def _read_lock_metadata(path: Path) -> ResumeLockRecord | None:
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


def read_resume_lock(run_dir: Path) -> ResumeLockRecord | None:
    metadata_path = resume_lock_metadata_path(run_dir)
    if metadata_path.is_file():
        lock = _read_lock_metadata(metadata_path)
        if lock is not None:
            return lock

    legacy_path = resume_lock_path(run_dir)
    if not legacy_path.is_file():
        return None
    try:
        payload = json.loads(legacy_path.read_text(encoding="utf-8"))
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
    return not _is_lock_holder_alive(lock)


def _clear_legacy_lock_file(run_dir: Path) -> bool:
    path = resume_lock_path(run_dir)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return False
    return True


def _clear_lock_storage(run_dir: Path) -> bool:
    cleared = False
    flock_path = owner_flock_path(run_dir)
    try:
        flock_path.unlink(missing_ok=True)
    except OSError:
        pass
    lock_dir = resume_lock_dir(run_dir)
    if lock_dir.is_dir():
        try:
            for child in lock_dir.iterdir():
                child.unlink(missing_ok=True)
            lock_dir.rmdir()
            cleared = True
        except OSError:
            return False
    if resume_lock_path(run_dir).is_file():
        _clear_legacy_lock_file(run_dir)
        cleared = True
    return cleared


def _metadata_holder_alive(metadata_path: Path) -> bool:
    lock = _read_lock_metadata(metadata_path)
    if lock is not None:
        return _is_lock_holder_alive(lock)
    try:
        content = metadata_path.read_text(encoding="utf-8")
    except OSError:
        return False
    pid_match = re.search(r'"pid"\s*:\s*(\d+)', content)
    if pid_match is None:
        return False
    pid = int(pid_match.group(1))
    identity_match = re.search(r'"process_identity"\s*:\s*"([^"]+)"', content)
    if identity_match is None:
        return is_pid_alive(pid)
    probe = ResumeLockRecord(
        run_id="unknown",
        pid=pid,
        owner_token="unknown",
        acquired_at=_utc_now(),
        process_identity=identity_match.group(1),
    )
    return _is_lock_holder_alive(probe)


def _try_acquire_flock_nonblocking(run_dir: Path) -> int | None:
    flock_path = owner_flock_path(run_dir)
    flock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(flock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except BlockingIOError:
        os.close(fd)
        return None


def _release_flock_fd(fd: int) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        os.close(fd)
    except OSError:
        pass


def _is_owner_flock_held(run_dir: Path) -> bool:
    fd = _try_acquire_flock_nonblocking(run_dir)
    if fd is None:
        return True
    _release_flock_fd(fd)
    return False


def _write_lock_metadata(path: Path, record: ResumeLockRecord) -> None:
    payload = json.dumps(record.to_dict(), sort_keys=True) + "\n"
    encoded = payload.encode("utf-8")
    fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o644)
    try:
        written = 0
        while written < len(encoded):
            nbytes = os.write(fd, encoded[written:])
            if nbytes <= 0:
                raise OSError("failed to write complete ownership metadata")
            written += nbytes
        os.fsync(fd)
    finally:
        os.close(fd)


def _clear_abandoned_lock_claim(run_dir: Path) -> bool:
    legacy_path = resume_lock_path(run_dir)
    if legacy_path.is_file():
        try:
            legacy_content = legacy_path.read_text(encoding="utf-8").strip()
        except OSError:
            return False
        if legacy_content and read_resume_lock(run_dir) is None:
            return False

    flock_fd = _try_acquire_flock_nonblocking(run_dir)
    if flock_fd is None:
        return False

    try:
        metadata_path = resume_lock_metadata_path(run_dir)
        lock_dir = resume_lock_dir(run_dir)

        if metadata_path.is_file():
            lock = _read_lock_metadata(metadata_path)
            if lock is not None:
                if _is_lock_holder_alive(lock):
                    return False
                _PROCESS_REGISTRY.pop(lock.run_id, None)
                return _clear_lock_storage(run_dir)
            if _metadata_holder_alive(metadata_path):
                return False
            return _clear_lock_storage(run_dir)

        if legacy_path.is_file():
            lock = read_resume_lock(run_dir)
            if lock is not None:
                if _is_lock_holder_alive(lock):
                    return False
                _PROCESS_REGISTRY.pop(lock.run_id, None)
                return _clear_lock_storage(run_dir)
            try:
                content = legacy_path.read_text(encoding="utf-8").strip()
            except OSError:
                return False
            if not content:
                return _clear_lock_storage(run_dir)
            return False

        if lock_dir.is_dir():
            return _clear_lock_storage(run_dir)

        return False
    finally:
        _release_flock_fd(flock_fd)


def clear_orphan_resume_lock(run_dir: Path) -> bool:
    """Remove abandoned lock storage."""

    return _clear_abandoned_lock_claim(run_dir)


def clear_stale_resume_lock(
    run_dir: Path,
    *,
    stale_after_seconds: float = DEFAULT_OWNERSHIP_STALE_SECONDS,
) -> bool:
    """Remove a stale on-disk lock. Returns True when a stale lock was cleared."""

    lock = read_resume_lock(run_dir)
    if lock is None:
        return _clear_abandoned_lock_claim(run_dir)
    if not is_resume_lock_stale(lock, stale_after_seconds=stale_after_seconds):
        return False
    _PROCESS_REGISTRY.pop(lock.run_id, None)
    return _clear_abandoned_lock_claim(run_dir)


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

    if _is_owner_flock_held(run_dir):
        lock = read_resume_lock(run_dir)
        if lock is not None and lock.run_id == run_id and _is_lock_holder_alive(lock):
            raise RunOwnershipError(
                f"run {run_id} is owned by live process pid={lock.pid}",
                code="run_owned_by_live_process",
            )
        raise RunOwnershipError(
            f"run {run_id} is owned by a live continuation",
            code="run_owned_by_live_process",
        )

    clear_stale_resume_lock(run_dir)
    lock = read_resume_lock(run_dir)
    if lock is None:
        return
    if lock.run_id != run_id:
        raise RunOwnershipError(
            f"run {run_id} resume lock belongs to {lock.run_id}",
            code="run_owned_by_live_process",
        )
    if _is_lock_holder_alive(lock):
        raise RunOwnershipError(
            f"run {run_id} is owned by live process pid={lock.pid}",
            code="run_owned_by_live_process",
        )


def _raise_if_live_lock(run_id: str, lock: ResumeLockRecord) -> None:
    if lock.run_id != run_id:
        raise RunOwnershipError(
            f"run {run_id} resume lock belongs to {lock.run_id}",
            code="run_owned_by_live_process",
        )
    raise RunOwnershipError(
        f"run {run_id} is owned by live process pid={lock.pid}",
        code="run_owned_by_live_process",
    )


def _acquire_owner_flock(run_dir: Path) -> int:
    flock_path = owner_flock_path(run_dir)
    flock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(flock_path, os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


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
        process_identity=process_identity_for_pid(os.getpid()),
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    _clear_abandoned_lock_claim(run_dir)
    flock_fd = _acquire_owner_flock(run_dir)
    metadata_path = resume_lock_metadata_path(run_dir)
    _write_lock_metadata(metadata_path, record)
    _PROCESS_REGISTRY[run_id] = owner_token
    _FLOCK_REGISTRY[run_id] = flock_fd
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

    flock_fd = _FLOCK_REGISTRY.pop(run_id, None)
    if flock_fd is not None:
        _release_flock_fd(flock_fd)

    lock = read_resume_lock(run_dir)
    if lock is None:
        return
    if lock.owner_token != owner_token:
        return
    _clear_lock_storage(run_dir)


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

    if _is_owner_flock_held(run_dir):
        lock = read_resume_lock(run_dir)
        if lock is None:
            return True
        return _is_lock_holder_alive(lock)
    clear_stale_resume_lock(run_dir)
    lock = read_resume_lock(run_dir)
    if lock is None:
        return False
    return _is_lock_holder_alive(lock)
