"""Unblock SIGINT and constrain live-PID listing to agent-looking commands.

Does not stub orphan scanners to empty. The real classify/kill/scan path runs,
but only over processes whose command looks like a provider agent. That keeps
macOS unverifiable system PIDs from collapsing preflight while still proving
process-backed cleanup for the fake Cursor executable.
"""

from __future__ import annotations

import os
import signal

if os.environ.get("TDP_SLICE10_PROCESS_PROVIDER"):
    signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGINT, signal.SIGTERM})

    from top_down_planning.orchestrator import agent_process_cleanup

    _orig_list_live_pids = agent_process_cleanup._default_list_live_pids

    def _agent_looking_live_pids() -> list[int]:
        return [
            pid
            for pid in _orig_list_live_pids()
            if agent_process_cleanup._looks_like_agent_command(
                agent_process_cleanup._read_pid_cmdline(pid)
            )
        ]

    agent_process_cleanup._default_list_live_pids = _agent_looking_live_pids
