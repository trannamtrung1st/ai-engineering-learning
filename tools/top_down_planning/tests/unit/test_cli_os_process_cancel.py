"""Top-level CLI cancellation across a real OS process boundary."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from top_down_planning.persistence import FileRunStore
from tests.helpers import only_run_id, write_config

_SITCUSTOMIZE_DIR = (
    Path(__file__).resolve().parents[1] / "fixtures" / "cli_os_interrupt"
)


def _descendant_pids(root_pid: int) -> set[int]:
    output = subprocess.check_output(
        ["ps", "-axww", "-o", "pid=,ppid="],
        text=True,
    )
    by_parent: dict[int, list[int]] = {}
    for line in output.splitlines():
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        pid = int(parts[0])
        ppid = int(parts[1])
        by_parent.setdefault(ppid, []).append(pid)
    found: set[int] = set()
    stack = list(by_parent.get(root_pid, ()))
    while stack:
        pid = stack.pop()
        found.add(pid)
        stack.extend(by_parent.get(pid, ()))
    return found


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX SIGINT CLI contract")
def test_tdp_run_sigint_exits_130_and_pauses_run_as_user_cancelled(
    tmp_path: Path,
) -> None:
    config_path = write_config(
        tmp_path / "run.yaml",
        """
run:
  output_goal: Deliver the sample output.
provider:
  name: stub
""",
    )
    runs_dir = tmp_path / "runs"
    ready_path = tmp_path / "stub-turn-ready"
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{_SITCUSTOMIZE_DIR}{os.pathsep}{existing}" if existing else str(_SITCUSTOMIZE_DIR)
    )
    env["TDP_STUB_TURN_READY_PATH"] = str(ready_path)
    env["TDP_STUB_TURN_BLOCK_SECONDS"] = "30"

    tdp = shutil.which("tdp")
    assert tdp, "expected an installed non-editable tdp on PATH"
    child = subprocess.Popen(
        [
            tdp,
            "run",
            "--config",
            str(config_path),
            "--runs-dir",
            str(runs_dir),
            "--no-notify",
            "--no-color",
            "--stream-json",
        ],
        cwd=str(tmp_path),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not ready_path.is_file():
            if child.poll() is not None:
                stdout, stderr = child.communicate()
                raise AssertionError(
                    "tdp run exited before entering the stub provider turn: "
                    f"code={child.returncode} stdout={stdout!r} stderr={stderr!r}"
                )
            if time.monotonic() >= deadline:
                child.send_signal(signal.SIGKILL)
                stdout, stderr = child.communicate()
                raise AssertionError(
                    "timed out waiting for stub provider turn: "
                    f"stdout={stdout!r} stderr={stderr!r}"
                )
            time.sleep(0.05)

        child.send_signal(signal.SIGINT)
        child.wait(timeout=15)
    except Exception:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        raise

    assert child.returncode == 130, (
        f"expected SIGINT exit 130, got {child.returncode}; "
        f"stdout={child.stdout.read() if child.stdout else ''} "
        f"stderr={child.stderr.read() if child.stderr else ''}"
    )

    leftover = {pid for pid in _descendant_pids(child.pid) if pid != child.pid}
    assert not leftover, f"provider/CLI descendants still running: {leftover}"

    store = FileRunStore(runs_dir)
    run_id = only_run_id(store)
    run = store.load_run(run_id)
    assert run["status"] == "paused"
    assert run["stop"]["code"] == "user_cancelled"
    events = store.load_events(run_id)
    assert any(event.get("type") == "run_paused" for event in events)
