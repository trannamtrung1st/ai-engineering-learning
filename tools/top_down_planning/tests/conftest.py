"""Shared pytest fixtures and helpers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import ExitStack
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from top_down_planning.cli.main import main
from top_down_planning.orchestrator.agent_process_cleanup import OrphanScanResult

SEND_DESKTOP_NOTIFICATION_TARGETS = (
    "top_down_planning.notifications.desktop.send_desktop_notification",
    "top_down_planning.notifications.bridge.send_desktop_notification",
    "top_down_planning.notifications.outcome.send_desktop_notification",
)
BRIDGE_SEND_DESKTOP = SEND_DESKTOP_NOTIFICATION_TARGETS[1]
OUTCOME_SEND_DESKTOP = SEND_DESKTOP_NOTIFICATION_TARGETS[2]

# Full-system PID scans are slow (~0.7s on macOS). Patch every import site; tests that
# import scan_orphan_agent_pids directly still exercise real logic with injected fakes.
def _empty_orphan_scan(*_args: object, **_kwargs: object) -> OrphanScanResult:
    return OrphanScanResult(kill_candidates=(), unverifiable_pids=())


ORPHAN_AGENT_SCAN_TARGETS = (
    "top_down_planning.orchestrator.agent_process_cleanup.scan_orphan_agents",
    "top_down_planning.orchestrator.agent_process_cleanup.scan_orphan_agent_pids",
    "top_down_planning.orchestrator.run_lifecycle_reconciliation.scan_orphan_agent_pids",
    "top_down_planning.cli.doctor.scan_orphan_agent_pids",
    "top_down_planning.orchestrator.provider_teardown.scan_orphan_agents",
)


@pytest.fixture(scope="session", autouse=True)
def stub_orphan_agent_scan():
    """Stub orphan-agent PID scans once so tests avoid live process enumeration."""

    with ExitStack() as stack:
        for target in ORPHAN_AGENT_SCAN_TARGETS:
            if target.endswith("scan_orphan_agents"):
                stack.enter_context(patch(target, side_effect=_empty_orphan_scan))
            else:
                stack.enter_context(patch(target, return_value=[]))
        yield


@pytest.fixture(scope="session", autouse=True)
def suppress_desktop_notifications():
    """Stub desktop notification transport once so tests never invoke notify-py."""

    with ExitStack() as stack:
        for target in SEND_DESKTOP_NOTIFICATION_TARGETS:
            stack.enter_context(patch(target, return_value=False))
        yield


def _python_descendant_pids(root_pid: int) -> dict[int, str]:
    output = subprocess.check_output(
        ["ps", "-axww", "-o", "pid=,ppid=,command="],
        text=True,
    )
    by_parent: dict[int, list[int]] = {}
    commands: dict[int, str] = {}
    for line in output.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        pid = int(parts[0])
        ppid = int(parts[1])
        commands[pid] = parts[2]
        by_parent.setdefault(ppid, []).append(pid)
    found: dict[int, str] = {}
    stack = list(by_parent.get(root_pid, ()))
    while stack:
        pid = stack.pop()
        cmd = _process_command(pid) or commands.get(pid, "")
        if "python" in cmd.lower():
            found[pid] = cmd
        stack.extend(by_parent.get(pid, ()))
    return found


def _process_command(pid: int) -> str:
    proc_cmd = Path(f"/proc/{pid}/cmdline")
    if proc_cmd.exists():
        try:
            return proc_cmd.read_bytes().replace(b"\x00", b" ").decode("utf-8", "replace")
        except OSError:
            return ""
    return ""


def _is_pytest_infrastructure(cmd: str) -> bool:
    return "resource_tracker" in cmd.lower()


@pytest.fixture(scope="session", autouse=True)
def assert_no_leftover_python_descendants():
    parent = os.getpid()
    before = set(_python_descendant_pids(parent))
    yield
    leftover = {
        pid: cmd
        for pid, cmd in _python_descendant_pids(parent).items()
        if pid not in before and not _is_pytest_infrastructure(cmd)
    }
    assert leftover == {}, leftover
    from top_down_planning.orchestrator.provider_turns import (
        BoundaryWorker,
        owned_boundary_workers,
        reap_unreaped_boundary_workers,
        unreaped_boundary_workers,
    )

    try:
        reap_unreaped_boundary_workers(timeout=0.5)
    except Exception:
        pass
    live = [
        worker
        for worker in owned_boundary_workers()
        if BoundaryWorker._proc_alive(worker.proc)
    ]
    assert live == [], live
    assert unreaped_boundary_workers() == ()


@pytest.fixture
def bridge_send_mock():
    """Recording mock for bridge-tier notification sends (overrides autouse stub)."""

    with patch(BRIDGE_SEND_DESKTOP, return_value=True) as mock:
        yield mock


@pytest.fixture
def outcome_send_mock():
    """Recording mock for CLI outcome notification sends (overrides autouse stub)."""

    with patch(OUTCOME_SEND_DESKTOP, return_value=True) as mock:
        yield mock


@dataclass(frozen=True)
class CliResult:
    exit_code: int
    stdout: str
    stderr: str

    def json(self) -> dict:
        text = self.stdout.strip()
        if not text:
            raise json.JSONDecodeError("empty stdout", text, 0)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        decoder = json.JSONDecoder()
        last: dict | None = None
        idx = 0
        while idx < len(text):
            while idx < len(text) and text[idx] not in "{[":
                idx += 1
            if idx >= len(text):
                break
            try:
                value, end = decoder.raw_decode(text, idx)
            except json.JSONDecodeError:
                idx += 1
                continue
            if isinstance(value, dict):
                last = value
            idx = end

        if last is not None:
            return last
        raise json.JSONDecodeError("no JSON object in stdout", text, 0)


def run_cli(argv: list[str]) -> CliResult:
    """Invoke the CLI in-process and capture stdout/stderr."""

    out = StringIO()
    err = StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        try:
            main(argv)
            exit_code = 0
        except SystemExit as exc:
            code = exc.code
            exit_code = 0 if code is None else int(code)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return CliResult(exit_code=exit_code, stdout=out.getvalue(), stderr=err.getvalue())
