"""User-facing orchestration CLI commands (proposal §20)."""

from __future__ import annotations

import json
import os
import sys
from argparse import Namespace
from pathlib import Path
from typing import Any

from top_down_planning.agent_tool.config import planning_limits_from_config
from top_down_planning.agent_tool.views import build_active_view, build_audit_view
from top_down_planning.cli.common import (
    emit_error_message,
    emit_message,
    emit_operational_error,
    emit_payload,
    emit_run_access_error,
    run_access_boundary,
    format_run_startup_diagnostics,
    open_run_store_for_cli,
    provider_extra_env,
    require_cli_run_id,
    resolve_runs_dir_from_args,
    run_startup_diagnostics_payload,
    store_diagnostics_payload,
)
from top_down_planning.persistence.path_ids import new_run_id
from top_down_planning.config import (
    ConfigError,
    build_initial_context_snapshot_binding_with_diagnostics,
    compute_input_digest,
    compute_output_goal_digest,
    resolve_config,
    resolve_output_goal_text,
    resolve_workspace,
)
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.run_lifecycle import continuation_ok_from_run
from top_down_planning.domain.run_ownership import holds_run_ownership
from top_down_planning.domain.plan_tree import PLAN_ROOT_ITEM_ID, seed_plan_root_item
from top_down_planning.agent_tool.validation_context import (
    compute_plan_approval_actual_digests,
    user_validate_mode_and_context,
)
from top_down_planning.domain.reviews import find_whole_output_approval
from top_down_planning.domain.output_validators import (
    build_output_approval_validation_context,
    validate_output,
)
from top_down_planning.domain.validators import validate_plan
from top_down_planning.orchestrator import RunEngine
from top_down_planning.orchestrator.phases import (
    OUTPUT_VALIDATED,
    WHOLE_OUTPUT_REVIEW,
)
from top_down_planning.cli.resume_diagnostics import (
    build_resume_plan_summary,
    format_resume_plan_summary_text,
)
from top_down_planning.orchestrator.agent_process_cleanup import (
    finalize_user_cancel,
    workspace_has_orphan_agents,
)
from top_down_planning.orchestrator.run_lifecycle_reconciliation import (
    cleanup_staging_dirs,
    reconcile_stale_running_run,
)
from top_down_planning.domain.resume_limits import consumed_limits_from_run
from top_down_planning.config.resume_policy import resolve_resume_candidate_for_run
from top_down_planning.orchestrator.resume import (
    ApplyResumeError,
    PrepareResumeBlockedError,
    apply_resume_plan_atomically,
    is_terminal_resume_snapshot,
    load_run_resume_snapshot,
    prepare_resume,
)
from top_down_planning.workspace import run_workspace
from top_down_planning.invocation import (
    invocation_options_from_args,
    invocation_to_dict,
)
from top_down_planning.notifications import (
    NotificationContext,
    notify_run_outcome,
    wrap_run_store,
)
from top_down_planning.observability import (
    ObservabilityContext,
    build_observability_context,
    cancel_console_event,
    emit_resume_plan_diagnostics,
)
from top_down_planning.domain.run_kind import (
    RUN_KIND_PARENT_EXECUTION,
    RUN_KIND_PLANNING,
    resolve_run_kind,
)
from top_down_planning.domain.plan_schema import UnsupportedPlanSchemaVersionError
from top_down_planning.persistence import FileRunStore, PersistenceError, RunNotFoundError
from top_down_planning.persistence.digests import compute_output_digest
from top_down_planning.persistence.sub_tdp_state import load_sub_tdp_state, sub_tdp_progress
from core_tools.observability import ConsoleEvent
from core_tools.provider import create_provider

_CANCEL_EXIT_CODE = 130


