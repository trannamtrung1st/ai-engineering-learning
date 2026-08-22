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


def _write_record_script(payload: bytes, *, chunk_size: int | None = None, hold: bool = False) -> str:
    """Emit one NDJSON record; optional write chunking and a hold so the child stays alive."""

    hold_tail = "import time\ntime.sleep(60)\n" if hold else ""
    if chunk_size is None:
        return (
            "import sys\n"
            f"sys.stdout.buffer.write({payload!r})\n"
            "sys.stdout.buffer.flush()\n"
            f"{hold_tail}"
        )
    return (
        "import sys\n"
        f"data = {payload!r}\n"
        f"chunk = {int(chunk_size)}\n"
        "offset = 0\n"
        "while offset < len(data):\n"
        "    sys.stdout.buffer.write(data[offset:offset + chunk])\n"
        "    sys.stdout.buffer.flush()\n"
        "    offset += chunk\n"
        f"{hold_tail}"
    )


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess stdout")
def test_oversized_line_is_rejected_when_newline_crosses_the_cap(
    tmp_path: Path,
) -> None:
    """A 4096-byte read can land the newline in the same chunk that crosses the cap."""

    cap = 5000
    record = (b"x" * 6000) + b"\n"
    iterator = _SubprocessStdoutIterator(
        [sys.executable, "-c", _write_record_script(record, hold=True)],
        tmp_path,
        max_record_bytes=cap,
    )
    try:
        with pytest.raises(ProviderStreamRecordTooLargeError, match=str(cap)):
            iterator.read_nonempty_line(1.0)
    finally:
        terminate_process_tree(iterator._proc)
        iterator.close()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess stdout")
def test_oversized_line_is_rejected_when_child_exits_immediately(
    tmp_path: Path,
) -> None:
    cap = 2048
    record = (b"z" * (cap + 16)) + b"\n"
    iterator = _SubprocessStdoutIterator(
        [sys.executable, "-c", _write_record_script(record)],
        tmp_path,
        max_record_bytes=cap,
    )
    try:
        with pytest.raises(ProviderStreamRecordTooLargeError, match=str(cap)):
            next(iterator)
    finally:
        close_and_reap_iterator(iterator)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess stdout")
@pytest.mark.parametrize(
    ("payload_len", "should_accept"),
    [
        (63, True),
        (64, False),
        (65, False),
    ],
)
def test_record_limit_uses_exact_assembled_boundary(
    tmp_path: Path, payload_len: int, should_accept: bool
) -> None:
    cap = 64
    record = (b"w" * payload_len) + b"\n"
    iterator = _SubprocessStdoutIterator(
        [sys.executable, "-c", _write_record_script(record)],
        tmp_path,
        max_record_bytes=cap,
    )
    try:
        if should_accept:
            assert next(iterator) == "w" * payload_len
        else:
            with pytest.raises(ProviderStreamRecordTooLargeError, match=str(cap)):
                next(iterator)
    finally:
        close_and_reap_iterator(iterator)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess stdout")
@pytest.mark.parametrize("chunk_size", [1, 16, 64, 4096, 8192])
def test_record_limit_rejection_does_not_depend_on_write_chunk_size(
    tmp_path: Path, chunk_size: int
) -> None:
    cap = 128
    record = (b"q" * (cap + 8)) + b"\n"
    iterator = _SubprocessStdoutIterator(
        [sys.executable, "-c", _write_record_script(record, chunk_size=chunk_size)],
        tmp_path,
        max_record_bytes=cap,
    )
    try:
        with pytest.raises(ProviderStreamRecordTooLargeError, match=str(cap)):
            next(iterator)
    finally:
        close_and_reap_iterator(iterator)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess stdout")
@pytest.mark.parametrize("chunk_size", [1, 16, 64, 4096])
def test_record_limit_acceptance_does_not_depend_on_write_chunk_size(
    tmp_path: Path, chunk_size: int
) -> None:
    cap = 128
    payload = b"a" * (cap - 1)
    iterator = _SubprocessStdoutIterator(
        [sys.executable, "-c", _write_record_script(payload + b"\n", chunk_size=chunk_size)],
        tmp_path,
        max_record_bytes=cap,
    )
    try:
        assert next(iterator) == payload.decode("ascii")
    finally:
        close_and_reap_iterator(iterator)
