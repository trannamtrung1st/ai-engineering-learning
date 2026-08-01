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


__all__ = ["trap_run_interrupt_signals"]
