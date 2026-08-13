"""Slice 5 tenth re-review regression tests (S5-RR10-001 through S5-RR10-004)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider.cursor import CursorProvider
from core_tools.provider.process_identity import (
    IdentityInspectState,
    ProcessIdentity,
    TerminateIdentityResult,
)
from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.orchestrator.provider_teardown import (
    _retry_terminate_provider_identities,
    teardown_provider_sessions,
)
from top_down_planning.orchestrator.errors import ProviderTeardownError


def test_retry_terminate_provider_identities_does_not_kill_reused_pid(
    tmp_path: Path,
) -> None:
    original = ProcessIdentity(pid=4242, start_time="100", run_id="run-a")

    with patch(
        "top_down_planning.orchestrator.provider_teardown.inspect_process_identity",
        return_value=IdentityInspectState.IDENTITY_MISMATCH,
    ):
        with patch(
            "top_down_planning.orchestrator.provider_teardown.terminate_verified_process_identity",
        ) as terminate:
            result = _retry_terminate_provider_identities([original])

    assert result.stale_reconciled == (4242,)
    terminate.assert_not_called()


def test_retry_terminate_provider_identities_retries_original_identity(
    tmp_path: Path,
) -> None:
    original = ProcessIdentity(pid=4242, start_time="100", run_id="run-a")

    with patch(
        "top_down_planning.orchestrator.provider_teardown.inspect_process_identity",
        return_value=IdentityInspectState.LIVE_MATCH,
    ):
        with patch(
            "top_down_planning.orchestrator.provider_teardown.terminate_verified_process_identity",
            return_value=TerminateIdentityResult.TERMINATED,
        ) as terminate:
            result = _retry_terminate_provider_identities([original])

    assert result.terminated == (4242,)
    terminate.assert_called_once_with(original)


def test_teardown_retries_provider_failure_record_identity_not_fresh_read(
    tmp_path: Path,
) -> None:
    from core_tools.provider import StubProvider

    provider = StubProvider()
    provider.script_turn([{"type": "done", "subtype": "success", "text": "ok"}])
    provider.start_primary_session("planner", {"goal": "x"})
    original = ProcessIdentity(pid=4242, start_time="100", run_id="run-rr10")

    def terminate_all_sessions() -> list[dict[str, object]]:
        return [
            {
                "pid": 4242,
                "role": "planner",
                "session_id": "stub-session-1",
                "start_time": "100",
                "process_identity": "4242:100",
                "run_id": "run-rr10",
                "reason": "termination_failed",
            }
        ]

    with patch.object(provider, "terminate_all_sessions", side_effect=terminate_all_sessions):
        with patch(
            "top_down_planning.orchestrator.provider_teardown.inspect_process_identity",
            return_value=IdentityInspectState.IDENTITY_MISMATCH,
        ):
            with patch(
                "top_down_planning.orchestrator.provider_teardown.terminate_verified_process_identity",
            ) as terminate:
                with pytest.raises(ProviderTeardownError):
                    teardown_provider_sessions(
                        provider,
                        run_id="run-rr10",
                        phase=PLANNING,
                        append_event=lambda *_args, **_kwargs: None,
                        emit_console=lambda _event: None,
                    )

    terminate.assert_not_called()


def test_register_tracked_turn_proc_keeps_live_popen_when_start_time_unavailable(
    tmp_path: Path,
) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=lambda argv, cwd: iter(()),
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=sys.platform != "win32",
    )

    try:
        provider._set_collect_context(session_id, "planner")
        with patch(
            "core_tools.provider.cursor.read_process_identity",
            return_value=None,
        ):
            with patch(
                "core_tools.provider.cursor.read_process_start_time",
                return_value=None,
            ):
                provider._register_tracked_turn_proc(proc)

        assert proc.pid in provider._tracked_turn_procs
        entry = provider._tracked_turn_procs[proc.pid]
        assert entry.proc is proc
        assert entry.identity is None

        provider.terminate_session(session_id)
        assert proc.poll() is not None
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
