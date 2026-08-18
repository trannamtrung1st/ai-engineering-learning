"""tdp prepare — planning, review, and execution-package materialization (proposal §6.1)."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from typing import Any

from top_down_planning.cli.common import (
    emit_command_result,
    emit_error_message,
    format_run_startup_diagnostics,
    provider_extra_env,
    resolve_runs_dir_from_args,
    run_startup_diagnostics_payload,
)
from top_down_planning.cli.user import (
    _build_run_engine,
    _create_provider_for_run,
    _exit_for_cancel,
    _handle_blocking_run_interrupt,
    _initial_plan,
)
from top_down_planning.config import (
    ConfigError,
    build_initial_context_snapshot_binding_with_diagnostics,
    compute_input_digest,
    compute_output_goal_digest,
    resolve_config,
    resolve_output_goal_text,
    resolve_workspace,
)
from top_down_planning.domain.run_kind import RUN_KIND_PLANNING
from top_down_planning.invocation import invocation_options_from_args, invocation_to_dict
from top_down_planning.notifications import NotificationContext, wrap_run_store
from top_down_planning.observability import ObservabilityContext, build_observability_context
from top_down_planning.orchestrator.run_lifecycle_reconciliation import cleanup_staging_dirs
from top_down_planning.orchestrator.phases import PLAN_VALIDATED
from top_down_planning.package.builder import ExecutionPackageBuilder
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.path_ids import new_run_id
from core_tools.observability import ConsoleEvent


def handle_prepare_command(args: Namespace) -> None:
    if not args.config:
        emit_error_message(
            "tdp prepare requires --config",
            exit_code=2,
            stream_json=args.stream_json,
            code="missing_config",
        )

    config_path = Path(args.config).resolve()
    try:
        resolved = resolve_config(config_path, args.set)
    except ConfigError as exc:
        emit_error_message(
            str(exc),
            exit_code=2,
            stream_json=args.stream_json,
            code="config_error",
        )

    output_dir = Path(args.output).resolve() if args.output else Path(".tdp/execution").resolve()
    cwd = Path.cwd().resolve()
    workspace = resolve_workspace(resolved, cwd=cwd)
    try:
        output_goal = resolve_output_goal_text(resolved, base_dir=workspace)
    except ConfigError as exc:
        emit_error_message(
            str(exc),
            exit_code=2,
            stream_json=args.stream_json,
            code="config_error",
        )

    input_digest = compute_input_digest(resolved, base_dir=workspace)
    output_goal_digest = compute_output_goal_digest(resolved, base_dir=workspace)
    binding, context_spec_digest, context_snapshot_digest, snapshot_diag = (
        build_initial_context_snapshot_binding_with_diagnostics(
            resolved,
            workspace=workspace,
        )
    )
    run_id = new_run_id()
    plan = _initial_plan(run_id, resolved, output_goal=output_goal)

    resolved_runs = resolve_runs_dir_from_args(args, resolved_config=resolved)
    if resolved_runs.source == "default":
        emit_error_message(
            "tdp prepare requires an explicit run store: set runtime.runs_dir in the "
            "config, pass --runs-dir, or export TDP_RUNS_DIR",
            exit_code=2,
            stream_json=args.stream_json,
            code="missing_runs_dir",
        )

    store = FileRunStore(resolved_runs.path)
    store.root.mkdir(parents=True, exist_ok=True)
    cleanup_staging_dirs(store)

    invocation = invocation_options_from_args(
        args,
        resolved_config=resolved,
        resolved_runs=resolved_runs,
    )
    invocation_dict = invocation_to_dict(invocation)
    invocation_dict["command"] = "prepare"
    invocation_dict["until"] = "validated"

    store.create_run(
        run_id,
        plan=plan,
        resolved_config=resolved,
        input_digest=input_digest,
        output_goal_digest=output_goal_digest,
        context_spec_digest=context_spec_digest,
        context_snapshot_digest=context_snapshot_digest,
        context_snapshot_binding=binding,
        workspace=str(workspace),
        invocation=invocation_dict,
        run_extras={"run_kind": RUN_KIND_PLANNING},
    )
    store.append_event(
        run_id,
        {"type": "context_snapshot_collected", **snapshot_diag.to_event_fields()},
    )

    diagnostics = run_startup_diagnostics_payload(
        cwd=cwd,
        config_path=config_path,
        workspace=workspace,
        resolved_runs=resolved_runs,
        run_id=run_id,
        store=store,
    )
    observability = build_observability_context(
        options=invocation.observability,
        run_id=run_id,
        run_dir=resolved_runs.path / run_id,
    )
    notifications = NotificationContext(options=invocation.notifications)
    observability.emit(
        ConsoleEvent(
            category="run:start",
            message=(
                "Starting prepare run (planning + review + package materialization).\n"
                f"{format_run_startup_diagnostics(diagnostics)}"
            ),
            fields={"until": "validated"},
            run_id=run_id,
        )
    )

    try:
        engine = _build_run_engine(
            store,
            resolved_runs,
            run_id=run_id,
            observability=observability,
            notifications=notifications,
        )
        continuation = engine.continue_run(run_id, until="validated")
    except KeyboardInterrupt:
        _handle_blocking_run_interrupt(
            run_id=run_id,
            store=store,
            observability=observability,
            notifications=notifications,
            stream_json=args.stream_json,
        )
    finally:
        observability.close()

    if continuation.cancelled:
        _exit_for_cancel(run_id=run_id, store=store, stream_json=args.stream_json)

    run_record = store.load_run(run_id)
    if str(run_record.get("phase") or "") != PLAN_VALIDATED:
        emit_error_message(
            continuation.reason or "prepare did not reach plan_validated",
            exit_code=1,
            stream_json=args.stream_json,
            code="prepare_incomplete",
        )

    try:
        built = ExecutionPackageBuilder().build_from_planning_run(
            store,
            run_id,
            output_dir=output_dir,
            replace=getattr(args, "replace", False),
        )
    except ValueError as exc:
        emit_error_message(
            str(exc),
            exit_code=1,
            stream_json=args.stream_json,
            code="package_build_failed",
        )

    run_record = store.load_run(run_id)
    digests = dict(run_record.get("digests") or {})
    payload: dict[str, Any] = {
        "ok": True,
        "planning_run_id": run_id,
        "package_id": built.package_id,
        "manifest": str(built.manifest_path),
        "plan_revision": store.load_plan(run_id).get("revision"),
        "plan_digest": digests.get("plan"),
    }
    emit_command_result(
        payload,
        human_message=(
            f"Prepared package {built.package_id} from planning run {run_id} "
            f"(manifest: {built.manifest_path})."
        ),
        stream_json=args.stream_json,
    )


__all__ = ["handle_prepare_command"]
