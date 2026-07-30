"""Unit tests for persistence utilities."""

from __future__ import annotations

import json
from pathlib import Path

from core_tools.persistence import atomic_write_json, digest_text


def test_atomic_write_json_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "payload.json"
    payload = {"b": 2, "a": 1}
    atomic_write_json(path, payload)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded == payload


def test_digest_text_normalizes_newlines() -> None:
    assert digest_text("a\r\nb") == digest_text("a\nb")
