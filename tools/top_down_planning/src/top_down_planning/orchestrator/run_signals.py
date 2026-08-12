"""Signal handling for blocking run continuations."""

from __future__ import annotations

import signal
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


@contextmanager
def trap_run_interrupt_signals() -> Iterator[None]:
    """Translate SIGINT/SIGTERM into ``KeyboardInterrupt`` during a run loop."""

    previous: dict[int, Any] = {}

    def _raise_keyboard_interrupt(_signum: int, _frame: object | None) -> None:
        raise KeyboardInterrupt

    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            previous[signum] = signal.signal(signum, _raise_keyboard_interrupt)
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


@contextmanager
def defer_run_interrupt_signals() -> Iterator[None]:
    """Shield SIGINT/SIGTERM during teardown, then replay the first pending signal."""

    previous: dict[int, Any] = {}
    pending: set[int] = set()

    def _record_signal(signum: int, _frame: object | None) -> None:
        pending.add(signum)

    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            previous[signum] = signal.signal(signum, _record_signal)
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
        if pending:
            raise KeyboardInterrupt


@contextmanager
def ignore_repeated_run_interrupt_signals() -> Iterator[None]:
    """Ignore repeated SIGINT/SIGTERM while persisting cancellation."""

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


__all__ = [
    "defer_run_interrupt_signals",
    "ignore_repeated_run_interrupt_signals",
    "trap_run_interrupt_signals",
]
