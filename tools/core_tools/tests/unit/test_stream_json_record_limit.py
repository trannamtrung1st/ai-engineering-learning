"""Configurable Cursor stream-json record size limit."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider.cursor import (
    MAX_STREAM_JSON_RECORD_BYTES,
    _MAX_IDLE_RESCUE_BYTES,
    _SubprocessStdoutIterator,
    max_stream_json_record_bytes,
)
from core_tools.provider.errors import ProviderStreamRecordTooLargeError
from core_tools.provider.process_cleanup import terminate_process_tree
from core_tools.provider.process_identity import (
    IdentityInspectState,
    TerminateIdentityResult,
)
from tests.conftest import close_and_reap_iterator, reap_hold_process, spawn_hold_process


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
        "import os, sys\n"
        "os.write(1, b'x' * 4096)\n"
        "sys.stdout.flush()\n"
        "sys.stdin.read()\n"
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


def _write_payload_argv(tmp_path: Path, payload: bytes, *, hold: bool = False) -> list[str]:
    """Run a file-backed writer so large records are not passed on argv."""

    blob = tmp_path / "records.bin"
    blob.write_bytes(payload)
    script = tmp_path / "write_records.py"
    hold_tail = "sys.stdin.read()\n" if hold else ""
    script.write_text(
        "import sys\n"
        f"sys.stdout.buffer.write(open({str(blob)!r}, 'rb').read())\n"
        "sys.stdout.buffer.flush()\n"
        f"{hold_tail}",
        encoding="utf-8",
    )
    return [sys.executable, str(script)]


def _write_record_script(payload: bytes, *, chunk_size: int | None = None, hold: bool = False) -> str:
    """Emit one NDJSON record; optional write chunking and a hold so the child stays alive."""

    hold_tail = "sys.stdin.read()\n" if hold else ""
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
def test_exiting_oversized_flood_does_not_buffer_past_rescue_slack(
    tmp_path: Path,
) -> None:
    """EOF drain must stop at the cap, not slurp the rest of a multi-chunk flood."""

    record = (b"x" * (512 * 1024)) + b"\n"
    iterator = _SubprocessStdoutIterator(
        _write_payload_argv(tmp_path, record),
        tmp_path,
        max_record_bytes=MAX_STREAM_JSON_RECORD_BYTES,
    )
    try:
        # Janitor-bound poll() stays None until reap is allowed. Force the
        # exit-drain path that Darwin CI hits once the janitor reports CLEAN.
        iterator._proc.poll = lambda *args, **kwargs: 0
        with pytest.raises(ProviderStreamRecordTooLargeError, match=str(MAX_STREAM_JSON_RECORD_BYTES)):
            next(iterator)
        assert len(iterator._stdout_buf) <= _MAX_IDLE_RESCUE_BYTES + 65536
    finally:
        close_and_reap_iterator(iterator)


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
def test_second_record_is_rejected_after_valid_prefix_on_exit_drain(
    tmp_path: Path,
) -> None:
    cap = MAX_STREAM_JSON_RECORD_BYTES
    payload = b"{}\n" + (b"x" * (512 * 1024)) + b"\n"
    iterator = _SubprocessStdoutIterator(
        _write_payload_argv(tmp_path, payload),
        tmp_path,
        max_record_bytes=cap,
    )
    try:
        real_poll = iterator._proc.poll
        iterator._proc.poll = lambda *args, **kwargs: 0
        try:
            assert next(iterator) == "{}"
            with pytest.raises(ProviderStreamRecordTooLargeError, match=str(cap)):
                next(iterator)
        finally:
            iterator._proc.poll = real_poll
        assert len(iterator._stdout_buf) <= cap + 65536
    finally:
        close_and_reap_iterator(iterator)


def _wait_until_exited(proc, timeout: float = 0.35) -> bool:
    """Treat a reaped or zombie writer as gone; wrapped poll stays None until status."""

    from core_tools.provider.process_cleanup import is_pid_alive

    raw_poll = getattr(proc, "_core_tools_raw_poll", proc.poll)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if callable(raw_poll):
            try:
                if raw_poll() is not None:
                    return True
            except Exception:
                pass
        if proc.pid is not None and not is_pid_alive(proc.pid):
            return True
        time.sleep(0.01)
    if callable(raw_poll):
        try:
            if raw_poll() is not None:
                return True
        except Exception:
            pass
    return bool(proc.pid is not None and not is_pid_alive(proc.pid))


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess stdout")
def test_rejected_oversized_flood_does_not_leave_a_blocked_writer(
    tmp_path: Path,
) -> None:
    """Closing the reader must unblock a flood so the child can exit."""

    record = (b"x" * (512 * 1024)) + b"\n"
    iterator = _SubprocessStdoutIterator(
        _write_payload_argv(tmp_path, record, hold=True),
        tmp_path,
        max_record_bytes=MAX_STREAM_JSON_RECORD_BYTES,
    )
    try:
        with pytest.raises(
            ProviderStreamRecordTooLargeError,
            match=str(MAX_STREAM_JSON_RECORD_BYTES),
        ):
            next(iterator)
        assert _wait_until_exited(iterator._proc)
    finally:
        close_and_reap_iterator(iterator)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess stdout")
def test_oversized_writer_is_killed_when_bound_terminate_fails_closed(
    tmp_path: Path,
) -> None:
    """Cap reject must still stop a live writer if bound terminate fails closed."""

    record = (b"x" * (512 * 1024)) + b"\n"
    iterator = _SubprocessStdoutIterator(
        _write_payload_argv(tmp_path, record, hold=True),
        tmp_path,
        max_record_bytes=MAX_STREAM_JSON_RECORD_BYTES,
    )
    try:
        with patch(
            "core_tools.provider.cursor.terminate_verified_process_identity",
            return_value=TerminateIdentityResult.FAILED,
        ):
            with pytest.raises(
                ProviderStreamRecordTooLargeError,
                match=str(MAX_STREAM_JSON_RECORD_BYTES),
            ):
                next(iterator)
        assert _wait_until_exited(iterator._proc)
    finally:
        close_and_reap_iterator(iterator)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess stdout")
def test_oversized_writer_is_killed_when_identity_inspect_is_unverifiable(
    tmp_path: Path,
) -> None:
    """A still-bound live Popen must stop the writer even if identity inspect times out."""

    record = (b"x" * (512 * 1024)) + b"\n"
    iterator = _SubprocessStdoutIterator(
        _write_payload_argv(tmp_path, record, hold=True),
        tmp_path,
        max_record_bytes=MAX_STREAM_JSON_RECORD_BYTES,
    )
    try:
        with patch(
            "core_tools.provider.cursor.inspect_process_identity",
            return_value=IdentityInspectState.UNVERIFIABLE,
        ):
            with pytest.raises(
                ProviderStreamRecordTooLargeError,
                match=str(MAX_STREAM_JSON_RECORD_BYTES),
            ):
                next(iterator)
        assert _wait_until_exited(iterator._proc, timeout=1.0)
    finally:
        close_and_reap_iterator(iterator)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_exited_popen_does_not_killpg_a_reused_or_foreign_pgid() -> None:
    """Numeric PID/PGID match after the bound child exited must not signal a foreign group."""

    victim = spawn_hold_process()

    class ExitedPopen:
        pid = victim.pid
        _core_tools_session_pgid = victim.pid

        def poll(self) -> int:
            return 0

    try:
        _SubprocessStdoutIterator._kill_bound_session_group(None, ExitedPopen())
        assert victim.poll() is None
    finally:
        reap_hold_process(victim)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_unverifiable_inspect_does_not_signal_foreign_group_after_writer_exits(
    tmp_path: Path,
) -> None:
    """UNVERIFIABLE inspect plus a stale cached PGID must not killpg a live stranger."""

    victim = spawn_hold_process()
    cap = 64
    record = (b"z" * (cap + 10)) + b"\n"
    iterator = _exited_iterator_with_buffered_record(tmp_path, record, cap=cap)
    killpg_targets: list[int] = []
    try:
        iterator._proc._core_tools_session_pgid = victim.pid
        with patch(
            "core_tools.provider.cursor.inspect_process_identity",
            return_value=IdentityInspectState.UNVERIFIABLE,
        ), patch(
            "core_tools.provider.cursor.os.getpgid",
            return_value=victim.pid,
        ), patch(
            "core_tools.provider.cursor.os.killpg",
            side_effect=lambda pgid, _sig: killpg_targets.append(pgid),
        ):
            with pytest.raises(ProviderStreamRecordTooLargeError, match=str(cap)):
                next(iterator)
        assert victim.pid not in killpg_targets
        assert victim.poll() is None
    finally:
        close_and_reap_iterator(iterator)
        reap_hold_process(victim)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess stdout")
def test_rejected_second_record_does_not_leave_a_blocked_writer(
    tmp_path: Path,
) -> None:
    cap = MAX_STREAM_JSON_RECORD_BYTES
    payload = b"{}\n" + (b"x" * (512 * 1024)) + b"\n"
    iterator = _SubprocessStdoutIterator(
        _write_payload_argv(tmp_path, payload),
        tmp_path,
        max_record_bytes=cap,
    )
    try:
        assert next(iterator) == "{}"
        with pytest.raises(ProviderStreamRecordTooLargeError, match=str(cap)):
            next(iterator)
        assert _wait_until_exited(iterator._proc)
    finally:
        close_and_reap_iterator(iterator)


def _exited_iterator_with_buffered_record(
    tmp_path: Path, record: bytes, *, cap: int
) -> _SubprocessStdoutIterator:
    """Buffer a complete record after the owned writer/janitor has been reaped."""

    iterator = _SubprocessStdoutIterator(
        [sys.executable, "-c", "raise SystemExit"],
        tmp_path,
        max_record_bytes=cap,
    )
    iterator._stdout_buf.extend(record)
    close_and_reap_iterator(iterator)
    iterator._finished = False
    iterator._stdout_eof = True
    return iterator


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess stdout")
def test_exited_oversized_record_is_rejected_without_group_kill(
    tmp_path: Path,
) -> None:
    cap = 64
    record = (b"z" * (cap + 10)) + b"\n"
    iterator = _exited_iterator_with_buffered_record(tmp_path, record, cap=cap)
    try:
        killpg_calls: list[tuple[int, int]] = []
        with patch(
            "core_tools.provider.cursor.os.killpg",
            side_effect=lambda pgid, sig: killpg_calls.append((pgid, sig)),
        ):
            with pytest.raises(ProviderStreamRecordTooLargeError, match=str(cap)):
                next(iterator)
        assert killpg_calls == []
    finally:
        close_and_reap_iterator(iterator)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess stdout")
def test_stale_cached_pgid_is_not_signaled_after_writer_exits(
    tmp_path: Path,
) -> None:
    victim = spawn_hold_process()
    cap = 64
    record = (b"z" * (cap + 10)) + b"\n"
    iterator = _exited_iterator_with_buffered_record(tmp_path, record, cap=cap)
    try:
        iterator._proc._core_tools_session_pgid = victim.pid
        with pytest.raises(ProviderStreamRecordTooLargeError, match=str(cap)):
            next(iterator)
        assert victim.poll() is None
    finally:
        close_and_reap_iterator(iterator)
        reap_hold_process(victim)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess stdout")
def test_second_complete_record_in_one_read_is_rejected(
    tmp_path: Path,
) -> None:
    cap = 64
    payload = b"hi\n" + (b"y" * 200) + b"\n"
    iterator = _SubprocessStdoutIterator(
        [sys.executable, "-c", _write_record_script(payload)],
        tmp_path,
        max_record_bytes=cap,
    )
    try:
        assert next(iterator) == "hi"
        with pytest.raises(ProviderStreamRecordTooLargeError, match=str(cap)):
            next(iterator)
    finally:
        close_and_reap_iterator(iterator)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess stdout")
def test_oversized_record_after_several_valid_records_is_rejected(
    tmp_path: Path,
) -> None:
    cap = 32
    payload = b"a\n" + b"b\n" + b"c\n" + (b"z" * (cap + 10)) + b"\n"
    iterator = _SubprocessStdoutIterator(
        [sys.executable, "-c", _write_record_script(payload)],
        tmp_path,
        max_record_bytes=cap,
    )
    try:
        assert next(iterator) == "a"
        assert next(iterator) == "b"
        assert next(iterator) == "c"
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
