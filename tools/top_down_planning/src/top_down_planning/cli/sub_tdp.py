"""Sub-TDP CLI commands."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from typing import Any

from top_down_planning.cli.common import (
    emit_error_message,
    emit_payload,
    open_run_store,
    resolve_runs_dir_from_args,
)
from top_down_planning.config import resolve_config, resolve_workspace
from top_down_planning.config.execution import (
    execution_state_file_from_config,
    is_sub_tdps_mode,
)
from top_down_planning.domain.sub_tdp_synthesis import child_run_summary
from top_down_planning.domain.sub_tdp_units import SubTdpUnit
from top_down_planning.orchestrator.phases import SUB_TDPS, WHOLE_OUTPUT_REVIEW
from top_down_planning.orchestrator.sub_tdp_child_driver import (
    child_runs_store_path,
    unit_relative_directory,
)
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.commit import CommitSpec
from top_down_planning.persistence.sub_tdp_state import (
    load_sub_tdp_state,
    merge_sub_tdp_state_into_production,
    unit_status_from_child_run,
    write_sub_tdp_state_yaml,
)
from top_down_planning.workspace import run_workspace


_ALLOWED_ATTACH_PHASES = frozenset({SUB_TDPS, WHOLE_OUTPUT_REVIEW})


def handle_sub_tdp_attach_command(args: Namespace) -> None:
    parent_run_id = str(args.parent).strip()
    plan_item_id = str(args.unit).strip()
    child_run_id = str(args.child).strip()

    cwd = Path.cwd()
    config_path = Path(args.config).resolve() if args.config else cwd / "config.yaml"
    resolved = resolve_config(config_path, cwd=cwd)
    store, _ = open_run_store(args, resolved_config=resolved)
    resolved_runs = resolve_runs_dir_from_args(args, resolved_config=resolved)

    parent_run = store.load_run(parent_run_id)
    parent_config = store.load_resolved_config(parent_run_id)
    if not is_sub_tdps_mode(parent_config):
        emit_error_message(
            "parent run execution.mode must be sub_tdps",
            exit_code=1,
            stream_json=args.stream_json,
            code="sub_tdp_attach_rejected",
        )

    phase = str(parent_run.get("phase") or "")
    parent_status = str(parent_run.get("status") or "")
    if parent_status in {"failed", "completed"}:
        emit_error_message(
            f"parent run status {parent_status!r} cannot accept attach",
            exit_code=1,
            stream_json=args.stream_json,
            code="sub_tdp_attach_rejected",
        )
    if phase not in _ALLOWED_ATTACH_PHASES:
        emit_error_message(
            f"parent phase must be one of: {', '.join(sorted(_ALLOWED_ATTACH_PHASES))}",
            exit_code=1,
            stream_json=args.stream_json,
            code="sub_tdp_attach_rejected",
        )

    production = store.load_production(parent_run_id)
    state = load_sub_tdp_state(production)
    if state is None:
        emit_error_message(
            "parent production missing sub_tdps orchestration state",
            exit_code=1,
            stream_json=args.stream_json,
            code="sub_tdp_attach_rejected",
        )

    unit_record = None
    for unit in state.get("units") or []:
        if isinstance(unit, dict) and str(unit.get("plan_item_id") or "") == plan_item_id:
            unit_record = unit
            break
    if unit_record is None:
        emit_error_message(
            f"unknown sub-tdp unit: {plan_item_id!r}",
            exit_code=1,
            stream_json=args.stream_json,
            code="sub_tdp_attach_rejected",
        )

    workspace = run_workspace(parent_run)
    state_file = execution_state_file_from_config(parent_config)
    unit = SubTdpUnit(
        plan_item_id=str(unit_record.get("plan_item_id") or unit_record.get("id") or ""),
        title=str(unit_record.get("title") or ""),
        outcome="",
        directory=str(unit_record.get("directory") or ""),
        ordinal=0,
    )
    child_store = FileRunStore(
        child_runs_store_path(workspace, unit, state_file=state_file)
    )
    if not child_store.run_dir(child_run_id).is_dir():
        emit_error_message(
            f"child run not found under unit runs store: {child_run_id}",
            exit_code=1,
            stream_json=args.stream_json,
            code="sub_tdp_attach_rejected",
        )

    child_run = child_store.load_run(child_run_id)
    child_config = child_store.load_resolved_config(child_run_id)
    if is_sub_tdps_mode(child_config):
        emit_error_message(
            "child run cannot use execution.mode=sub_tdps",
            exit_code=1,
            stream_json=args.stream_json,
            code="sub_tdp_attach_rejected",
        )

    parent_workspace = resolve_workspace(parent_config, cwd=workspace)
    child_workspace = resolve_workspace(child_config, cwd=workspace)
    if parent_workspace.resolve() != child_workspace.resolve():
        emit_error_message(
            "child workspace must match parent workspace",
            exit_code=1,
            stream_json=args.stream_json,
            code="sub_tdp_attach_rejected",
        )

    child_status = str(child_run.get("status") or "")
    if child_status not in {"completed", "paused"}:
        emit_error_message(
            "child run must be completed or paused for attach",
            exit_code=1,
            stream_json=args.stream_json,
            code="sub_tdp_attach_rejected",
        )

    unit_record["child_run_id"] = child_run_id
    unit_record["status"] = unit_status_from_child_run(child_run)
    child_production = child_store.load_production(child_run_id)
    unit_record["summary"] = child_run_summary(child_production, child_run)
    state["active_unit_id"] = plan_item_id if child_status == "paused" else None
    merged = merge_sub_tdp_state_into_production(production, state)
    expected_revision = int(production["revision"])
    merged["revision"] = expected_revision + 1
    store.commit(
        parent_run_id,
        CommitSpec(
            production=merged,
            production_expected_revision=expected_revision,
            events=[
                {
                    "type": "sub_tdp_child_attached",
                    "run_id": parent_run_id,
                    "plan_item_id": plan_item_id,
                    "child_run_id": child_run_id,
                    "unit_directory": unit_record.get("directory"),
                    "child_status": child_status,
                }
            ],
        ),
    )
    write_sub_tdp_state_yaml(
        workspace,
        state_file,
        load_sub_tdp_state(merged) or state,
    )

    emit_payload(
        {
            "ok": True,
            "parent_run_id": parent_run_id,
            "plan_item_id": plan_item_id,
            "child_run_id": child_run_id,
            "unit_status": unit_record["status"],
            "unit_directory": unit_relative_directory(unit, state_file=state_file),
            "runs_dir": str(resolved_runs.path),
        },
    )


__all__ = ["handle_sub_tdp_attach_command"]
