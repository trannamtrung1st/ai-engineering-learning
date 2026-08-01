"""Run health diagnostics for orphan agent processes."""

from __future__ import annotations

from argparse import Namespace
from typing import Any

import os

from top_down_planning.cli.common import emit_error_message, emit_payload, open_run_store
from top_down_planning.orchestrator.agent_process_cleanup import (
    scan_orphan_agent_pids,
    terminated_pids_from_stop,
)


def handle_doctor_command(args: Namespace) -> None:
    store, _resolved = open_run_store(args)
    if not args.run:
        emit_error_message(
            "tdp doctor requires --run",
            exit_code=2,
            stream_json=args.stream_json,
            code="missing_run",
        )

    run_id = str(args.run)
    run = store.load_run(run_id)
    orphan_pids = scan_orphan_agent_pids(
        run_id,
        exclude_pids=frozenset({os.getpid()}),
        terminated_pids=terminated_pids_from_stop(run),
    )
    payload: dict[str, Any] = {
        "ok": True,
        "run_id": run_id,
        "status": run.get("status"),
        "orphan_agent_count": len(orphan_pids),
        "orphan_agent_pids": orphan_pids,
    }
    if args.stream_json:
        emit_payload(payload)
        return

    if orphan_pids:
        message = (
            f"run {run_id}: {len(orphan_pids)} orphan agent process(es) "
            f"still alive: {', '.join(str(pid) for pid in orphan_pids)}"
        )
    else:
        message = f"run {run_id}: no orphan agent processes detected"
    print(message)


__all__ = ["handle_doctor_command"]