def _exit_for_cancel(
    *,
    run_id: str,
    stream_json: bool,
    run: dict[str, Any] | None = None,
    store: FileRunStore | None = None,
    phase: str | None = None,
    status: str | None = None,
) -> None:
    """Exit with SIGINT convention (130) after cancellation was logged."""

    payload_run = run
    if payload_run is None and store is not None:
        try:
            payload_run = store.load_run(run_id)
        except (RunNotFoundError, PersistenceError, OSError):
            payload_run = None
    if payload_run is not None:
        phase = payload_run.get("phase") if phase is None else phase
        status = payload_run.get("status") if status is None else status
    if stream_json:
        emit_payload(
            {
                "ok": False,
                "cancelled": True,
                "run_id": run_id,
                "phase": phase,
                "status": status,
                "reason": "cancelled by user",
            },
            exit_code=_CANCEL_EXIT_CODE,
        )
    raise SystemExit(_CANCEL_EXIT_CODE) from None


def _exit_for_command_interrupt(
    *,
    run_id: str,
    stream_json: bool,
    run: dict[str, Any] | None = None,
    store: FileRunStore | None = None,
    phase: str | None = None,
    status: str | None = None,
) -> None:
    """Exit with SIGINT convention when the command was interrupted without cancelling the run."""

    payload_run = run
    if payload_run is None and store is not None:
        try:
            payload_run = store.load_run(run_id)
        except (RunNotFoundError, PersistenceError, OSError):
            payload_run = None
    if payload_run is not None:
        phase = payload_run.get("phase") if phase is None else phase
        status = payload_run.get("status") if status is None else status
    if stream_json:
        emit_payload(
            {
                "ok": False,
                "cancelled": False,
                "command_interrupted": True,
                "run_id": run_id,
                "phase": phase,
                "status": status,
                "reason": "command interrupted by user",
            },
            exit_code=_CANCEL_EXIT_CODE,
        )
    sys.stdout.write("Command interrupted.\n")
    raise SystemExit(_CANCEL_EXIT_CODE) from None


def _run_is_user_cancelled(run: dict[str, Any]) -> bool:
    if str(run.get("status") or "") != "paused":
        return False
    stop = run.get("stop")
    if not isinstance(stop, dict):
        return False
    return str(stop.get("code") or "") == "user_cancelled"


def _handle_blocking_run_interrupt(
    *,
    run_id: str,
    store: FileRunStore,
    observability: ObservabilityContext,
    notifications: NotificationContext | None,
    stream_json: bool,
) -> None:
    """Emit cancel observability and exit when Ctrl+C escapes the engine loop."""

    try:
        with run_access_boundary(stream_json=stream_json):
            run = store.load_run(run_id)
    except SystemExit:
        raise

    if str(run.get("status") or "") == "running" and holds_run_ownership(run_id):
        phase = str(run.get("phase") or "unknown")
        finalize_user_cancel(
            store,
            run_id,
            phase=phase,
            exclude_pids=frozenset({os.getpid()}),
        )
        try:
            run = store.load_run(run_id)
        except (RunNotFoundError, PersistenceError, OSError):
            run = {
                **run,
                "status": "paused",
                "stop": {
                    "code": "user_cancelled",
                    "category": "operational",
                    "phase": phase,
                    "message": "cancelled by user",
                },
            }

    if _run_is_user_cancelled(run):
        if notifications is not None:
            notify_run_outcome(
                "cancelled",
                run_id=run_id,
                run=run,
                options=notifications.options,
            )
        observability.emit(
            cancel_console_event(
                run_id=run_id,
                phase=str(run.get("phase") or "unknown"),
            )
        )
        _exit_for_cancel(run_id=run_id, stream_json=stream_json, run=run)

    _exit_for_command_interrupt(
        run_id=run_id,
        stream_json=stream_json,
        run=run,
    )


def _cli_load_run(
    store: FileRunStore,
    run_id: str,
    *,
    stream_json: bool,
) -> dict[str, Any]:
    with run_access_boundary(stream_json=stream_json):
        return store.load_run(run_id)


def _canonical_snapshot_for_cli(
    store: FileRunStore,
    run_id: str,
    *,
    stream_json: bool,
):
    with run_access_boundary(stream_json=stream_json):
        return store.load_canonical_snapshot(run_id)


def _open_run_store_for_command(
    args: Namespace,
    *,
    resolved_config: dict[str, Any] | None = None,
    create: bool = False,
) -> tuple[FileRunStore, Any]:
    return open_run_store_for_cli(
        args, resolved_config=resolved_config, create=create
    )


