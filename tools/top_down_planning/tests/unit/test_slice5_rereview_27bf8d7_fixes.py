"""Slice 5 rereview 27bf8d7: TDP Darwin orphan cleanup must terminate live agents."""

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
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator.agent_process_cleanup import (
    PidRunAgentMatch,
    classify_pid_run_agent,
    kill_orphan_agents,
)
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs, minimal_resolved_config


def _plan() -> Plan:
    return Plan(
        id="plan-orphan-darwin",
        revision=0,
        output_goal="Goal.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="Root",
                kind="aggregate",
            )
        },
    )


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX orphan cleanup")
def test_kill_orphan_agents_terminates_live_run_agent(tmp_path: Path) -> None:
    run_id = "run-20260101T270807-270807"
    store = FileRunStore(tmp_path)
    store.create_run(
        run_id,
        plan=_plan(),
        **create_run_kwargs(tmp_path, resolved_config=minimal_resolved_config()),
    )

    env = {**os.environ, "TDP_RUN_ID": run_id}
    orphan = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import time; time.sleep(60)  # agent --output-format stream-json --trust",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not is_pid_alive(orphan.pid):
            time.sleep(0.05)
        assert is_pid_alive(orphan.pid)
        assert (
            classify_pid_run_agent(run_id, orphan.pid)
            is PidRunAgentMatch.CONFIRMED_SAME
        )

        def live_scan(run_id: str, **kwargs: object) -> list[int]:
            list_live_pids = kwargs.get("list_live_pids")
            pids = list(list_live_pids()) if callable(list_live_pids) else [orphan.pid]
            return [
                pid
                for pid in pids
                if classify_pid_run_agent(run_id, pid) is PidRunAgentMatch.CONFIRMED_SAME
            ]

        with patch(
            "top_down_planning.orchestrator.agent_process_cleanup.scan_orphan_agent_pids",
            live_scan,
        ):
            cleanup = kill_orphan_agents(
                store,
                run_id,
                list_live_pids=lambda: [orphan.pid],
            )
        assert orphan.pid in cleanup.cleaned_pids
        assert cleanup.failed_pids == ()
        assert not is_pid_alive(orphan.pid)
    finally:
        if orphan.poll() is None:
            orphan.kill()
            orphan.wait(timeout=2)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX orphan cleanup")
@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork unavailable")
def test_kill_orphan_agents_cleans_janitor_session_not_raw_child_pid(
    tmp_path: Path,
) -> None:
    run_id = "run-20260101T270911-270911"
    store = FileRunStore(tmp_path)
    store.create_run(
        run_id,
        plan=_plan(),
        **create_run_kwargs(tmp_path, resolved_config=minimal_resolved_config()),
    )
    child_file = tmp_path / "agent.pid"
    env = {**os.environ, "TDP_RUN_ID": run_id}
    script = (
        "import os, sys, time\n"
        f"path = {str(child_file)!r}\n"
        "child = os.fork()\n"
        "if child == 0:\n"
        "    os.execl(\n"
        f"        {sys.executable!r}, {sys.executable!r}, '-c',\n"
        "        'import time; time.sleep(60)  # agent --output-format stream-json --trust',\n"
        "    )\n"
        "with open(path, 'w', encoding='utf-8') as handle:\n"
        "    handle.write(str(child))\n"
        "time.sleep(60)\n"
    )
    janitor = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 2.0
        child_pid = None
        while time.monotonic() < deadline:
            if child_file.exists():
                child_pid = int(child_file.read_text(encoding="utf-8").strip())
                break
            time.sleep(0.05)
        assert child_pid is not None
        assert is_pid_alive(child_pid)
        assert (
            classify_pid_run_agent(run_id, child_pid)
            is PidRunAgentMatch.CONFIRMED_SAME
        )

        def live_scan(run_id: str, **kwargs: object) -> list[int]:
            return [child_pid]

        killed_child: list[int] = []
        real_kill = os.kill

        def tracking_kill(pid: int, sig: int) -> None:
            if pid == child_pid and sig in (signal.SIGTERM, signal.SIGKILL):
                killed_child.append(pid)
            real_kill(pid, sig)

        with patch(
            "top_down_planning.orchestrator.agent_process_cleanup.scan_orphan_agent_pids",
            live_scan,
        ), patch(
            "core_tools.provider.process_identity.os.kill",
            side_effect=tracking_kill,
        ):
            cleanup = kill_orphan_agents(
                store,
                run_id,
                list_live_pids=lambda: [child_pid],
            )
        assert child_pid in cleanup.cleaned_pids
        assert cleanup.failed_pids == ()
        assert not is_pid_alive(child_pid)
        assert killed_child == []
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and janitor.poll() is None:
            time.sleep(0.05)
        assert janitor.poll() is not None
    finally:
        if janitor.poll() is None:
            janitor.kill()
            janitor.wait(timeout=2)

