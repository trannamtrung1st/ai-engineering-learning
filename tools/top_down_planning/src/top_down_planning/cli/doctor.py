"""Run health diagnostics for orphan agent processes."""

from __future__ import annotations

from argparse import Namespace
from typing import Any

import os

from top_down_planning.cli.common import emit_payload, open_run_store
from top_down_planning.orchestrator.agent_process_cleanup import (
    kill_orphan_agents,
    scan_orphan_agent_pids,
    terminated_pids_from_stop,
)
from top_down_planning.orchestrator.run_lifecycle_reconciliation import (
    cleanup_staging_dirs,
    reconcile_stale_running_run,
    workspace_diagnostics,
)


def handle_doctor_command(args: Namespace) -> None:
    store, _resolved = open_run_store(args)
    fix = bool(getattr(args, "fix", False))
    removed_staging_dirs: list[str] = []
    if fix:
        removed_staging_dirs = cleanup_staging_dirs(store)

    if not args.run:
        diagnostics = workspace_diagnostics(store)
        reconciled: list[str] = []
        if fix:
            for run_id in sorted(
                set(diagnostics["interrupted_running_run_ids"])
                | set(diagnostics["idle_running_run_ids"])
            ):
                if reconcile_stale_running_run(
                    store,
                    run_id,
                    require_orphan_agents=False,
                ):
                    reconciled.append(run_id)
            diagnostics = workspace_diagnostics(store)

        payload: dict[str, Any] = {
            "ok": True,
            "workspace": diagnostics,
            "reconciled_run_ids": reconciled,
            "removed_staging_dirs": removed_staging_dirs,
        }
        if args.stream_json:
            emit_payload(payload)
            return

        lines = ["Workspace diagnostics:"]
        if diagnostics["interrupted_running_run_ids"]:
            lines.append(
                "  interrupted running runs (orphan agents): "
                + ", ".join(diagnostics["interrupted_running_run_ids"])
            )
        else:
            lines.append("  interrupted running runs: none")
        if diagnostics["idle_running_run_ids"]:
            lines.append(
                "  idle running runs (awaiting resume): "
                + ", ".join(diagnostics["idle_running_run_ids"])
            )
        else:
            lines.append("  idle running runs: none")
        if diagnostics["incomplete_run_dirs"]:
            lines.append(
                "  incomplete run dirs (missing run.json): "
                + ", ".join(diagnostics["incomplete_run_dirs"])
            )
        else:
            lines.append("  incomplete run dirs: none")
        if diagnostics["staging_run_dirs"]:
            lines.append(
                "  staging dirs (.creating-*): "
                + ", ".join(diagnostics["staging_run_dirs"])
            )
        else:
            lines.append("  staging dirs: none")
        if fix and reconciled:
            lines.append("  reconciled runs: " + ", ".join(reconciled))
        if fix and removed_staging_dirs:
            lines.append(
                "  removed staging dirs: " + ", ".join(removed_staging_dirs)
            )
        print("\n".join(lines))
        return

    run_id = str(args.run)
    reconciled = False
    if fix:
        kill_orphan_agents(
            store,
            run_id,
            exclude_pids=frozenset({os.getpid()}),
        )
        reconciled = reconcile_stale_running_run(
            store,
            run_id,
            require_orphan_agents=False,
        )

    run = store.load_run(run_id)
    orphan_pids = scan_orphan_agent_pids(
        run_id,
        exclude_pids=frozenset({os.getpid()}),
        terminated_pids=terminated_pids_from_stop(run),
    )

    payload = {
        "ok": True,
        "run_id": run_id,
        "status": run.get("status"),
        "reconciled": reconciled,
        "orphan_agent_count": len(orphan_pids),
        "orphan_agent_pids": orphan_pids,
    }
    if args.stream_json:
        emit_payload(payload)
        return

    lines = [f"run {run_id}: status={run.get('status')}"]
    if reconciled:
        lines.append(
            "  reconciled stale running status to paused (orchestrator_interrupted)"
        )
    if orphan_pids:
        lines.append(
            f"  {len(orphan_pids)} orphan agent process(es) still alive: "
            + ", ".join(str(pid) for pid in orphan_pids)
        )
    else:
        lines.append("  no orphan agent processes detected")
    print("\n".join(lines))


__all__ = ["handle_doctor_command"]
