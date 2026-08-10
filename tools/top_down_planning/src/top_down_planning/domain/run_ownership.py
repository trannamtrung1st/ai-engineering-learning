"""Live-process run ownership and revision CAS helpers (proposal §18.1)."""

from __future__ import annotations

import contextvars
import json
import os
import re
import signal
import time
import uuid
from contextlib import contextmanager
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError as exc:
    raise ImportError(
        "top_down_planning run ownership requires POSIX (fcntl). "
        "Cross-process resume locking is not supported on this platform."
    ) from exc

from top_down_planning.domain.errors import DomainError

DEFAULT_OWNERSHIP_STALE_SECONDS = 4 * 60 * 60
_LOCK_WAIT_ATTEMPTS = 20
_LOCK_WAIT_INTERVAL_SECONDS = 0.025

_RESUME_LOCK_FILENAME = ".resume.lock"
_RESUME_LOCK_DIRNAME = ".resume.lock.d"
_LOCK_METADATA_FILENAME = "owner.json"
_OWNER_FLOCK_FILENAME = ".owner.lock"
_OWNERSHIP_REGISTRY: dict[str, dict[str, Any]] = {}
_OWNERSHIP_CLEANUP_FAILURES: list[dict[str, Any]] = []
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
    return run_id in _OWNERSHIP_REGISTRY


def ownership_cleanup_failures() -> list[dict[str, Any]]:
    """Return secondary ownership metadata cleanup failures recorded this process."""

    return list(_OWNERSHIP_CLEANUP_FAILURES)


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


def _unlink_if_present(path: Path) -> bool:
    if not path.is_file():
        return False
    path.unlink()
    return True


def _clear_legacy_lock_file(run_dir: Path) -> bool:
    return _unlink_if_present(resume_lock_path(run_dir))


def _clear_owner_metadata(run_dir: Path) -> bool:
    """Remove ephemeral ownership metadata without touching the flock sentinel."""

    cleared = False
    if _unlink_if_present(resume_lock_metadata_path(run_dir)):
        cleared = True
    if _clear_legacy_lock_file(run_dir):
        cleared = True
    return cleared


def _has_flock_sentinel(run_dir: Path) -> bool:
    return owner_flock_path(run_dir).is_file()


def _ensure_lock_infrastructure(run_dir: Path) -> None:
    lock_dir = resume_lock_dir(run_dir)
    lock_dir.mkdir(parents=True, exist_ok=True)
    flock_path = owner_flock_path(run_dir)
    if flock_path.is_file():
        return
    fd = os.open(flock_path, os.O_CREAT | os.O_RDWR, 0o644)
    os.close(fd)


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


