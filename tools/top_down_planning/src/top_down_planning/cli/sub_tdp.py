"""Sub-TDP CLI commands."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from top_down_planning.cli.common import (
    emit_error_message,
    emit_payload,
    open_run_store,
)
from top_down_planning.domain.run_kind import (
    RUN_KIND_PARENT_EXECUTION,
    RUN_KIND_SUB_TDP_EXECUTION,
    resolve_run_kind,
)
from top_down_planning.domain.sub_tdp_synthesis import child_run_summary
from top_down_planning.orchestrator.phases import OUTPUT_VALIDATED, SUB_TDPS
from top_down_planning.package.lineage import (
    ExecutionLineageValidator,
    accepted_result_record,
)
from top_down_planning.package.loader import ExecutionPackageLoader
from top_down_planning.persistence.commit import CommitSpec
from top_down_planning.persistence.sub_tdp_state import (
    load_sub_tdp_state,
    merge_sub_tdp_state_into_production,
    unit_status_from_child_run,
)

# Attach only while parent is still collecting children — never after synthesis.
_ALLOWED_ATTACH_PHASES = frozenset({SUB_TDPS})


def handle_sub_tdp_attach_command(args: Namespace) -> None:
    parent_run_id = str(args.parent).strip()
    child_run_id = str(args.child).strip()

    # Attach needs only the run store locator — not a product YAML config.
    store, resolved_runs = open_run_store(args, resolved_config=None)

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
    if parent_status != "paused":
        emit_error_message(
            "parent run must be paused before attach "
            "(use tdp execute --parent-only or pause an active parent)",
            exit_code=1,
            stream_json=args.stream_json,
            code="sub_tdp_attach_rejected",
        )
    if phase not in _ALLOWED_ATTACH_PHASES:
        emit_error_message(
            f"parent phase must be {SUB_TDPS} to attach children "
            f"(got {phase!r}); late attach after synthesis is rejected",
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

    package = ExecutionPackageLoader().load(Path(manifest_path).parent)
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

    child_production = store.load_production(child_run_id)
    child_plan = store.load_plan_model(child_run_id)
    mismatches = ExecutionLineageValidator().validate_attach(
        parent_package=package,
        parent_manifest_digest=str(package.manifest.get("package_digest") or ""),
        child_run=child_run,
        child_production=child_production,
        child_plan=child_plan,
    )
    if mismatches:
        detail = mismatches[0]
        emit_error_message(
            f"lineage mismatch on {detail.field}: expected {detail.expected}, got {detail.actual}",
            exit_code=1,
            stream_json=args.stream_json,
            code="sub_tdp_attach_rejected",
        )

    from top_down_planning.package.lineage import validate_accepted_child_delivery

    try:
        validate_accepted_child_delivery(
            store=store,
            child_run_id=child_run_id,
            child_run=child_run,
            child_production=child_production,
        )
    except ValueError as exc:
        emit_error_message(
            str(exc),
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
    if existing_child_id and existing_child_id != child_run_id:
        emit_error_message(
            "unit already bound to a different child run",
            exit_code=1,
            stream_json=args.stream_json,
            code="sub_tdp_attach_rejected",
        )

    unit = package.units[plan_item_id]
    accepted = accepted_result_record(
        child_run=child_run,
        child_production=child_production,
        unit_id=plan_item_id,
        unit_plan_digest=unit.plan_digest,
        package_id=str(package.manifest.get("package_id") or ""),
        package_digest=str(package.manifest.get("package_digest") or ""),
        assigned_subtree_digest=unit.assigned_subtree_digest,
    )
    from top_down_planning.package.lineage import accepted_result_digest

    unit_record["child_run_id"] = child_run_id
    unit_record["status"] = unit_status_from_child_run(child_run)
    unit_record["summary"] = child_run_summary(child_production, child_run)
    unit_record["accepted_result"] = accepted
    unit_record["accepted_result_digest"] = accepted_result_digest(accepted)
    from top_down_planning.package.lineage import verify_accepted_result_attestation

    verify_accepted_result_attestation(unit_record)
    state["active_unit_id"] = None
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
                    "unit_id": plan_item_id,
                    "child_run_id": child_run_id,
                    "child_status": str(child_run.get("status") or ""),
                    "package_id": package.manifest.get("package_id"),
                    "output_digest": accepted.get("output_digest"),
                    "accepted_result_digest": unit_record["accepted_result_digest"],
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
            "accepted_result_digest": unit_record["accepted_result_digest"],
            "runs_dir": str(resolved_runs.path),
        },
    )


__all__ = ["handle_sub_tdp_attach_command"]
