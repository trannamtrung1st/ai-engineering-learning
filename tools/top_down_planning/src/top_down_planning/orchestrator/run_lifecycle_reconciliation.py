"""Reconcile interrupted runs and incomplete workspace artifacts."""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

from core_tools.persistence import PersistenceError, try_exclusive_file_lock
from top_down_planning.domain.run_lifecycle import StopRecord
from top_down_planning.domain.run_ownership import (
    holds_run_ownership,
    is_run_orchestrator_alive,
    resolve_run_dir,
)
from top_down_planning.orchestrator.agent_process_cleanup import (
    scan_orphan_agent_pids,
    terminated_pids_from_stop,
)
from top_down_planning.orchestrator.run_transitions import pause_run
from top_down_planning.persistence.interface import RunStore
from top_down_planning.persistence.path_containment import lexical_run_dir
from top_down_planning.persistence.transaction_inspect import (
    classify_run_transactions,
    list_txn_candidate_dirs,
)

_RUN_DIR_PATTERN = re.compile(r"^run-\d{8}T\d{6}-[0-9a-f]{6}$")
_CREATING_DIR_PREFIX = ".creating-"
_COMMIT_STAGE_PREFIX = ".stage-"
_COMMIT_RETIRED_PREFIX = ".retired-txn-"


def _running_without_live_orchestrator(store: RunStore, run_id: str) -> bool:
    run = store.load_run(run_id)
    if str(run.get("status") or "") != "running":
        return False
    run_dir = resolve_run_dir(store, run_id)
    if run_dir is None:
        return False
    return not is_run_orchestrator_alive(run_dir)


def reconcile_stale_running_run(
    store: RunStore,
    run_id: str,
    *,
    message: str = "orchestrator is no longer running",
    require_orphan_agents: bool = True,
) -> bool:
    """Pause a stale ``running`` run when its orchestrator is gone.

  When *require_orphan_agents* is true (default), only reconcile when orphan
  agent processes are still alive. ``tdp doctor --fix`` passes false to
  reconcile interrupted runs even after orphan cleanup.
  """

    if not _running_without_live_orchestrator(store, run_id):
        return False

    run = store.load_run(run_id)
    orphan_pids = scan_orphan_agent_pids(
        run_id,
        exclude_pids=frozenset({os.getpid()}),
        terminated_pids=terminated_pids_from_stop(run),
    )
    if require_orphan_agents and not orphan_pids:
        return False

    phase = str(run.get("phase") or "unknown")
    details: dict[str, Any] = {}
    if orphan_pids:
        details["orphan_agent_pids"] = orphan_pids
    pause_run(
        store,
        run_id,
        stop=StopRecord(
            code="orchestrator_interrupted",
            category="operational",
            phase=phase,
            message=message,
            details=details,
        ),
        event_type="run_reconciled",
        reason="stale_running",
    )
    return True


def reconcile_stale_running_run_under_ownership(
    store: RunStore,
    run_id: str,
    *,
    message: str = "orchestrator is no longer running",
    require_orphan_agents: bool = True,
) -> bool:
    """Pause a stale ``running`` run while the caller holds repair ownership.

    Unlike ``reconcile_stale_running_run``, this does not treat the caller's
    repair ownership flock as evidence of a live orchestrator.
    """

    if not holds_run_ownership(run_id):
        return False

    run = store.load_run(run_id)
    if str(run.get("status") or "") != "running":
        return False

    orphan_pids = scan_orphan_agent_pids(
        run_id,
        exclude_pids=frozenset({os.getpid()}),
        terminated_pids=terminated_pids_from_stop(run),
    )
    if require_orphan_agents and not orphan_pids:
        return False

    phase = str(run.get("phase") or "unknown")
    details: dict[str, Any] = {}
    if orphan_pids:
        details["orphan_agent_pids"] = orphan_pids
    pause_run(
        store,
        run_id,
        stop=StopRecord(
            code="orchestrator_interrupted",
            category="operational",
            phase=phase,
            message=message,
            details=details,
        ),
        event_type="run_reconciled",
        reason="stale_running",
    )
    return True


