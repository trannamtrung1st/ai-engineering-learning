"""OS-level file locks for cross-process critical sections."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def _try_acquire_exclusive_lock(handle) -> bool:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


def _acquire_exclusive_lock(handle) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _release_exclusive_lock(handle) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def try_exclusive_file_lock(lock_path: Path) -> Iterator[bool]:
    """Acquire an exclusive advisory lock when available.

    Yields ``True`` when the lock was acquired and ``False`` when another holder
  already owns it.
    """

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    acquired = False
    try:
        acquired = _try_acquire_exclusive_lock(handle)
        yield acquired
    finally:
        if acquired:
            _release_exclusive_lock(handle)
        handle.close()


@contextmanager
def exclusive_file_lock(lock_path: Path) -> Iterator[None]:
    """Acquire an exclusive advisory lock on ``lock_path`` until the block exits."""

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    try:
        _acquire_exclusive_lock(handle)
        yield
    finally:
        _release_exclusive_lock(handle)
        handle.close()
