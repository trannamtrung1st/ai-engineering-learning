"""Sub-TDP CLI commands."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from top_down_planning.cli.common import (
    emit_error_message,
    emit_payload,
    open_run_store,
    resolve_runs_dir_from_args,
)
from top_down_planning.config import resolve_config
from top_down_planning.domain.run_kind import RUN_KIND_PARENT_EXECUTION, RUN_KIND_SUB_TDP_EXECUTION, resolve_run_kind
from top_down_planning.domain.sub_tdp_synthesis import child_run_summary
from top_down_planning.orchestrator.phases import OUTPUT_VALIDATED, SUB_TDPS, WHOLE_OUTPUT_REVIEW
from top_down_planning.package.lineage import ExecutionLineageValidator
from top_down_planning.package.loader import ExecutionPackageLoader
from top_down_planning.persistence.commit import CommitSpec
from top_down_planning.persistence.sub_tdp_state import (
    load_sub_tdp_state,
    merge_sub_tdp_state_into_production,
    unit_status_from_child_run,
)

_ALLOWED_ATTACH_PHASES = frozenset({SUB_TDPS, WHOLE_OUTPUT_REVIEW})


def handle_sub_tdp_attach_command(args: Namespace) -> None:
    parent_run_id = str(args.parent).strip()
    child_run_id = str(args.child).strip()

    cwd = Path.cwd()
    config_path = Path(args.config).resolve() if args.config else cwd / "config.yaml"
    resolved = resolve_config(config_path, cwd=cwd)
    store, _ = open_run_store(args, resolved_config=resolved)
    resolved_runs = resolve_runs_dir_from_args(args, resolved_config=resolved)

    parent_run = store.load_run(parent_run_id)
    if resolve_run_kind(parent_run) != RUN_KIND_PARENT_EXECUTION:
        emit_error_message(
            "parent run must be parent_execution",
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

    binding = parent_run.get("package_binding") or {}
    manifest_path = str(binding.get("manifest_path") or "").strip()
    production = store.load_production(parent_run_id)
    state = load_sub_tdp_state(production)
    if not manifest_path and isinstance(state, dict):
        manifest_path = str(state.get("manifest_path") or "").strip()
    if not manifest_path:
        emit_error_message(
            "parent run has no prepared execution package binding",
            exit_code=1,
            stream_json=args.stream_json,
            code="sub_tdp_attach_rejected",
        )

    package = ExecutionPackageLoader().load(
        Path(manifest_path).parent,
    )
    child_run = store.load_run(child_run_id)
    if resolve_run_kind(child_run) != RUN_KIND_SUB_TDP_EXECUTION:
        emit_error_message(
            "child run must be sub_tdp_execution",
            exit_code=1,
            stream_json=args.stream_json,
            code="sub_tdp_attach_rejected",
        )

    child_binding = child_run.get("package_binding") or {}
    plan_item_id = str(
        child_binding.get("selected_unit_id") or child_binding.get("unit_id") or ""
    )
    if not plan_item_id:
        emit_error_message(
            "child run is missing embedded unit lineage",
            exit_code=1,
            stream_json=args.stream_json,
            code="sub_tdp_attach_rejected",
        )

    mismatches = ExecutionLineageValidator().validate_attach(
        parent_package=package,
        parent_manifest_digest=str(package.manifest.get("package_digest") or ""),
        child_run=child_run,
    )
    if mismatches:
        detail = mismatches[0]
        emit_error_message(
            f"lineage mismatch on {detail.field}: expected {detail.expected}, got {detail.actual}",
            exit_code=1,
            stream_json=args.stream_json,
            code="sub_tdp_attach_rejected",
        )

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

    existing_child_id = str(unit_record.get("child_run_id") or "").strip()
    existing_status = str(unit_record.get("status") or "")
    if existing_child_id and existing_child_id != child_run_id:
        emit_error_message(
            "unit already bound to a different child run",
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
    if child_status == "completed" and str(child_run.get("phase") or "") != OUTPUT_VALIDATED:
        emit_error_message(
            "completed child must reach output_validated before attach",
            exit_code=1,
            stream_json=args.stream_json,
            code="sub_tdp_attach_rejected",
        )

    unit_record["child_run_id"] = child_run_id
    unit_record["status"] = unit_status_from_child_run(child_run)
    child_production = store.load_production(child_run_id)
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
                    "type": "sub_tdp:attach",
                    "run_id": parent_run_id,
                    "plan_item_id": plan_item_id,
                    "child_run_id": child_run_id,
                    "child_status": child_status,
                }
            ],
        ),
    )

    emit_payload(
        {
            "ok": True,
            "parent_run_id": parent_run_id,
            "plan_item_id": plan_item_id,
            "child_run_id": child_run_id,
            "unit_status": unit_record["status"],
            "runs_dir": str(resolved_runs.path),
        },
    )


__all__ = ["handle_sub_tdp_attach_command"]
