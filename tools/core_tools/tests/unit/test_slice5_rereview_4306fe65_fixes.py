"""Slice 5 rereview 4306fe65: normal stream EOF must wait/reap the janitor."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider.cursor import CursorProvider, _SubprocessStdoutIterator
from core_tools.provider.errors import ProviderTurnError
from tests.conftest import close_and_reap_iterator


def _idle_config() -> dict:
    return {
        "limits": {
            "provider": {
                "turn_idle_timeout_seconds": 2.0,
                "max_retries_per_call": 0,
            }
        }
    }


def _assistant_script(text: str = "ok") -> str:
    init = json.dumps(
        {"type": "system", "subtype": "init", "session_id": "chat-eof-reap"}
    )
    payload = json.dumps(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}
    )
    return (
        "import sys\n"
        f"print({init!r}, flush=True)\n"
        f"print({payload!r}, flush=True)\n"
    )


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX janitor wait")
def test_read_nonempty_line_eof_waits_subprocess_before_stopiteration(
    tmp_path: Path,
) -> None:
    iterator = _SubprocessStdoutIterator(
        [sys.executable, "-c", "print('ready', flush=True)\n"],
        tmp_path,
    )
    try:
        iterator.wait_agent_started(timeout=2.0)
        proc = iterator._proc
        while True:
            try:
                line = iterator.read_nonempty_line(2.0)
            except StopIteration:
                assert proc.poll() is not None
                assert proc.returncode is not None
                break
            if line is None:
                pytest.fail("idle timeout before EOF")
    finally:
        close_and_reap_iterator(iterator)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX janitor wait")
def test_stream_events_reaps_janitor_when_turn_completes(tmp_path: Path) -> None:
    holder: dict[str, _SubprocessStdoutIterator] = {}

    def runner(argv: list[str], cwd: Path):
        del argv
        iterator = _SubprocessStdoutIterator(
            [sys.executable, "-c", _assistant_script()], cwd
        )
        holder["it"] = iterator
        return iterator

    agent = tmp_path / "agent"
    agent.write_text("", encoding="utf-8")
    provider = CursorProvider(
        _idle_config(),
        workspace=tmp_path,
        runner=runner,
        binary=str(agent),
        skip_probe=True,
    )
    with patch(
        "core_tools.provider.process_identity.capture_process_group_identities",
        return_value=[],
    ):
        session_id = provider.start_primary_session("planner", {"goal": "x"})
        list(provider.stream_events(session_id))
    canonical = provider.canonical_session_id(session_id)
    session = provider._sessions[canonical]
    proc = holder["it"]._proc
    assert session.turn_complete is True
    assert proc.returncode is not None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX janitor wait")
def test_fast_stream_events_loop_leaves_no_zombie_descendants(tmp_path: Path) -> None:
    from tests.conftest import _is_pytest_infrastructure, _python_descendant_pids

    parent = os.getpid()
    before = set(_python_descendant_pids(parent))
    holder: dict[str, _SubprocessStdoutIterator] = {}

    def runner(argv: list[str], cwd: Path):
        del argv
        iterator = _SubprocessStdoutIterator(
            [sys.executable, "-c", _assistant_script("loop")], cwd
        )
        holder["it"] = iterator
        return iterator

    agent = tmp_path / "agent"
    agent.write_text("", encoding="utf-8")
    provider = CursorProvider(
        _idle_config(),
        workspace=tmp_path,
        runner=runner,
        binary=str(agent),
        skip_probe=True,
    )
    with patch(
        "core_tools.provider.process_identity.capture_process_group_identities",
        return_value=[],
    ):
        session_id = provider.start_primary_session("planner", {"goal": "x"})
        for _ in range(20):
            list(provider.stream_events(session_id))
            assert holder["it"]._proc.returncode is not None
            leftover = {
                pid: cmd
                for pid, cmd in _python_descendant_pids(parent).items()
                if pid not in before and not _is_pytest_infrastructure(cmd)
            }
            assert leftover == {}, leftover


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX janitor wait")
def test_iterator_and_read_nonempty_line_propagate_the_same_exit_error(
    tmp_path: Path,
) -> None:
    script = "import sys\nprint('ready', flush=True)\nsys.exit(7)\n"

    def drain_next(iterator: _SubprocessStdoutIterator):
        iterator.wait_agent_started(timeout=2.0)
        try:
            return list(iterator), None
        except Exception as exc:
            return None, type(exc)

    def drain_read(iterator: _SubprocessStdoutIterator):
        iterator.wait_agent_started(timeout=2.0)
        try:
            while True:
                line = iterator.read_nonempty_line(2.0)
                if line is None:
                    pytest.fail("idle timeout before EOF")
        except StopIteration:
            return [], None
        except Exception as exc:
            return None, type(exc)

    next_it = _SubprocessStdoutIterator([sys.executable, "-c", script], tmp_path)
    read_it = _SubprocessStdoutIterator([sys.executable, "-c", script], tmp_path)
    try:
        _lines_next, err_next = drain_next(next_it)
        _lines_read, err_read = drain_read(read_it)
    finally:
        close_and_reap_iterator(next_it)
        close_and_reap_iterator(read_it)
    assert err_next is ProviderTurnError
    assert err_read is err_next
    assert next_it._proc.returncode is not None
    assert read_it._proc.returncode is not None
