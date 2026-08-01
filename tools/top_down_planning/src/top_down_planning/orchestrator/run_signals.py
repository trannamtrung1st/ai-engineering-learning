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
    """Ignore SIGINT/SIGTERM while persisting cancel teardown."""

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


__all__ = ["defer_run_interrupt_signals", "trap_run_interrupt_signals"]