def list_incomplete_run_dirs(store: RunStore) -> list[str]:
    """Return run directory names that look like runs but lack ``run.json``."""

    root = getattr(store, "root", None)
    if root is None:
        return []
    root_path = Path(root)
    if not root_path.is_dir():
        return []

    incomplete: list[str] = []
    for entry in sorted(root_path.iterdir()):
        if not entry.is_dir():
            continue
        name = entry.name
        if name.startswith(_CREATING_DIR_PREFIX):
            continue
        if not _RUN_DIR_PATTERN.match(name):
            continue
        if (entry / "run.json").is_file():
            continue
        incomplete.append(name)
    return incomplete


def list_staging_run_dirs(store: RunStore) -> list[str]:
    """Return leftover ``.creating-<run-id>`` staging directories."""

    root = getattr(store, "root", None)
    if root is None:
        return []
    root_path = Path(root)
    if not root_path.is_dir():
        return []

    staging: list[str] = []
    for entry in sorted(root_path.iterdir()):
        if not entry.is_dir():
            continue
        if not entry.name.startswith(_CREATING_DIR_PREFIX):
            continue
        staging.append(entry.name)
    return staging


def list_commit_transaction_dirs(store: RunStore) -> list[str]:
    """Return leftover commit ``.stage-*`` and ``.retired-txn-*`` directories under runs."""

    root = getattr(store, "root", None)
    if root is None:
        return []
    root_path = Path(root)
    if not root_path.is_dir():
        return []

    leftovers: list[str] = []
    for run_entry in sorted(root_path.iterdir()):
        if not run_entry.is_dir() or not _RUN_DIR_PATTERN.match(run_entry.name):
            continue
        for entry in sorted(run_entry.iterdir()):
            if not entry.is_dir():
                continue
            name = entry.name
            if name.startswith(_COMMIT_STAGE_PREFIX) or name.startswith(_COMMIT_RETIRED_PREFIX):
                leftovers.append(f"{run_entry.name}/{name}")
    return leftovers


def cleanup_commit_transaction_dirs(store: RunStore) -> list[str]:
    """Remove leftover commit staging and retired transaction directories under runs."""

    removed: list[str] = []
    root = getattr(store, "root", None)
    if root is None:
        return removed
    root_path = Path(root)
    if not root_path.is_dir():
        return removed

    for relative_name in list_commit_transaction_dirs(store):
        run_id, _, txn_name = relative_name.partition("/")
        run_dir = root_path / run_id
        if not run_dir.is_dir():
            continue
        lock_path = run_dir / ".commit.lock"
        with try_exclusive_file_lock(lock_path) as acquired:
            if not acquired:
                continue
            path = run_dir / txn_name
            if not path.is_dir():
                continue
            shutil.rmtree(path, ignore_errors=True)
            if not path.exists():
                removed.append(relative_name)
    return removed


def cleanup_staging_dirs(store: RunStore) -> list[str]:
    """Remove leftover run-creation and commit-transaction staging directories."""

    removed: list[str] = []
    root = getattr(store, "root", None)
    if root is None:
        return removed
    root_path = Path(root)
    if not root_path.is_dir():
        return removed

    for name in list_staging_run_dirs(store):
        path = root_path / name
        if not path.is_dir():
            continue
        lock_path = root_path / f"{name}.lock"
        with try_exclusive_file_lock(lock_path) as acquired:
            if not acquired:
                continue
            shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            removed.append(name)
    removed.extend(cleanup_commit_transaction_dirs(store))
    return removed


def diagnose_canonical_run(run_dir: Path, run_id: str) -> dict[str, Any]:
    """Non-mutating, commit-lock-aware classification of a run directory."""

    from top_down_planning.persistence.persisted_validation import (
        validate_canonical_run_artifacts,
    )

    try:
        lexical_run_dir(run_dir.parent, run_id)
    except PersistenceError:
        return {"kind": "corrupt"}

    lock_path = run_dir / ".commit.lock"
    with try_exclusive_file_lock(lock_path) as acquired:
        if not acquired:
            return {"kind": "busy"}
        presence = classify_run_transactions(run_dir, run_id)
        if presence == "recoverable":
            txn_dirs = list_txn_candidate_dirs(run_dir)
            return {
                "kind": "recoverable",
                "transaction_dirs": [f"{run_id}/{path.name}" for path in txn_dirs],
            }
        if presence == "unrecoverable":
            return {"kind": "corrupt"}
        try:
            if run_dir.is_symlink() or not run_dir.is_dir():
                raise PersistenceError("run directory must not be a symlink")
            run = validate_canonical_run_artifacts(run_dir, run_id)
        except (
            OSError,
            json.JSONDecodeError,
            UnicodeDecodeError,
            PersistenceError,
            TypeError,
            ValueError,
        ):
            return {"kind": "corrupt"}
        return {"kind": "ok", "run": run}