def _try_acquire_flock_nonblocking(
    run_dir: Path,
    *,
    create_sentinel: bool = False,
) -> int | None:
    flock_path = owner_flock_path(run_dir)
    if not flock_path.is_file():
        if not create_sentinel:
            return None
        _ensure_lock_infrastructure(run_dir)
    fd = os.open(flock_path, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    except BaseException:
        os.close(fd)
        raise
    return fd


@contextmanager
def _defer_interrupt_signals() -> Iterator[None]:
    previous: dict[int, Any] = {}

    def _ignore_signal(_signum: int, _frame: object | None) -> None:
        return None

    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            previous[signum] = signal.signal(signum, _ignore_signal)
        except (OSError, ValueError):
            continue
    try:
        yield
    finally:
        for signum, handler in previous.items():
            try:
                signal.signal(signum, handler)
            except (OSError, ValueError):
                pass


def _release_flock_fd(fd: int) -> None:
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def _is_owner_flock_held(run_dir: Path) -> bool:
    flock_path = owner_flock_path(run_dir)
    if not flock_path.is_file():
        return False
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
    metadata_path = resume_lock_metadata_path(run_dir)
    lock_dir = resume_lock_dir(run_dir)
    flock_path = owner_flock_path(run_dir)

    if legacy_path.is_file():
        try:
            legacy_content = legacy_path.read_text(encoding="utf-8").strip()
        except OSError:
            return False
        if legacy_content and read_resume_lock(run_dir) is None:
            return False

    if (
        lock_dir.is_dir()
        and not metadata_path.is_file()
        and not legacy_path.is_file()
        and not flock_path.is_file()
    ):
        return True

    create_sentinel = metadata_path.is_file() or legacy_path.is_file() or flock_path.is_file()
    flock_fd = _try_acquire_flock_nonblocking(run_dir, create_sentinel=create_sentinel)
    if flock_fd is None:
        return False

    try:
        if metadata_path.is_file():
            lock = _read_lock_metadata(metadata_path)
            if lock is not None:
                if _is_lock_holder_alive(lock):
                    return False
                return _clear_owner_metadata(run_dir)
            if _metadata_holder_alive(metadata_path):
                return False
            return _clear_owner_metadata(run_dir)

        if legacy_path.is_file():
            lock = read_resume_lock(run_dir)
            if lock is not None:
                if _is_lock_holder_alive(lock):
                    return False
                return _clear_owner_metadata(run_dir)
            try:
                content = legacy_path.read_text(encoding="utf-8").strip()
            except OSError:
                return False
            if not content:
                return _clear_owner_metadata(run_dir)
            return False

        if lock_dir.is_dir():
            return _clear_owner_metadata(run_dir)

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

    entry = _OWNERSHIP_REGISTRY.get(run_id)
    if entry is not None:
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

    if _has_flock_sentinel(run_dir):
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
    _ensure_lock_infrastructure(run_dir)
    flock_path = owner_flock_path(run_dir)
    fd = os.open(flock_path, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise RunOwnershipError(
            "run is owned by a live continuation",
            code="run_owned_by_live_process",
        )
    except BaseException:
        os.close(fd)
        raise
    return fd


def _cleanup_failed_acquire(run_dir: Path) -> None:
    """Remove partial ownership metadata after a failed acquire attempt."""

    metadata_path = resume_lock_metadata_path(run_dir)
    try:
        metadata_path.unlink(missing_ok=True)
    except OSError:
        pass


def _publish_run_ownership(run_id: str, owner_token: str, flock_fd: int) -> None:
    _OWNERSHIP_REGISTRY[run_id] = {"owner_token": owner_token, "fd": flock_fd}


def _rollback_failed_acquire(
    run_id: str,
    run_dir: Path,
    flock_fd: int | None,
) -> None:
    with _defer_interrupt_signals():
        entry = _OWNERSHIP_REGISTRY.pop(run_id, None)
        fd_to_release = int(entry["fd"]) if entry is not None else flock_fd
        if fd_to_release is None:
            return
        if entry is None:
            _cleanup_failed_acquire(run_dir)
        _release_flock_fd(fd_to_release)


def _record_ownership_cleanup_failure(
    run_dir: Path,
    run_id: str | None,
    exc: OSError,
) -> None:
    _OWNERSHIP_CLEANUP_FAILURES.append(
        {
            "type": "ownership_cleanup_failed",
            "run_id": run_id,
            "path": str(resume_lock_metadata_path(run_dir)),
            "error_class": type(exc).__name__,
            "message": str(exc),
            "safe_to_retry": True,
        }
    )


def _clear_owner_metadata_best_effort(
    run_dir: Path,
    *,
    run_id: str | None = None,
) -> None:
    try:
        _clear_owner_metadata(run_dir)
    except OSError as exc:
        _record_ownership_cleanup_failure(run_dir, run_id, exc)


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
    flock_fd: int | None = None
    try:
        flock_fd = _acquire_owner_flock(run_dir)
        _clear_owner_metadata(run_dir)
        metadata_path = resume_lock_metadata_path(run_dir)
        _write_lock_metadata(metadata_path, record)
        _publish_run_ownership(run_id, owner_token, flock_fd)
        flock_fd = None
        return owner_token
    except BaseException:
        _rollback_failed_acquire(run_id, run_dir, flock_fd)
        raise


def release_run_ownership(
    run_id: str,
    *,
    run_dir: Path,
    owner_token: str,
) -> None:
    """Release ownership acquired by ``acquire_run_ownership``."""

    entry = _OWNERSHIP_REGISTRY.get(run_id)
    if entry is None or entry.get("owner_token") != owner_token:
        return

    flock_fd = int(entry["fd"])
    with _defer_interrupt_signals():
        try:
            _clear_owner_metadata_best_effort(run_dir, run_id=run_id)
        finally:
            try:
                _release_flock_fd(flock_fd)
            finally:
                _OWNERSHIP_REGISTRY.pop(run_id, None)


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
        return True
    if _has_flock_sentinel(run_dir):
        return False
    clear_stale_resume_lock(run_dir)
    lock = read_resume_lock(run_dir)
    if lock is None:
        return False
    return _is_lock_holder_alive(lock)
