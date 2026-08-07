"""Unit tests for persistence utilities."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.persistence import atomic_write_json, digest_text


def test_atomic_write_json_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "payload.json"
    payload = {"b": 2, "a": 1}
    atomic_write_json(path, payload)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded == payload


def test_exclusive_create_bytes_rejects_existing_file(tmp_path: Path) -> None:
    from core_tools.persistence import exclusive_create_bytes

    path = tmp_path / "artifact.txt"
    exclusive_create_bytes(path, b"first")
    try:
        exclusive_create_bytes(path, b"second")
        raised = False
    except FileExistsError:
        raised = True
    assert raised
    assert path.read_bytes() == b"first"


def test_try_exclusive_file_lock_reports_busy(tmp_path: Path) -> None:
    from core_tools.persistence import exclusive_file_lock, try_exclusive_file_lock

    lock_path = tmp_path / "test.lock"
    with exclusive_file_lock(lock_path):
        with try_exclusive_file_lock(lock_path) as acquired:
            assert acquired is False
    with try_exclusive_file_lock(lock_path) as acquired:
        assert acquired is True


def test_exclusive_create_bytes_leaves_no_partial_final_artifact_on_write_failure(
    tmp_path: Path,
) -> None:
    from core_tools.persistence import exclusive_create_bytes

    path = tmp_path / "artifact.bin"
    original_write_bytes = Path.write_bytes

    def fail_temp_write(self: Path, data: bytes) -> int:
        if self.name.startswith(".artifact.bin.create"):
            raise OSError("simulated incomplete write")
        return original_write_bytes(self, data)

    with patch.object(Path, "write_bytes", fail_temp_write):
        with pytest.raises(OSError, match="simulated incomplete write"):
            exclusive_create_bytes(path, b"payload")

    assert not path.exists()
    exclusive_create_bytes(path, b"payload")
    assert path.read_bytes() == b"payload"


def test_digest_text_normalizes_newlines() -> None:
    assert digest_text("a\r\nb") == digest_text("a\nb")