def _create_provider_for_run(
    config: dict[str, Any],
    *,
    workspace: Path,
    resolved_runs: Any,
    run_id: str,
    store: FileRunStore,
    on_provider_event: Any | None = None,
) -> Any:
    return create_provider(
        config,
        workspace=workspace,
        extra_env=provider_extra_env(resolved_runs, run_id=run_id, store=store),
        on_provider_event=on_provider_event,
    )


def _build_run_engine(
    store: FileRunStore,
    resolved_runs: Any,
    *,
    run_id: str,
    observability: ObservabilityContext,
    notifications: NotificationContext | None = None,
) -> RunEngine:
    def create_provider(config: dict[str, Any], workspace: Path) -> Any:
        return _create_provider_for_run(
            config,
            workspace=workspace,
            resolved_runs=resolved_runs,
            run_id=run_id,
            store=store,
            on_provider_event=observability.provider_callback(),
        )

    return RunEngine(
        wrap_run_store(
            store,
            observability=observability,
            notifications=notifications,
        ),
        create_provider=create_provider,
        observability=observability,
    )


def handle_run_command(args: Namespace) -> None:
    if not args.config:
        emit_error_message(
            "tdp run requires --config",
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
    except OSError as exc:
        emit_operational_error(exc, stream_json=args.stream_json)

    run_id = new_run_id()
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
    try:
        binding, context_spec_digest, context_snapshot_digest, snapshot_diag = (
            build_initial_context_snapshot_binding_with_diagnostics(
                resolved,
                workspace=workspace,
            )
        )
    except ConfigError as exc:
        emit_error_message(
            str(exc),
            exit_code=2,
            stream_json=args.stream_json,
            code="config_error",
        )

    plan = _initial_plan(run_id, resolved, output_goal=output_goal)

    resolved_runs = resolve_runs_dir_from_args(args, resolved_config=resolved)
    if resolved_runs.source == "default":
        emit_error_message(
            "tdp run requires an explicit run store: set runtime.runs_dir in the "
            "config, pass --runs-dir, or export TDP_RUNS_DIR",
            exit_code=2,
            stream_json=args.stream_json,
            code="missing_runs_dir",
        )

    store = FileRunStore(resolved_runs.path)
    try:
        store.root.mkdir(parents=True, exist_ok=True)
        cleanup_staging_dirs(store)
    except OSError as exc:
        emit_operational_error(exc, stream_json=args.stream_json)

    orphans = workspace_has_orphan_agents(store)
    if orphans and not getattr(args, "force", False):
        pairs = ", ".join(f"{run_id}:pid={pid}" for run_id, pid in orphans)
        emit_error_message(
            "refusing to start a new run while orphan agent processes are still "
            f"alive for interrupted runs ({pairs}); retry with --force after cleanup",
            exit_code=1,
            stream_json=args.stream_json,
            code="orphan_agents_present",
        )

    invocation = invocation_options_from_args(
        args,
        resolved_config=resolved,
        resolved_runs=resolved_runs,
    )
    try:
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
            invocation=invocation_to_dict(invocation),
            run_extras={"run_kind": RUN_KIND_PLANNING},
        )
        store.append_event(
            run_id,
            {
                "type": "context_snapshot_collected",
                **snapshot_diag.to_event_fields(),
            },
        )
    except OSError as exc:
        emit_operational_error(exc, stream_json=args.stream_json)

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
    until = invocation.until or "plan"
    observability.emit(
        ConsoleEvent(
            category="run:start",
            message=(
                "Starting run (blocking on provider until the target milestone).\n"
                f"{format_run_startup_diagnostics(diagnostics)}\n"
                f"Run path: {resolved_runs.path / run_id}"
            ),
            fields={"until": until},
            run_id=run_id,
        )
    )

    try:
        try:
            engine = _build_run_engine(
                store,
                resolved_runs,
                run_id=run_id,
                observability=observability,
                notifications=notifications,
            )
            continuation = engine.continue_run(run_id, until=until)
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
        _exit_for_cancel(
            run_id=run_id,
            stream_json=args.stream_json,
            phase=continuation.phase,
            status=continuation.status,
        )

    run_record = _cli_load_run(store, run_id, stream_json=args.stream_json)
    if until and continuation.target_reached and continuation.status == "running":
        notify_run_outcome(
            "target_reached",
            run_id=run_id,
            run=run_record,
            options=notifications.options,
            until=until,
        )
    last_step = continuation.steps[-1].details if continuation.steps else {}
    payload = {
        "ok": continuation.ok,
        "target_reached": continuation.target_reached,
        "run_id": run_id,
        "revision": run_record["revision"],
        "phase": continuation.phase,
        "status": continuation.status,
        "outcome": continuation.outcome,
        "config_contract_digest": run_record["digests"]["config_contract"],
        "config_execution_digest": run_record["digests"]["config_execution"],
        "until": until,
        "steps": [
            {
                "phase": step.phase,
                "ok": step.ok,
                "status": step.status,
                "outcome": step.outcome,
                "details": step.details,
                "reason": step.reason,
            }
            for step in continuation.steps
        ],
        **last_step,
        **(diagnostics or {}),
    }
    if continuation.reason:
        payload["reason"] = continuation.reason

    exit_code = 0 if continuation.ok else 1
    if args.stream_json:
        emit_payload(payload, exit_code=exit_code)

    if continuation.ok:
        message = (
            f"Run {run_id} reached target {until!r} "
            f"(phase={continuation.phase}, status={continuation.status})."
        )
    else:
        message = (
            f"Run {run_id} stopped: {continuation.reason} "
            f"(phase={continuation.phase}, outcome={continuation.outcome})."
        )
    message = (
        f"{message}\n"
        f"{format_run_startup_diagnostics(diagnostics)}\n"
        f"Run path: {resolved_runs.path / run_id}"
    )
    emit_message(message, exit_code=exit_code)