def recover_abandoned_transactions(store: RunStore) -> list[str]:
    """Recover abandoned ``.txn-*`` journals when the commit lock is free."""

    recovered: list[str] = []
    recover = getattr(store, "recover_incomplete_transactions", None)
    root = getattr(store, "root", None)
    if root is None or not callable(recover):
        return recovered
    root_path = Path(root)
    if not root_path.is_dir():
        return recovered
    for entry in sorted(root_path.iterdir()):
        run_id = entry.name
        if not _RUN_DIR_PATTERN.match(run_id):
            continue
        try:
            lexical = lexical_run_dir(root_path, run_id)
        except PersistenceError:
            continue
        if not lexical.is_dir():
            continue
        lock_path = lexical / ".commit.lock"
        with try_exclusive_file_lock(lock_path) as acquired:
            if not acquired:
                continue
            presence = classify_run_transactions(lexical, run_id)
        if presence != "recoverable":
            continue
        recover(run_id)
        recovered.append(run_id)
    return recovered


def workspace_diagnostics(store: RunStore) -> dict[str, Any]:
    """Summarize workspace-level run store hygiene issues."""

    incomplete_run_dirs = list_incomplete_run_dirs(store)
    staging_run_dirs = list_staging_run_dirs(store)
    commit_transaction_dirs = list_commit_transaction_dirs(store)

    idle_running: list[str] = []
    interrupted_running: list[str] = []
    corrupt_run_dirs: list[str] = []
    busy_run_dirs: list[str] = []
    recoverable_transaction_run_ids: list[str] = []
    recoverable_transaction_dirs: list[str] = []
    root = getattr(store, "root", None)
    if root is not None:
        root_path = Path(root)
        if root_path.is_dir():
            for entry in sorted(root_path.iterdir()):
                run_id = entry.name
                if not _RUN_DIR_PATTERN.match(run_id):
                    continue
                run_json = entry / "run.json"
                if not run_json.is_file() and not run_json.is_symlink():
                    continue
                diagnosis = diagnose_canonical_run(entry, run_id)
                kind = str(diagnosis.get("kind") or "")
                if kind == "busy":
                    busy_run_dirs.append(run_id)
                    continue
                if kind == "recoverable":
                    recoverable_transaction_run_ids.append(run_id)
                    recoverable_transaction_dirs.extend(
                        list(diagnosis.get("transaction_dirs") or [])
                    )
                    continue
                if kind != "ok":
                    corrupt_run_dirs.append(run_id)
                    continue
                run = diagnosis["run"]
                if str(run.get("status") or "") != "running":
                    continue
                run_dir = resolve_run_dir(store, run_id)
                if run_dir is None or is_run_orchestrator_alive(run_dir):
                    continue
                orphan_pids = scan_orphan_agent_pids(
                    run_id,
                    exclude_pids=frozenset({os.getpid()}),
                    terminated_pids=terminated_pids_from_stop(run),
                )
                if orphan_pids:
                    interrupted_running.append(run_id)
                else:
                    idle_running.append(run_id)

    return {
        "incomplete_run_dirs": incomplete_run_dirs,
        "staging_run_dirs": staging_run_dirs,
        "commit_transaction_dirs": commit_transaction_dirs,
        "corrupt_run_dirs": corrupt_run_dirs,
        "busy_run_dirs": busy_run_dirs,
        "recoverable_transaction_run_ids": recoverable_transaction_run_ids,
        "recoverable_transaction_dirs": recoverable_transaction_dirs,
        "idle_running_run_ids": idle_running,
        "interrupted_running_run_ids": interrupted_running,
    }


__all__ = [
    "cleanup_commit_transaction_dirs",
    "cleanup_staging_dirs",
    "diagnose_canonical_run",
    "list_commit_transaction_dirs",
    "list_incomplete_run_dirs",
    "list_staging_run_dirs",
    "reconcile_stale_running_run",
    "reconcile_stale_running_run_under_ownership",
    "recover_abandoned_transactions",
    "workspace_diagnostics",
]
