"""Detect and terminate orphaned provider agent subprocesses for a run."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core_tools.provider.process_cleanup import is_pid_alive, terminate_pid_tree

from top_down_planning.cli.common import RUN_ID_ENV_VAR
from top_down_planning.domain.run_lifecycle import StopRecord
from top_down_planning.domain.run_ownership import is_run_orchestrator_alive
from top_down_planning.orchestrator.run_signals import defer_run_interrupt_signals
from top_down_planning.orchestrator.run_transitions import pause_run
from top_down_planning.persistence.interface import RunStore

ReadPidEnviron = Callable[[int], dict[str, str]]
ListLivePids = Callable[[], list[int]]

_AGENT_CMD_MARKERS = ("--output-format", "stream-json")
_RUN_ID_PATTERN = re.compile(rf"(?:^|\s){re.escape(RUN_ID_ENV_VAR)}=([^\s]+)")


def _default_list_live_pids() -> list[int]:
    if sys.platform == "win32":
        return []
    try:
        result = subprocess.run(
            ["ps", "-A", "-o", "pid="],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []
    pids: list[int] = []
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.isdigit():
            pids.append(int(stripped))
    return pids


def _read_pid_environ_linux(pid: int) -> dict[str, str]:
    path = f"/proc/{pid}/environ"
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return {}
    env: dict[str, str] = {}
    for entry in raw.split(b"\0"):
        if b"=" not in entry:
            continue
        key, value = entry.split(b"=", 1)
        try:
            env[key.decode()] = value.decode(errors="replace")
        except UnicodeDecodeError:
            continue
    return env


def _read_pid_environ_darwin(pid: int) -> dict[str, str]:
    try:
        result = subprocess.run(
            ["ps", "eww", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return {}
    if result.returncode != 0:
        return {}
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        return {}
    line = lines[-1]
    env: dict[str, str] = {}
    for match in _RUN_ID_PATTERN.finditer(line):
        env[RUN_ID_ENV_VAR] = match.group(1)
    for token in line.split():
        if "=" not in token:
            continue
        key, _, value = token.partition("=")
        if key.startswith("TDP_"):
            env[key] = value
    return env


def default_read_pid_environ(pid: int) -> dict[str, str]:
    if sys.platform == "win32":
        return {}
    if sys.platform == "darwin":
        return _read_pid_environ_darwin(pid)
    if os.path.isdir("/proc"):
        return _read_pid_environ_linux(pid)
    return _read_pid_environ_darwin(pid)


def _normalize_pid_list(raw: object) -> list[int]:
    if not isinstance(raw, list):
        return []
    pids: list[int] = []
    for pid in raw:
        try:
            pids.append(int(pid))
        except (TypeError, ValueError):
            continue
    return pids


def _read_pid_command(pid: int) -> str:
    if sys.platform == "win32":
        return ""
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _read_pid_cmdline(pid: int) -> str:
    if sys.platform == "win32":
        return _read_pid_command(pid)
    if os.path.isdir("/proc"):
        path = f"/proc/{pid}/cmdline"
        try:
            with open(path, "rb") as handle:
                raw = handle.read()
        except OSError:
            return _read_pid_command(pid)
        parts = [part.decode(errors="replace") for part in raw.split(b"\0") if part]
        if parts:
            return " ".join(parts)
    return _read_pid_command(pid)


def _looks_like_agent_command(command: str) -> bool:
    lowered = command.lower()
    if "agent" not in lowered and "cursor-agent" not in lowered:
        return False
    return all(marker in command for marker in _AGENT_CMD_MARKERS)


def scan_orphan_agent_pids(
    run_id: str,
    *,
    exclude_pids: frozenset[int] | None = None,
    terminated_pids: list[int] | None = None,
    list_live_pids: ListLivePids | None = None,
    read_pid_environ: ReadPidEnviron | None = None,
) -> list[int]:
    """Return live agent PIDs associated with *run_id* outside *exclude_pids*."""

    excluded = exclude_pids or frozenset()
    list_pids = list_live_pids or _default_list_live_pids
    read_environ = read_pid_environ or default_read_pid_environ
    orphans: list[int] = []
    seen: set[int] = set(excluded)

    for pid in terminated_pids or []:
        if pid in seen:
            continue
        seen.add(pid)
        if is_pid_alive(pid):
            orphans.append(pid)

    for pid in list_pids():
        if pid in seen:
            continue
        seen.add(pid)
        if not is_pid_alive(pid):
            continue
        environ = read_environ(pid)
        env_run_id = str(environ.get(RUN_ID_ENV_VAR) or "").strip()
        if env_run_id != run_id:
            continue
        command = _read_pid_cmdline(pid)
        if not _looks_like_agent_command(command):
            continue
        orphans.append(pid)

    return sorted(set(orphans))


def kill_orphan_agents(
    store: RunStore,
    run_id: str,
    *,
    exclude_pids: frozenset[int] | None = None,
    list_live_pids: ListLivePids | None = None,
    read_pid_environ: ReadPidEnviron | None = None,
) -> list[int]:
    """Terminate orphan agents for *run_id* and append audit events."""

    run = store.load_run(run_id)
    terminated_pids = terminated_pids_from_stop(run)

    orphan_pids = scan_orphan_agent_pids(
        run_id,
        exclude_pids=exclude_pids,
        terminated_pids=terminated_pids,
        list_live_pids=list_live_pids,
        read_pid_environ=read_pid_environ,
    )
    cleaned: list[int] = []
    for pid in orphan_pids:
        if not is_pid_alive(pid):
            continue
        if terminate_pid_tree(pid):
            cleaned.append(pid)
            store.append_event(
            run_id,
            {
                "type": "agent_orphan_cleaned",
                "pid": pid,
                "run_id": run_id,
                "reason": "orphan",
            },
        )
    return cleaned


def finalize_user_cancel(
    store: RunStore,
    run_id: str,
    *,
    phase: str,
    provider_terminated_pids: list[int] | None = None,
    exclude_pids: frozenset[int] | None = None,
) -> list[int]:
    """Persist ``user_cancelled`` then best-effort orphan cleanup."""

    with defer_run_interrupt_signals():
        orphan_pids: list[int] = []
        try:
            orphan_pids = _kill_orphan_agents_before_pause(
                store,
                run_id,
                provider_terminated_pids=provider_terminated_pids,
                exclude_pids=exclude_pids,
            )
        except BaseException:
            orphan_pids = []
        all_terminated_pids = sorted(
            {int(pid) for pid in (provider_terminated_pids or [])}
            | {int(pid) for pid in orphan_pids}
        )
        pause_run(
            store,
            run_id,
            stop=StopRecord(
                code="user_cancelled",
                category="operational",
                phase=phase,
                message="cancelled by user",
                details={"terminated_pids": all_terminated_pids},
            ),
        )
        if all_terminated_pids:
            try:
                store.append_event(
                    run_id,
                    {
                        "type": "user_cancel_cleanup",
                        "run_id": run_id,
                        "terminated_pids": all_terminated_pids,
                    },
                )
            except BaseException:
                pass
    return all_terminated_pids


def _kill_orphan_agents_before_pause(
    store: RunStore,
    run_id: str,
    *,
    provider_terminated_pids: list[int] | None = None,
    exclude_pids: frozenset[int] | None = None,
    list_live_pids: ListLivePids | None = None,
    read_pid_environ: ReadPidEnviron | None = None,
) -> list[int]:
    """Terminate orphan agents before the cancel pause record is persisted."""

    orphan_pids = scan_orphan_agent_pids(
        run_id,
        exclude_pids=exclude_pids,
        terminated_pids=provider_terminated_pids or [],
        list_live_pids=list_live_pids,
        read_pid_environ=read_pid_environ,
    )
    cleaned: list[int] = []
    for pid in orphan_pids:
        if not is_pid_alive(pid):
            continue
        if terminate_pid_tree(pid):
            cleaned.append(pid)
            store.append_event(
                run_id,
                {
                    "type": "agent_orphan_cleaned",
                    "pid": pid,
                    "run_id": run_id,
                    "reason": "orphan",
                },
            )
    return cleaned


def terminated_pids_from_stop(run: dict[str, Any]) -> list[int]:
    stop = run.get("stop")
    if not isinstance(stop, dict):
        return []
    details = stop.get("details")
    if not isinstance(details, dict):
        return []
    raw = details.get("terminated_pids")
    return _normalize_pid_list(raw)


def workspace_has_orphan_agents(
    store: RunStore,
    *,
    list_live_pids: ListLivePids | None = None,
    read_pid_environ: ReadPidEnviron | None = None,
) -> list[tuple[str, int]]:
    """Return (run_id, pid) pairs for orphan agents on paused, terminal, or stale runs."""

    orphans: list[tuple[str, int]] = []
    root = getattr(store, "root", None)
    if root is None:
        return orphans
    root_path = root if isinstance(root, os.PathLike) else None
    if root_path is None:
        return orphans

    for run_dir in sorted(Path(root_path).iterdir()):
        if not run_dir.is_dir() or not (run_dir / "run.json").is_file():
            continue
        run_id = run_dir.name
        try:
            run = store.load_run(run_id)
        except Exception:
            continue
        status = str(run.get("status") or "")
        if status in {"paused", "completed", "failed"}:
            scan = True
        elif status == "running":
            scan = not is_run_orchestrator_alive(run_dir)
        else:
            scan = False
        if not scan:
            continue
        for pid in scan_orphan_agent_pids(
            run_id,
            exclude_pids=frozenset({os.getpid()}),
            terminated_pids=terminated_pids_from_stop(run),
            list_live_pids=list_live_pids,
            read_pid_environ=read_pid_environ,
        ):
            orphans.append((run_id, pid))
    return orphans


__all__ = [
    "default_read_pid_environ",
    "finalize_user_cancel",
    "kill_orphan_agents",
    "scan_orphan_agent_pids",
    "terminated_pids_from_stop",
    "workspace_has_orphan_agents",
]