def handle_resume_command(args: Namespace) -> None:
    if not args.run:
        emit_error_message(
            "tdp resume requires --run",
            exit_code=2,
            stream_json=args.stream_json,
            code="missing_run",
        )

    args.run = require_cli_run_id(args.run, stream_json=args.stream_json)
    store, resolved_runs = _open_run_store_for_command(args)
    try:
        reconcile_stale_running_run(store, args.run)
        run = store.load_run(args.run)
        snapshot = load_run_resume_snapshot(store, args.run)
    except (RunNotFoundError, PersistenceError, OSError) as exc:
        emit_run_access_error(exc, stream_json=args.stream_json)

    if snapshot.status == "failed":
        emit_error_message(
            "failed runs cannot be resumed",
            exit_code=1,
            stream_json=args.stream_json,
            code="failed_run_not_resumable",
        )
        return

    phase = snapshot.phase
    if is_terminal_resume_snapshot(snapshot) or snapshot.status == "completed":
        if phase == OUTPUT_VALIDATED and snapshot.status == "completed":
            message = "run already completed with final outcome"
        else:
            message = (
                f"run already terminated "
                f"(status={snapshot.status}, outcome={snapshot.outcome})"
            )
        ok = continuation_ok_from_run(store.load_run(args.run))
        payload = {
            "ok": ok,
            "run_id": args.run,
            "phase": phase,
            "status": snapshot.status,
            "outcome": snapshot.outcome,
            "message": message,
        }
        exit_code = 0 if ok else 1
        if args.stream_json:
            emit_payload(payload, exit_code=exit_code)
        emit_message(
            f"Run {args.run}: {message}",
            exit_code=exit_code,
        )
        return

    until = getattr(args, "until", None)
    check_only = bool(getattr(args, "check", False))
    allow_config_drift = bool(getattr(args, "allow_config_drift", False))
    config_overrides = list(getattr(args, "set", None) or [])
    config_path = Path(args.config).resolve() if getattr(args, "config", None) else None

    try:
        stored = store.load_resolved_config(args.run)
    except (RunNotFoundError, PersistenceError, OSError) as exc:
        emit_run_access_error(exc, stream_json=args.stream_json)

    try:
        candidate = resolve_resume_candidate_for_run(
            stored,
            config_path=config_path,
            overrides=config_overrides,
        )
    except ConfigError as exc:
        emit_error_message(
            str(exc),
            exit_code=2,
            stream_json=args.stream_json,
            code="config_error",
        )
        return
    except OSError as exc:
        emit_operational_error(exc, stream_json=args.stream_json)

    invocation = invocation_options_from_args(
        args,
        resolved_config=candidate,
        resolved_runs=resolved_runs,
    )
    invocation_payload = invocation_to_dict(invocation)

    try:
        resume_plan = prepare_resume(
            store,
            args.run,
            candidate,
            consumed_limits=consumed_limits_from_run(run),
            allow_config_drift=allow_config_drift,
        )
    except PrepareResumeBlockedError as exc:
        emit_error_message(
            exc.message,
            exit_code=1,
            stream_json=args.stream_json,
            code=exc.code,
        )
        return
    except UnsupportedPlanSchemaVersionError as exc:
        emit_error_message(
            str(exc),
            exit_code=1,
            stream_json=args.stream_json,
            code=exc.code,
        )
        return
    except (RunNotFoundError, PersistenceError, OSError) as exc:
        emit_run_access_error(exc, stream_json=args.stream_json)

    plan_summary = build_resume_plan_summary(
        resume_plan,
        run=run,
        snapshot=snapshot,
        stored_config=stored,
        candidate_config=candidate,
        invocation=invocation_payload,
        config_path=str(config_path) if config_path is not None else None,
        config_overrides=config_overrides,
        allow_config_drift=allow_config_drift,
    )

    if resume_plan.already_completed:
        message = resume_plan.message or "run already completed"
        run_record = store.load_run(args.run)
        ok = continuation_ok_from_run(run_record)
        payload = {
            "ok": ok,
            "run_id": args.run,
            "phase": phase,
            "status": snapshot.status,
            "outcome": snapshot.outcome,
            "message": message,
            "already_completed": True,
            "resume_plan": plan_summary,
        }
        if args.stream_json:
            emit_payload(payload, exit_code=0 if ok else 1)
        else:
            emit_message(f"Run {args.run}: {message}")
        if not ok:
            sys.exit(1)
        return

    if check_only:
        plan_summary["check_only"] = True
        if args.stream_json:
            emit_payload(plan_summary)
        else:
            emit_message(format_resume_plan_summary_text(plan_summary))
        return

    plan_summary["check_only"] = False
    if not args.stream_json:
        summary_text = format_resume_plan_summary_text(plan_summary)
        sys.stdout.write(summary_text)
        if not summary_text.endswith("\n"):
            sys.stdout.write("\n")

    try:
        apply_resume_plan_atomically(
            store,
            resume_plan,
            resolved_config=resume_plan.effective_config or candidate,
            invocation=invocation_payload,
        )
    except ApplyResumeError as exc:
        emit_error_message(
            exc.message,
            exit_code=1,
            stream_json=args.stream_json,
            code=exc.code,
        )
        return
    except OSError as exc:
        emit_operational_error(exc, stream_json=args.stream_json)

    observability = build_observability_context(
        options=invocation.observability,
        run_id=args.run,
        run_dir=resolved_runs.path / args.run,
    )
    notifications = NotificationContext(options=invocation.notifications)
    observability.emit(
        ConsoleEvent(
            category="run:resume",
            message=f"Resuming run {args.run}",
            run_id=args.run,
        )
    )
    emit_resume_plan_diagnostics(
        observability,
        message=f"Applying resume plan for {args.run}",
        run_id=args.run,
    )
    try:
        try:
            engine = _build_run_engine(
                store,
                resolved_runs,
                run_id=args.run,
                observability=observability,
                notifications=notifications,
            )
            if until:
                continuation = engine.continue_run(
                    args.run,
                    until=until,
                    session_policy=resume_plan.session_policy,
                )
            else:
                continuation = engine.continue_run(
                    args.run,
                    until="completed",
                    single_step=True,
                    session_policy=resume_plan.session_policy,
                )
        except KeyboardInterrupt:
            _handle_blocking_run_interrupt(
                run_id=args.run,
                store=store,
                observability=observability,
                notifications=notifications,
                stream_json=args.stream_json,
            )
    finally:
        observability.close()

    if continuation.cancelled:
        _exit_for_cancel(
            run_id=args.run,
            stream_json=args.stream_json,
            phase=continuation.phase,
            status=continuation.status,
        )

    run = _cli_load_run(store, args.run, stream_json=args.stream_json)
    if until and continuation.target_reached and continuation.status == "running":
        notify_run_outcome(
            "target_reached",
            run_id=args.run,
            run=run,
            options=notifications.options,
            until=until,
        )
    payload = {
        "ok": continuation.ok,
        "target_reached": continuation.target_reached,
        "run_id": args.run,
        "phase": continuation.phase,
        "status": continuation.status,
        "outcome": continuation.outcome,
        "steps": [
            {
                "phase": step.phase,
                "ok": step.ok,
                "status": step.status,
                "outcome": step.outcome,
                "details": step.details,
                "reason": step.reason,
            }
            for step in continuation.steps
        ],
    }
    if continuation.reason:
        payload["reason"] = continuation.reason
    if until:
        payload["until"] = until
    payload["resume_plan"] = plan_summary

    exit_code = 0 if continuation.ok else 1
    if args.stream_json:
        emit_payload(payload, exit_code=exit_code)

    if continuation.ok:
        message = (
            f"Resumed run {args.run} to phase {run.get('phase')} "
            f"(status={run.get('status')})."
        )
    else:
        message = (
            f"Resumed run {args.run} stopped: {continuation.reason} "
            f"(outcome={continuation.outcome})."
        )
    emit_message(message, exit_code=exit_code)


