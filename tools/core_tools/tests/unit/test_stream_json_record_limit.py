"""Configurable Cursor stream-json record size limit."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from core_tools.provider.cursor import (
    MAX_STREAM_JSON_RECORD_BYTES,
    _SubprocessStdoutIterator,
    max_stream_json_record_bytes,
)
from core_tools.provider.errors import ProviderStreamRecordTooLargeError
from core_tools.provider.process_cleanup import terminate_process_tree
from tests.conftest import close_and_reap_iterator


def test_max_stream_json_record_bytes_defaults_to_256kib() -> None:
    assert max_stream_json_record_bytes({}) == MAX_STREAM_JSON_RECORD_BYTES
    assert max_stream_json_record_bytes(None) == MAX_STREAM_JSON_RECORD_BYTES
    assert MAX_STREAM_JSON_RECORD_BYTES == 256 * 1024


def test_max_stream_json_record_bytes_reads_provider_limit() -> None:
    assert (
        max_stream_json_record_bytes(
            {"limits": {"provider": {"max_stream_json_record_bytes": 4096}}}
        )
        == 4096
    )


def test_max_stream_json_record_bytes_rejects_non_positive_as_default() -> None:
    assert (
        max_stream_json_record_bytes(
            {"limits": {"provider": {"max_stream_json_record_bytes": 0}}}
        )
        == MAX_STREAM_JSON_RECORD_BYTES
    )
    assert (
        max_stream_json_record_bytes(
            {"limits": {"provider": {"max_stream_json_record_bytes": -1}}}
        )
        == MAX_STREAM_JSON_RECORD_BYTES
    )
    assert (
        max_stream_json_record_bytes(
            {"limits": {"provider": {"max_stream_json_record_bytes": "nope"}}}
        )
        == MAX_STREAM_JSON_RECORD_BYTES
    )


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess stdout")
def test_configured_record_limit_rejects_oversized_line(tmp_path: Path) -> None:
    script = (
        "import os, sys, time\n"
        "os.write(1, b'x' * 4096)\n"
        "sys.stdout.flush()\n"
        "time.sleep(60)\n"
    )
    iterator = _SubprocessStdoutIterator(
        [sys.executable, "-c", script],
        tmp_path,
        max_record_bytes=2048,
    )
    try:
        started = time.monotonic()
        with pytest.raises(ProviderStreamRecordTooLargeError, match="2048"):
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                iterator.read_nonempty_line(0.05)
        assert time.monotonic() - started < 1.2
    finally:
        terminate_process_tree(iterator._proc)
        iterator.close()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess stdout")
def test_configured_record_limit_accepts_line_under_cap(tmp_path: Path) -> None:
    payload = '{"type":"assistant","message":{"content":[{"type":"text","text":"' + ("y" * 512) + '"}]}}'
    script = (
        "import sys\n"
        f"sys.stdout.write({payload!r} + '\\n')\n"
        "sys.stdout.flush()\n"
    )
    iterator = _SubprocessStdoutIterator(
        [sys.executable, "-c", script],
        tmp_path,
        max_record_bytes=2048,
    )
    try:
        line = iterator.read_nonempty_line(1.0)
        assert line is not None
        assert "yyyy" in line
    finally:
        close_and_reap_iterator(iterator)
