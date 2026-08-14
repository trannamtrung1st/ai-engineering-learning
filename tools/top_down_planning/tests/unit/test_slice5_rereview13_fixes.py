"""Slice 5 thirteenth re-review regressions (S5-RR13-001/004 TDP surface)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider.process_cleanup import is_pid_alive
from core_tools.provider.process_identity import (
    IdentityInspectState,
    ProcessIdentity,
    TerminateIdentityResult,
    drain_owned_process_group,
)
from top_down_planning.orchestrator.errors import ProviderTeardownError
from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.orchestrator.provider_teardown import teardown_provider_sessions


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork unavailable")
def test_drain_discovers_child_forked_after_first_group_snapshot(tmp_path: Path) -> None:
    go_file = tmp_path / "go"
    child_file = tmp_path / "child.pid"
    script = (
        "import os, time\n"
        f"go_file = {str(go_file)!r}\n"
        f"child_file = {str(child_file)!r}\n"
        "while not os.path.exists(go_file):\n"
        "    time.sleep(0.01)\n"
        "child = os.fork()\n"
        "if child == 0:\n"
        "    time.sleep(60)\n"
        "    os._exit(0)\n"
        "with open(child_file, 'w', encoding='utf-8') as handle:\n"
        "    handle.write(str(child))\n"
        "time.sleep(60)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    from core_tools.provider.process_identity import read_process_identity

    leader = read_process_identity(proc.pid)
    assert leader is not None
    pgid = os.getpgid(proc.pid)
    first = {"seen": False}

    import core_tools.provider.process_identity as identity_mod

    original = identity_mod._current_group_identities

    def wrapped(pgid_value: int, *, run_id: str | None = None, timeout: float | None = None):
        members = original(pgid_value, run_id=run_id, timeout=timeout)
        if not first["seen"]:
            first["seen"] = True
            go_file.write_text("go", encoding="utf-8")
            for _ in range(40):
                if child_file.exists():
                    break
                time.sleep(0.05)
        return members

    late_child_pid: int | None = None
    try:
        with patch(
            "core_tools.provider.process_identity._current_group_identities",
            side_effect=wrapped,
        ):
            result = drain_owned_process_group(
                pgid=pgid,
                leader_identity=leader,
                known_identities=[leader],
            )
        late_child_pid = (
            int(child_file.read_text(encoding="utf-8").strip())
            if child_file.exists()
            else None
        )
        child_alive = late_child_pid is not None and is_pid_alive(late_child_pid)
        assert not (result is True and child_alive)
        if late_child_pid is not None and not child_alive:
            assert result is True or result is False
        else:
            assert result is False
    finally:
        if late_child_pid is not None and is_pid_alive(late_child_pid):
            os.kill(late_child_pid, signal.SIGKILL)
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_teardown_fails_when_dead_leader_leaves_live_descendant(tmp_path: Path) -> None:
    from core_tools.provider import StubProvider

    provider = StubProvider()
    provider.script_turn([{"type": "done", "subtype": "success", "text": "ok"}])
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    child = ProcessIdentity(pid=5151, start_time="200", run_id="run-rr13")

    def terminate_all_sessions() -> list[dict[str, object]]:
        return [
            {
                "pid": 4242,
                "role": "planner",
                "session_id": session_id,
                "start_time": "100",
                "process_identity": "4242:100",
                "run_id": "run-rr13",
                "pgid": 4242,
                "member_pids": [4242, 5151],
                "member_identities": ["4242:100", "5151:200"],
                "tree_status": "unresolved",
                "reason": "termination_failed",
            }
        ]

    with patch.object(provider, "terminate_all_sessions", side_effect=terminate_all_sessions):
        with patch.object(provider, "list_active_sessions", return_value=[]):
            with patch(
                "top_down_planning.orchestrator.provider_teardown.is_pid_alive",
                side_effect=lambda pid, timeout=None: pid == 5151,
            ):
                with patch(
                    "top_down_planning.orchestrator.provider_teardown.inspect_process_identity",
                    side_effect=lambda identity, timeout=None: (
                        IdentityInspectState.LIVE_MATCH
                        if identity.pid == 5151
                        else IdentityInspectState.GONE
                    ),
                ):
                    with patch(
                        "top_down_planning.orchestrator.provider_teardown.process_identity_is_live",
                        side_effect=lambda identity, timeout=None: identity.pid == 5151,
                    ):
                        with patch(
                            "top_down_planning.orchestrator.provider_teardown.terminate_verified_process_identity",
                            return_value=TerminateIdentityResult.FAILED,
                        ) as terminate:
                            with pytest.raises(ProviderTeardownError) as exc_info:
                                teardown_provider_sessions(
                                    provider,
                                    run_id="run-rr13",
                                    phase=PLANNING,
                                    append_event=lambda *_args, **_kwargs: None,
                                    emit_console=lambda _event: None,
                                )

    assert 5151 in exc_info.value.surviving_pids
    assert any(call.args and call.args[0].pid == 5151 for call in terminate.call_args_list)
