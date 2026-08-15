"""Slice 5 rereview eb572b0: long-line drain, one CleanupDeadline, POSIX-only trees."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider.cursor import CursorProvider, _SubprocessStdoutIterator
from core_tools.provider.errors import ProviderUnsupportedPlatformError
from core_tools.provider.process_cleanup import terminate_process_tree
from core_tools.provider.process_identity import (
    IdentityInspectState,
    ProcessIdentity,
    _current_group_identities,
    terminate_verified_process_identity,
)


def _idle_config() -> dict:
    return {
        "limits": {
            "provider": {
                "turn_idle_timeout_seconds": 2.0,
                "max_retries_per_call": 0,
            }
        }
    }


def _provider(tmp_path: Path, runner) -> CursorProvider:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    return CursorProvider(
        _idle_config(),
        workspace=tmp_path,
        runner=runner,
        binary=str(agent_path),
        skip_probe=True,
    )


def _script_runner(script: str):
    def runner(argv: list[str], cwd: Path):
        del argv
        return _SubprocessStdoutIterator([sys.executable, "-c", script], cwd)

    return runner


def _system_init(session_id: str, extra: str = "") -> str:
    payload = {
        "type": "system",
        "subtype": "init",
        "session_id": session_id,
        "padding": extra,
    }
    return json.dumps(payload)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess stdout drain")
@pytest.mark.parametrize("nbytes", [8192, 65536])
def test_long_final_json_without_newline_survives_immediate_exit(
    tmp_path: Path, nbytes: int
) -> None:
    session_id = "chat-long-line"
    padding = "x" * nbytes
    payload = _system_init(session_id, extra=padding)
    assert len(payload.encode("utf-8")) > 4096
    script = (
        "import sys\n"
        f"sys.stdout.write({payload!r})\n"
        "sys.stdout.flush()\n"
    )
    provider = _provider(tmp_path, _script_runner(script))
    started = provider.start_primary_session("planner", {"goal": "x"})
    list(provider.stream_events(started))
    assert provider.canonical_session_id(started) == session_id


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess stdout drain")
def test_two_long_json_records_plus_exit_are_both_parsed(tmp_path: Path) -> None:
    first = _system_init("chat-two-long", extra="a" * 5000)
    second = json.dumps(
        {
            "type": "assistant",
            "session_id": "chat-two-long",
            "message": {"content": [{"type": "text", "text": "kept"}]},
            "padding": "b" * 5000,
        }
    )
    script = (
        "import sys\n"
        f"sys.stdout.write({first!r} + '\\n' + {second!r} + '\\n')\n"
        "sys.stdout.flush()\n"
    )
    provider = _provider(tmp_path, _script_runner(script))
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    events = list(provider.stream_events(session_id))
    texts = [str(event.get("text") or "") for event in events]
    assert any("kept" in text for text in texts)
    assert provider.canonical_session_id(session_id) == "chat-two-long"


def test_windows_process_tree_is_unsupported() -> None:
    with patch("core_tools.provider.process_cleanup.sys.platform", "win32"):
        with pytest.raises(ProviderUnsupportedPlatformError, match="POSIX"):
            terminate_process_tree(object(), timeout=0.1)  # type: ignore[arg-type]


def test_initial_inspect_consumes_budget_remaining_for_terminate() -> None:
    identity = ProcessIdentity(pid=1, start_time="1")
    seen: list[float | None] = []

    def fake_inspect(target, timeout=None):
        del target
        seen.append(timeout)
        time.sleep(0.08)
        return IdentityInspectState.LIVE_MATCH

    def fake_linux(target, *, timeout=None):
        del target
        seen.append(timeout)
        from core_tools.provider.process_identity import TerminateIdentityResult

        return TerminateIdentityResult.TERMINATED

    with patch(
        "core_tools.provider.process_identity.inspect_process_identity",
        side_effect=fake_inspect,
    ), patch(
        "core_tools.provider.process_identity._pidfd_supported",
        return_value=True,
    ), patch(
        "core_tools.provider.process_identity._terminate_linux_identity",
        side_effect=fake_linux,
    ):
        terminate_verified_process_identity(identity, timeout=0.2)
    assert seen[0] == 0.2 or (seen[0] is not None and seen[0] <= 0.2)
    assert seen[1] is not None
    assert seen[1] < 0.2
    assert seen[1] <= 0.14


def test_group_identity_reads_share_shrinking_deadline() -> None:
    seen: list[float | None] = []

    def fake_list(pgid, timeout=None):
        del pgid
        seen.append(timeout)
        return [11, 12, 13]

    def fake_read(pid, run_id=None, timeout=None):
        del run_id
        seen.append(timeout)
        time.sleep(0.04)
        return ProcessIdentity(pid=pid, start_time="1")

    with patch(
        "core_tools.provider.process_identity.list_process_group_pids",
        side_effect=fake_list,
    ), patch(
        "core_tools.provider.process_identity.read_process_identity",
        side_effect=fake_read,
    ):
        identities = _current_group_identities(99, timeout=0.2)
    assert identities is not None
    read_timeouts = seen[1:]
    assert read_timeouts[-1] is not None
    assert read_timeouts[0] is not None
    assert read_timeouts[-1] < read_timeouts[0]
