"""Detect and terminate orphaned provider agent subprocesses for a run."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from core_tools.provider.process_cleanup import is_pid_alive, terminate_pid_tree
from core_tools.provider.process_identity import (
    ProcessIdentity,
    TerminateIdentityResult,
    read_process_start_time,
    terminate_verified_process_identity,
)

from top_down_planning.cli.common import RUN_ID_ENV_VAR
from top_down_planning.domain.run_lifecycle import StopRecord
from top_down_planning.domain.run_ownership import is_run_orchestrator_alive
from top_down_planning.orchestrator.run_signals import ignore_repeated_run_interrupt_signals
from top_down_planning.orchestrator.run_transitions import pause_run
from top_down_planning.persistence.interface import RunStore

ReadPidEnviron = Callable[[int], dict[str, str]]
ListLivePids = Callable[[], list[int]]

_AGENT_CMD_MARKERS = ("--output-format", "stream-json")
_RUN_ID_PATTERN = re.compile(rf"(?:^|\s){re.escape(RUN_ID_ENV_VAR)}=([^\s]+)")


class PidRunAgentMatch(Enum):
    """Three-way classification for run-associated agent PID ownership."""

    CONFIRMED_SAME = "confirmed_same"
    CONFIRMED_DIFFERENT = "confirmed_different"
    UNVERIFIABLE = "unverifiable"


@dataclass(frozen=True)
class OrphanScanResult:
    """Outcome of scanning for run-associated orphan agent processes."""

    kill_candidates: tuple[ProcessIdentity, ...]
    unverifiable_pids: tuple[int, ...]


@dataclass(frozen=True)
class OrphanCleanupResult:
    """Outcome of terminating run-associated orphan agent processes."""

    cleaned_pids: tuple[int, ...]
    failed_pids: tuple[int, ...]


@dataclass(frozen=True)
class CancelCleanupResult:
    """Outcome of cancellation orphan cleanup before persisting user_cancelled."""

    terminated_pids: tuple[int, ...]
    surviving_pids: tuple[int, ...]
    cleanup_complete: bool


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


def classify_pid_run_agent(
    run_id: str,
    pid: int,
    *,
    read_environ: ReadPidEnviron | None = None,
) -> PidRunAgentMatch:
    """Classify whether *pid* is the same run agent, a reused PID, or unverifiable."""

    read_env = read_environ or default_read_pid_environ
    if not is_pid_alive(pid):
        return PidRunAgentMatch.CONFIRMED_DIFFERENT
    environ = read_env(pid)
    env_run_id = str(environ.get(RUN_ID_ENV_VAR) or "").strip()
    command = _read_pid_cmdline(pid)
    if not env_run_id or not command:
        return PidRunAgentMatch.UNVERIFIABLE
    if env_run_id != run_id:
        return PidRunAgentMatch.CONFIRMED_DIFFERENT
    if not _looks_like_agent_command(command):
        return PidRunAgentMatch.CONFIRMED_DIFFERENT
    if read_process_start_time(pid) is None:
        return PidRunAgentMatch.UNVERIFIABLE
    return PidRunAgentMatch.CONFIRMED_SAME


def pid_matches_run_agent(
    run_id: str,
    pid: int,
    *,
    read_environ: ReadPidEnviron | None = None,
) -> bool:
    """Return whether *pid* is a confirmed live run-associated agent process."""

    return (
        classify_pid_run_agent(run_id, pid, read_environ=read_environ)
        == PidRunAgentMatch.CONFIRMED_SAME
    )


def _build_kill_candidate_identity(
    run_id: str,
    pid: int,
    *,
    read_environ: ReadPidEnviron,
) -> ProcessIdentity | None:
    if (
        classify_pid_run_agent(run_id, pid, read_environ=read_environ)
        != PidRunAgentMatch.CONFIRMED_SAME
    ):
        return None
    command = _read_pid_cmdline(pid)
    start_time = read_process_start_time(pid)
    if start_time is None:
        return None
    return ProcessIdentity(
        pid=pid,
        start_time=start_time,
        run_id=run_id,
        command=command,
    )


def scan_orphan_agents(
    run_id: str,
    *,
    exclude_pids: frozenset[int] | None = None,
    terminated_pids: list[int] | None = None,
    list_live_pids: ListLivePids | None = None,
    read_pid_environ: ReadPidEnviron | None = None,
) -> OrphanScanResult:
    """Return identity-safe kill candidates and unverifiable live PIDs."""

    excluded = exclude_pids or frozenset()
    list_pids = list_live_pids or _default_list_live_pids
    read_environ = read_pid_environ or default_read_pid_environ
    kill_candidates: list[ProcessIdentity] = []
    unverifiable: list[int] = []
    seen: set[int] = set(excluded)

    def consider(pid: int) -> None:
        if pid in seen:
            return
        seen.add(pid)
        if not is_pid_alive(pid):
            return
        match = classify_pid_run_agent(run_id, pid, read_environ=read_environ)
        if match == PidRunAgentMatch.UNVERIFIABLE:
            unverifiable.append(pid)
            return
        if match == PidRunAgentMatch.CONFIRMED_DIFFERENT:
            return
        identity = _build_kill_candidate_identity(
            run_id,
            pid,
            read_environ=read_environ,
        )
        if identity is None:
            unverifiable.append(pid)
            return
        kill_candidates.append(identity)

    for pid in terminated_pids or []:
        consider(pid)
    for pid in list_pids():
        consider(pid)

    return OrphanScanResult(
        kill_candidates=tuple(kill_candidates),
        unverifiable_pids=tuple(sorted(set(unverifiable))),
    )


def scan_orphan_agent_pids(
    run_id: str,
    *,
    exclude_pids: frozenset[int] | None = None,
    terminated_pids: list[int] | None = None,
    list_live_pids: ListLivePids | None = None,
    read_pid_environ: ReadPidEnviron | None = None,
) -> list[int]:
    """Return live confirmed run-agent PIDs associated with *run_id*."""

    excluded = exclude_pids or frozenset()
    list_pids = list_live_pids or _default_list_live_pids
    read_environ = read_pid_environ or default_read_pid_environ
    orphans: list[int] = []
    seen: set[int] = set(excluded)

    def consider(pid: int) -> None:
        if pid in seen:
            return
        seen.add(pid)
        if (
            classify_pid_run_agent(run_id, pid, read_environ=read_environ)
            == PidRunAgentMatch.CONFIRMED_SAME
        ):
            orphans.append(pid)

    for pid in terminated_pids or []:
        consider(pid)
    for pid in list_pids():
        consider(pid)

    return sorted(set(orphans))


def kill_orphan_agents(
    store: RunStore,
    run_id: str,
    *,
    exclude_pids: frozenset[int] | None = None,
    additional_terminated_pids: list[int] | None = None,
    list_live_pids: ListLivePids | None = None,
    read_pid_environ: ReadPidEnviron | None = None,
) -> OrphanCleanupResult:
    """Terminate orphan agents for *run_id* and append audit events."""

    run = store.load_run(run_id)
    terminated_pids = [
        *terminated_pids_from_stop(run),
        *[int(pid) for pid in (additional_terminated_pids or [])],
    ]

    orphan_pids = scan_orphan_agent_pids(
        run_id,
        exclude_pids=exclude_pids,
        terminated_pids=terminated_pids,
        list_live_pids=list_live_pids,
        read_pid_environ=read_pid_environ,
    )
    cleaned: list[int] = []
    failed: list[int] = []
    stale_reconciled: list[int] = []
    for pid in orphan_pids:
        if not is_pid_alive(pid):
            continue
        identity = _build_kill_candidate_identity(
            run_id,
            pid,
            read_environ=read_pid_environ or default_read_pid_environ,
        )
        if identity is None:
            failed.append(pid)
            continue
        result = terminate_verified_process_identity(identity)
        if result == TerminateIdentityResult.TERMINATED:
            cleaned.append(pid)
            try:
                store.append_event(
                    run_id,
                    {
                        "type": "agent_orphan_cleaned",
                        "pid": pid,
                        "run_id": run_id,
                        "reason": "orphan",
                    },
                )
            except Exception:
                pass
        elif result == TerminateIdentityResult.IDENTITY_MISMATCH:
            stale_reconciled.append(pid)
            continue
        elif result == TerminateIdentityResult.ALREADY_GONE:
            continue
        else:
            failed.append(pid)
            try:
                store.append_event(
                    run_id,
                    {
                        "type": "agent_orphan_cleanup_failed",
                        "pid": pid,
                        "run_id": run_id,
                        "reason": "termination_failed",
                    },
                )
            except Exception:
                pass

    survivor_scan = scan_orphan_agents(
        run_id,
        exclude_pids=exclude_pids,
        terminated_pids=[*terminated_pids, *cleaned],
        list_live_pids=list_live_pids,
        read_pid_environ=read_pid_environ,
    )
    for pid in survivor_scan.unverifiable_pids:
        if pid not in failed:
            failed.append(pid)
    for identity in survivor_scan.kill_candidates:
        pid = identity.pid
        if pid in cleaned or pid in failed or pid in stale_reconciled:
            continue
        if is_pid_alive(pid):
            failed.append(pid)
    return OrphanCleanupResult(
        cleaned_pids=tuple(sorted(set(cleaned))),
        failed_pids=tuple(sorted(set(failed))),
    )


def finalize_user_cancel(
    store: RunStore,
    run_id: str,
    *,
    phase: str,
    provider_terminated_pids: list[int] | None = None,
    known_surviving_pids: tuple[int, ...] = (),
    exclude_pids: frozenset[int] | None = None,
) -> CancelCleanupResult:
    """Persist ``user_cancelled`` after verified orphan cleanup."""

    with ignore_repeated_run_interrupt_signals():
        cleanup = kill_orphan_agents(
            store,
            run_id,
            exclude_pids=exclude_pids,
            additional_terminated_pids=provider_terminated_pids,
        )
        verified_terminated = sorted(
            {int(pid) for pid in (provider_terminated_pids or [])}
            | {int(pid) for pid in cleanup.cleaned_pids}
        )
        surviving_pids = sorted(
            {
                int(pid)
                for pid in cleanup.failed_pids
                if is_pid_alive(pid)
            }
            | {
                int(pid)
                for pid in known_surviving_pids
                if is_pid_alive(pid)
            }
        )
        remaining = scan_orphan_agent_pids(
            run_id,
            exclude_pids=exclude_pids,
            terminated_pids=verified_terminated,
        )
        for pid in remaining:
            if is_pid_alive(pid) and pid not in surviving_pids:
                surviving_pids.append(pid)
        surviving_pids = sorted(set(surviving_pids))
        cleanup_complete = not surviving_pids
        message = (
            "cancelled by user"
            if cleanup_complete
            else "cancelled by user (agent cleanup incomplete)"
        )
        pause_run(
            store,
            run_id,
            stop=StopRecord(
                code="user_cancelled",
                category="operational",
                phase=phase,
                message=message,
                details={
                    "terminated_pids": verified_terminated,
                    "cleanup_failed_pids": surviving_pids,
                    "cleanup_complete": cleanup_complete,
                },
            ),
        )
        if verified_terminated or surviving_pids:
            try:
                store.append_event(
                    run_id,
                    {
                        "type": "user_cancel_cleanup",
                        "run_id": run_id,
                        "terminated_pids": verified_terminated,
                        "cleanup_failed_pids": surviving_pids,
                        "cleanup_complete": cleanup_complete,
                    },
                )
            except Exception:
                pass
    return CancelCleanupResult(
        terminated_pids=tuple(verified_terminated),
        surviving_pids=tuple(surviving_pids),
        cleanup_complete=cleanup_complete,
    )


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
    "CancelCleanupResult",
    "OrphanCleanupResult",
    "OrphanScanResult",
    "PidRunAgentMatch",
    "classify_pid_run_agent",
    "default_read_pid_environ",
    "finalize_user_cancel",
    "kill_orphan_agents",
    "pid_matches_run_agent",
    "scan_orphan_agent_pids",
    "scan_orphan_agents",
    "terminated_pids_from_stop",
    "workspace_has_orphan_agents",
]
