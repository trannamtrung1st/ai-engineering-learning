"""Run health diagnostics for orphan agent processes."""

from __future__ import annotations

from argparse import Namespace
from dataclasses import dataclass
from typing import Any

import os

from top_down_planning.cli.common import (
    emit_payload,
    emit_run_access_error,
    open_run_store_for_cli,
    require_cli_run_id,
)
from top_down_planning.domain.run_ownership import (
    RunOwnershipError,
    is_run_orchestrator_alive,
    resolve_run_dir,
    run_ownership,
)
from top_down_planning.orchestrator.agent_process_cleanup import (
    OrphanCleanupResult,
    kill_orphan_agents,
    scan_orphan_agent_pids,
    terminated_pids_from_stop,
)
from top_down_planning.orchestrator.run_lifecycle_reconciliation import (
    cleanup_staging_dirs,
    reconcile_stale_running_run_under_ownership,
    workspace_diagnostics,
)


@dataclass(frozen=True)
class DestructiveRunRepairResult:
    """Outcome of ownership-safe orphan cleanup and stale-run reconciliation."""

    reconciled: bool
    refusal: str | None = None
    failed_pids: tuple[int, ...] = ()


def _emit_doctor_result(args: Namespace, payload: dict[str, Any], lines: list[str]) -> None:
    exit_code = 0 if payload.get("ok", True) else 1
    if args.stream_json:
        emit_payload(payload, exit_code=exit_code)
        return
    print("\n".join(lines))
    if exit_code:
        raise SystemExit(exit_code)


def _destructive_fix_blocked(
    store,
    run_id: str,
) -> str | None:
    run = store.load_run(run_id)
    if str(run.get("status") or "") != "running":
        return None
    run_dir = resolve_run_dir(store, run_id)
    if run_dir is None:
        return None
    if is_run_orchestrator_alive(run_dir):
        return (
            "refusing destructive repair: a live orchestrator still owns this running run"
        )
    return None


def _apply_destructive_run_repair(
    store,
    run_id: str,
) -> DestructiveRunRepairResult:
    run_dir = resolve_run_dir(store, run_id)
    if run_dir is None:
        return DestructiveRunRepairResult(
            reconciled=False,
            refusal="refusing destructive repair: run directory not found",
        )
    try:
        with run_ownership(run_id, run_dir=run_dir):
            cleanup = kill_orphan_agents(
                store,
                run_id,
                exclude_pids=frozenset({os.getpid()}),
            )
            if cleanup.failed_pids:
                return DestructiveRunRepairResult(
                    reconciled=False,
                    failed_pids=cleanup.failed_pids,
                )
            run = store.load_run(run_id)
            if str(run.get("status") or "") == "running":
                reconciled = reconcile_stale_running_run_under_ownership(
                    store,
                    run_id,
                    require_orphan_agents=False,
                )
                return DestructiveRunRepairResult(reconciled=reconciled)
            return DestructiveRunRepairResult(reconciled=False)
    except RunOwnershipError as exc:
        return DestructiveRunRepairResult(
            reconciled=False,
            refusal=f"refusing destructive repair: {exc.message}",
        )


def _repair_candidate_run_ids(diagnostics: dict[str, Any]) -> list[str]:
    return sorted(
        set(diagnostics["interrupted_running_run_ids"])
        | set(diagnostics["idle_running_run_ids"])
    )


def handle_doctor_command(args: Namespace) -> None:
    if args.run:
        args.run = require_cli_run_id(args.run, stream_json=args.stream_json)
    store, _resolved = open_run_store_for_cli(args)
    try:
        _handle_doctor_command(args, store)
    except Exception as exc:
        emit_run_access_error(exc, stream_json=args.stream_json)