def handle_status_command(args: Namespace) -> None:
    if not args.run:
        emit_error_message(
            "tdp status requires --run",
            exit_code=2,
            stream_json=args.stream_json,
            code="missing_run",
        )

    args.run = require_cli_run_id(args.run, stream_json=args.stream_json)
    store, resolved_runs = _open_run_store_for_command(args)
    try:
        snapshot = store.load_canonical_snapshot(args.run)
        run = snapshot.run
        plan = snapshot.plan
    except RunNotFoundError as exc:
        if "production.json" in str(exc):
            emit_error_message(
                f"parent execution run {args.run} is missing production.json",
                exit_code=1,
                stream_json=args.stream_json,
                code="corrupt_run",
            )
        emit_run_access_error(exc, stream_json=args.stream_json)
    except (PersistenceError, OSError) as exc:
        emit_run_access_error(exc, stream_json=args.stream_json)
    except UnsupportedPlanSchemaVersionError as exc:
        emit_error_message(
            str(exc),
            exit_code=1,
            stream_json=args.stream_json,
            code=exc.code,
        )

    diagnostics = store_diagnostics_payload(resolved_runs, run_id=args.run, store=store)
    workspace = str(run.get("workspace") or "")
    payload = {
        "ok": True,
        "run": {
            "id": run["id"],
            "revision": run["revision"],
            "schema_version": run.get("schema_version"),
            "kind": resolve_run_kind(run),
            "status": run.get("status"),
            "phase": run.get("phase"),
            "outcome": run.get("outcome"),
            "plan_revision": plan.get("revision"),
            "phase_action_id": run.get("phase_action_id"),
            "digests": dict(run.get("digests") or {}),
            "workspace": workspace,
        },
        **diagnostics,
    }
    package_binding = run.get("package_binding")
    if isinstance(package_binding, dict):
        payload["run"]["package_id"] = package_binding.get("package_id")
        payload["run"]["unit_id"] = package_binding.get("selected_unit_id") or package_binding.get(
            "unit_id"
        )
    if resolve_run_kind(run) == RUN_KIND_PARENT_EXECUTION:
        production = snapshot.production
        completed, total, active_unit = sub_tdp_progress(load_sub_tdp_state(production))
        if total:
            payload["run"]["units_completed"] = completed
            payload["run"]["units_total"] = total
            if active_unit:
                payload["run"]["active_unit"] = active_unit
    stop = run.get("stop")
    if isinstance(stop, dict):
        payload["run"]["stop"] = dict(stop)
    digests = dict(run.get("digests") or {})
    digest_lines: list[str] = []
    for key in (
        "input",
        "output_goal",
        "config_contract",
        "config_execution",
        "plan",
        "context_spec",
        "context_snapshot",
        "output",
    ):
        value = digests.get(key)
        if value:
            digest_lines.append(f"  digests.{key}: {value}")

    if args.stream_json:
        emit_payload(payload)
        return

    lines = [
        f"Run {run['id']}",
        f"  kind: {resolve_run_kind(run)}",
        f"  status: {run.get('status')}",
        f"  phase: {run.get('phase')}",
        f"  outcome: {run.get('outcome')}",
        f"  revision: {run['revision']}",
        f"  schema_version: {run.get('schema_version')}",
        f"  plan_revision: {plan.get('revision')}",
        f"  workspace: {workspace}",
        f"  runs_root: {resolved_runs.path}",
        f"  runs_root_source: {resolved_runs.source}",
        f"  run_path: {resolved_runs.path / args.run}",
    ]
    if resolve_run_kind(run) == RUN_KIND_PARENT_EXECUTION:
        production = snapshot.production
        completed, total, active_unit = sub_tdp_progress(load_sub_tdp_state(production))
        if total:
            lines.append(f"  units: {completed}/{total} completed")
            if active_unit:
                lines.append(f"  active_unit: {active_unit}")
    lines.extend(digest_lines)
    if isinstance(stop, dict):
        lines.append(f"  stop: {stop.get('code')} ({stop.get('category')})")
        if stop.get("message"):
            lines.append(f"  stop_message: {stop.get('message')}")
    emit_message("\n".join(lines))


