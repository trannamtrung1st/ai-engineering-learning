#!/usr/bin/env python3
"""Process-backed fake Cursor agent for Slice 10 orphan-cleanup proofs.

Emits one stream-json init event, publishes pid/pgid, then blocks until signal.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path


def _write(path: str | None, text: str) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def main() -> int:
    session_id = os.environ.get("TDP_SLICE10_AGENT_SESSION", "fake-cursor-session")
    sys.stdout.write(
        json.dumps({"type": "system", "subtype": "init", "session_id": session_id}) + "\n"
    )
    sys.stdout.flush()
    _write(os.environ.get("TDP_SLICE10_AGENT_READY"), str(os.getpid()))
    try:
        pgid = os.getpgid(0)
    except OSError:
        pgid = os.getpid()
    _write(os.environ.get("TDP_SLICE10_AGENT_PGID"), str(pgid))

    def _exit(*_args: object) -> None:
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _exit)
    signal.signal(signal.SIGINT, _exit)
    time.sleep(float(os.environ.get("TDP_SLICE10_AGENT_BLOCK_SECONDS", "30")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
