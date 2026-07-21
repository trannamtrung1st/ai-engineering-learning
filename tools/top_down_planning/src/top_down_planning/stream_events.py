"""JSONL planning event stream for --stream-json."""

from __future__ import annotations

import json
import sys
from typing import Any


class StreamEmitter:
    def __init__(self, *, enabled: bool) -> None:
        self.enabled = enabled

    def emit(self, event_type: str, **fields: Any) -> None:
        if not self.enabled:
            return
        payload = {"type": event_type, **fields}
        sys.stdout.write(json.dumps(payload, default=str) + "\n")
        sys.stdout.flush()