def handle_inspect_command(args: Namespace) -> None:
    if not args.run:
        emit_error_message(
            "tdp inspect requires --run",
            exit_code=2,
            stream_json=args.stream_json,
            code="missing_run",
        )

    view = args.view or "active"
    if view not in {"active", "audit"}:
        emit_error_message(
            f"unsupported inspect view: {view!r} (supported: active, audit)",
            exit_code=2,
            stream_json=args.stream_json,
            code="invalid_view",
        )

    args.run = require_cli_run_id(args.run, stream_json=args.stream_json)
    store, _resolved_runs = _open_run_store_for_command(args)
    try:
        canonical = _canonical_snapshot_for_cli(
            store, args.run, stream_json=args.stream_json
        )
        plan = Plan.from_dict(canonical.plan)
        config = canonical.resolved_config
    except UnsupportedPlanSchemaVersionError as exc:
        emit_error_message(
            str(exc),
            exit_code=1,
            stream_json=args.stream_json,
            code=exc.code,
        )

    limits = planning_limits_from_config(config)
    if view == "audit":
        snapshot = build_audit_view(plan, limits=limits)
    else:
        snapshot = build_active_view(plan, limits=limits)
    payload = {
        "ok": True,
        **snapshot,
    }
    if args.stream_json:
        emit_payload(payload)
    emit_message(json.dumps(payload, indent=2, sort_keys=True))