def _handle_doctor_command(args: Namespace, store) -> None:
    fix = bool(getattr(args, "fix", False))
    removed_staging_dirs: list[str] = []
    if fix:
        removed_staging_dirs = cleanup_staging_dirs(store)

    if not args.run:
        diagnostics = workspace_diagnostics(store)
        reconciled: list[str] = []
        repair_incomplete: list[str] = []
        repair_refused_run_ids: list[str] = []
        cleanup_failed_pids_by_run: dict[str, list[int]] = {}
        if fix:
            for run_id in _repair_candidate_run_ids(diagnostics):
                blocked = _destructive_fix_blocked(store, run_id)
                if blocked is not None:
                    repair_refused_run_ids.append(run_id)
                    continue
                repair = _apply_destructive_run_repair(store, run_id)
                if repair.refusal is not None:
                    repair_refused_run_ids.append(run_id)
                    continue
                if repair.failed_pids:
                    repair_incomplete.append(run_id)
                    cleanup_failed_pids_by_run[run_id] = list(repair.failed_pids)
                    continue
                if repair.reconciled:
                    reconciled.append(run_id)
            diagnostics = workspace_diagnostics(store)

        leftover_repair_targets: list[str] = []
        if fix:
            leftover_repair_targets = list(diagnostics["staging_run_dirs"]) + list(
                diagnostics["commit_transaction_dirs"]
            )
        payload: dict[str, Any] = {
            "ok": not repair_incomplete
            and not repair_refused_run_ids
            and not leftover_repair_targets
            and not diagnostics["corrupt_run_dirs"],
            "workspace": diagnostics,
            "reconciled_run_ids": reconciled,
            "repair_incomplete_run_ids": repair_incomplete,
            "repair_refused_run_ids": repair_refused_run_ids,
            "cleanup_failed_pids_by_run": cleanup_failed_pids_by_run,
            "removed_staging_dirs": removed_staging_dirs,
        }
        if args.stream_json:
            _emit_doctor_result(args, payload, [])
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
        if diagnostics["corrupt_run_dirs"]:
            lines.append(
                "  corrupt run dirs: " + ", ".join(diagnostics["corrupt_run_dirs"])
            )
        else:
            lines.append("  corrupt run dirs: none")
        if diagnostics["staging_run_dirs"]:
            lines.append(
                "  staging dirs (.creating-*): "
                + ", ".join(diagnostics["staging_run_dirs"])
            )
        else:
            lines.append("  staging dirs: none")
        if diagnostics["commit_transaction_dirs"]:
            lines.append(
                "  commit transaction dirs (.stage-*/.retired-txn-*): "
                + ", ".join(diagnostics["commit_transaction_dirs"])
            )
        else:
            lines.append("  commit transaction dirs: none")
        if fix and reconciled:
            lines.append("  reconciled runs: " + ", ".join(reconciled))
        if fix and repair_incomplete:
            lines.append(
                "  repair incomplete (surviving orphan agents): "
                + ", ".join(repair_incomplete)
            )
            for run_id in repair_incomplete:
                failed_pids = cleanup_failed_pids_by_run.get(run_id, [])
                if failed_pids:
                    lines.append(
                        f"    {run_id}: surviving PIDs "
                        + ", ".join(str(pid) for pid in failed_pids)
                    )
        if fix and removed_staging_dirs:
            lines.append(
                "  removed staging dirs: " + ", ".join(removed_staging_dirs)
            )
        _emit_doctor_result(args, payload, lines)
        return

    run_id = str(args.run)
    from top_down_planning.persistence.persisted_validation import (
        validate_canonical_run_artifacts,
    )

    lexical_run_dir = store.root / run_id
    if lexical_run_dir.exists() or lexical_run_dir.is_symlink():
        validate_canonical_run_artifacts(lexical_run_dir, run_id)
    repair_refused: str | None = None
    reconciled = False
    repair_incomplete = False
    cleanup_failed_pids: list[int] = []
    if fix:
        repair_refused = _destructive_fix_blocked(store, run_id)
        if repair_refused is None:
            repair = _apply_destructive_run_repair(store, run_id)
            if repair.refusal is not None:
                repair_refused = repair.refusal
            elif repair.failed_pids:
                repair_incomplete = True
                cleanup_failed_pids = list(repair.failed_pids)
            else:
                reconciled = repair.reconciled

    run = store.load_run(run_id)
    orphan_pids = scan_orphan_agent_pids(
        run_id,
        exclude_pids=frozenset({os.getpid()}),
        terminated_pids=terminated_pids_from_stop(run),
    )

    payload = {
        "ok": repair_refused is None and not repair_incomplete,
        "run_id": run_id,
        "status": run.get("status"),
        "reconciled": reconciled,
        "repair_incomplete": repair_incomplete,
        "repair_refused": repair_refused,
        "cleanup_failed_pids": cleanup_failed_pids,
        "orphan_agent_count": len(orphan_pids),
        "orphan_agent_pids": orphan_pids,
    }
    if args.stream_json:
        emit_payload(payload, exit_code=0 if payload["ok"] else 1)
        return

    lines = [f"run {run_id}: status={run.get('status')}"]
    if repair_refused:
        lines.append(f"  {repair_refused}")
    if repair_incomplete:
        lines.append("  repair incomplete: orphan agent cleanup failed")
        if cleanup_failed_pids:
            lines.append(
                "  surviving orphan agent process(es): "
                + ", ".join(str(pid) for pid in cleanup_failed_pids)
            )
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
    _emit_doctor_result(args, payload, lines)


__all__ = ["DestructiveRunRepairResult", "handle_doctor_command"]
