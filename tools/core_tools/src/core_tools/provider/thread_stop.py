"""Best-effort stop for helper threads TDP/Cursor must not leak."""

from __future__ import annotations

import ctypes
import threading


def force_stop_thread(thread: threading.Thread, *, timeout: float) -> None:
    """Ask *thread* to exit, including via ``SystemExit`` injection, then join."""

    if thread.ident is None or not thread.is_alive():
        return
    try:
        ctypes.pythonapi.PyThreadState_SetAsyncExc(
            ctypes.c_ulong(thread.ident),
            ctypes.py_object(SystemExit),
        )
    except Exception:
        pass
    thread.join(timeout=max(0.0, timeout))
    if thread.is_alive():
        try:
            ctypes.pythonapi.PyThreadState_SetAsyncExc(
                ctypes.c_ulong(thread.ident),
                ctypes.py_object(SystemExit),
            )
        except Exception:
            pass
        thread.join(timeout=max(0.0, timeout))