def handle_validate_command(args: Namespace) -> None:
    if not args.run:
        emit_error_message(
            "tdp validate requires --run",
            exit_code=2,
            stream_json=args.stream_json,
            code="missing_run",
        )

    args.run = require_cli_run_id(args.run, stream_json=args.stream_json)
    store, _resolved_runs = _open_run_store_for_command(args)
    try:
        canonical = _canonical_snapshot_for_cli(
            store, args.run, stream_json=args.stream_json
        )
        run = canonical.run
        plan = Plan.from_dict(canonical.plan)
        config = canonical.resolved_config
        production = canonical.production
        reviews = canonical.reviews
    except UnsupportedPlanSchemaVersionError as exc:
        emit_error_message(
            str(exc),
            exit_code=1,
            stream_json=args.stream_json,
            code=exc.code,
        )

    limits = planning_limits_from_config(config)
    dispositions = dict(production.get("dispositions") or {})
    phase = str(run.get("phase") or "")
    try:
        mode, review_state, digest_bundle = user_validate_mode_and_context(
            store,
            args.run,
            run,
            plan,
        )
    except (PersistenceError, OSError) as exc:
        emit_run_access_error(exc, stream_json=args.stream_json)

    plan_validation = validate_plan(
        plan,
        limits=limits,
        dispositions=dispositions,
        mode=mode,
        review_state=review_state,
        digests=digest_bundle,
        reviews=reviews,
    )

    output_validation = None
    output_mode = "draft"
    completion_claim = production.get("completion_claim")
    output_revision = int(production.get("output_revision") or 0)
    output_approval = find_whole_output_approval(reviews, output_revision)
    should_validate_output = (
        output_approval is not None
        or phase in {WHOLE_OUTPUT_REVIEW, OUTPUT_VALIDATED}
        or isinstance(completion_claim, dict)
    )
    if should_validate_output:
        output_mode = "approval" if output_approval is not None else "draft"
        output_review_state = None
        output_digest_bundle = None
        if output_approval is not None:
            (
                actual_plan_digest,
                actual_config_contract_digest,
                actual_input_digest,
                actual_output_goal_digest,
                actual_context_spec_digest,
            ) = compute_plan_approval_actual_digests(store, args.run, run, plan)
            output_review_state, output_digest_bundle = build_output_approval_validation_context(
                production=production,
                approval=output_approval,
                actual_output_digest=compute_output_digest(production),
                actual_plan_digest=actual_plan_digest,
                actual_config_contract_digest=actual_config_contract_digest,
                actual_input_digest=actual_input_digest,
                actual_output_goal_digest=actual_output_goal_digest,
                actual_context_spec_digest=actual_context_spec_digest,
                actual_context_snapshot_digest=(run.get("digests") or {}).get(
                    "context_snapshot"
                ),
            )
        output_validation = validate_output(
            plan,
            production,
            review_state=output_review_state,
            digests=output_digest_bundle,
            reviews=reviews,
            mode=output_mode,
        )

    ok = plan_validation.ok and (output_validation.ok if output_validation is not None else True)
    payload = {
        "ok": ok,
        "plan": {
            "mode": mode,
            "revision": plan.revision,
            "issues": [issue.to_dict() for issue in plan_validation.issues],
        },
    }
    if output_validation is not None:
        payload["output"] = {
            "mode": output_mode,
            "output_revision": output_revision,
            "issues": [issue.to_dict() for issue in output_validation.issues],
        }
    exit_code = 0 if ok else 1
    if args.stream_json:
        emit_payload(payload, exit_code=exit_code)

    if ok:
        emit_message(f"Validation passed (plan={mode}, output={output_mode}).", exit_code=0)
        return

    lines = [f"Validation failed (plan={mode}):"]
    for issue in plan_validation.issues:
        path = ".".join(issue.path) if issue.path else "-"
        lines.append(f"  [{issue.severity}] {issue.code} ({path}): {issue.message}")
    if output_validation is not None and not output_validation.ok:
        lines.append(f"Output validation failed ({output_mode}):")
        for issue in output_validation.issues:
            path = ".".join(issue.path) if issue.path else "-"
            lines.append(f"  [{issue.severity}] {issue.code} ({path}): {issue.message}")
    emit_message("\n".join(lines), exit_code=exit_code)


def _initial_plan(run_id: str, config: dict[str, Any], *, output_goal: str) -> Plan:
    run_section = config.get("run") or {}
    input_refs = list(run_section.get("input_refs") or [])
    boundaries = list(run_section.get("boundaries") or [])
    acceptance = list(run_section.get("acceptance") or [])
    root = seed_plan_root_item()
    return Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal=output_goal,
        input_refs=input_refs,
        boundaries=boundaries,
        acceptance=acceptance,
        items={PLAN_ROOT_ITEM_ID: root},
    )


def _require_run_workspace(run: dict[str, Any], *, stream_json: bool = False) -> Path:
    try:
        return run_workspace(run)
    except ValueError as exc:
        emit_error_message(
            str(exc),
            exit_code=1,
            stream_json=stream_json,
            code="missing_workspace",
        )
