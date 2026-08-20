"""tdp prepare — planning, review, and execution-package materialization (proposal §6.1)."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from typing import Any

from top_down_planning.cli.common import (
    emit_command_result,
    emit_error_message,
    emit_operational_error,
    emit_run_access_error,
    emit_create_run_error,
    emit_continue_run_error,
    emit_error_with_fields,
    locator_fields,
    recovery_fields,
    format_run_startup_diagnostics,
    provider_extra_env,
    require_cli_run_id,
    resolve_runs_dir_from_args,
    run_startup_diagnostics_payload,
)
from top_down_planning.cli.user import (
    _build_run_engine,
    _cli_load_run,
    _create_provider_for_run,
    _exit_for_cancel,
    _exit_for_command_interrupt,
    _handle_blocking_run_interrupt,
    _initial_plan,
)
from top_down_planning.config import (
    ConfigError,
    build_initial_context_snapshot_binding_with_diagnostics,
    compute_input_digest,
    compute_output_goal_digest_from_text,
    is_allowed_presentation_override_path,
    resolve_config,
    resolve_output_goal_text,
    resolve_workspace,
)
from top_down_planning.domain.run_kind import RUN_KIND_PLANNING, resolve_run_kind
from top_down_planning.domain.run_ownership import RunOwnershipError
from top_down_planning.invocation import invocation_options_from_args, invocation_to_dict
from top_down_planning.notifications import NotificationContext, wrap_run_store
from top_down_planning.observability import ObservabilityContext, build_observability_context
from top_down_planning.orchestrator.run_lifecycle_reconciliation import cleanup_staging_dirs
from top_down_planning.orchestrator.phases import PLAN_VALIDATED
from top_down_planning.package.builder import ExecutionPackageBuilder
from top_down_planning.persistence import FileRunStore, PersistenceError, RunPublishedInterrupt
from top_down_planning.persistence.path_ids import new_run_id
from core_tools.observability import ConsoleEvent


def handle_prepare_command(args: Namespace) -> None:
    planning_run = str(getattr(args, "planning_run", "") or "").strip()
    if not args.config and not planning_run:
        emit_error_message(
            "tdp prepare requires --config, or --planning-run with --runs-dir",
            exit_code=2,
            stream_json=args.stream_json,
            code="missing_config",
        )
    if planning_run and not args.config and list(getattr(args, "set", None) or []):
        emit_error_message(
            "--planning-run without --config rejects --set",
            exit_code=2,
            stream_json=args.stream_json,
            code="config_error",
        )

    resolved: dict[str, Any] | None = None
    config_path: Path | None = None
    if args.config:
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

    output_dir = Path(args.output).resolve() if args.output else Path(".tdp/execution").resolve()
    cwd = Path.cwd().resolve()
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
    try:
        store.root.mkdir(parents=True, exist_ok=True)
        cleanup_staging_dirs(store)
    except OSError as exc:
        emit_operational_error(exc, stream_json=args.stream_json)

    if planning_run:
        if args.config:
            for raw in list(getattr(args, "set", None) or []):
                path = str(raw).split("=", 1)[0].strip()
                if path and not is_allowed_presentation_override_path(path):
                    emit_error_message(
                        f"--planning-run rejects semantic override {path}",
                        exit_code=2,
                        stream_json=args.stream_json,
                        code="config_error",
                    )
        run_id = require_cli_run_id(planning_run, stream_json=args.stream_json)
        try:
            snapshot = store.load_canonical_snapshot(run_id)
        except (PersistenceError, OSError) as exc:
            emit_run_access_error(
                exc,
                stream_json=args.stream_json,
                extra={"planning_run_id": run_id, "run_id": run_id},
            )
        except KeyboardInterrupt:
            emit_error_with_fields(
                "cancelled by user",
                exit_code=130,
                stream_json=args.stream_json,
                code="user_cancelled",
                extra={"run_id": run_id, "planning_run_id": run_id},
            )
        if resolve_run_kind(snapshot.run) != RUN_KIND_PLANNING:
            emit_error_message(
                f"run {run_id} is not a planning run",
                exit_code=1,
                stream_json=args.stream_json,
                code="invalid_planning_run",
            )
        if str(snapshot.run.get("phase") or "") != PLAN_VALIDATED:
            emit_error_message(
                f"planning run {run_id} is not at plan_validated",
                exit_code=1,
                stream_json=args.stream_json,
                code="invalid_planning_run",
            )
        _materialize_prepare_package(
            args,
            store=store,
            run_id=run_id,
            output_dir=output_dir,
            snapshot=snapshot,
            resolved_runs=resolved_runs,
        )
        return

    if resolved is None or config_path is None:
        emit_error_message(
            "tdp prepare requires --config",
            exit_code=2,
            stream_json=args.stream_json,
            code="missing_config",
        )

    workspace = resolve_workspace(resolved, cwd=cwd)
    try:
        output_goal = resolve_output_goal_text(resolved, base_dir=workspace)
        input_digest = compute_input_digest(resolved, base_dir=workspace)
        output_goal_digest = compute_output_goal_digest_from_text(output_goal)
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
    except OSError as exc:
        emit_operational_error(exc, stream_json=args.stream_json)

    invocation = invocation_options_from_args(
        args,
        resolved_config=resolved,
        resolved_runs=resolved_runs,
    )
    invocation_dict = invocation_to_dict(invocation)
    invocation_dict["command"] = "prepare"
    invocation_dict["until"] = "validated"

    run_id = new_run_id()
    plan = _initial_plan(run_id, resolved, output_goal=output_goal)
    try:
        created = store.create_run(
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
            initial_events=[
                {
                    "type": "context_snapshot_collected",
                    **snapshot_diag.to_event_fields(),
                }
            ],
        )
        run_id = str(created.get("id") or run_id)
    except PersistenceError as exc:
        emit_create_run_error(exc, stream_json=args.stream_json)
    except OSError as exc:
        emit_operational_error(exc, stream_json=args.stream_json)
    except RunPublishedInterrupt as exc:
        _exit_for_command_interrupt(
            run_id=exc.run_id,
            stream_json=args.stream_json,
            run=exc.run,
        )
    except KeyboardInterrupt:
        emit_error_with_fields(
            "cancelled by user",
            exit_code=130,
            stream_json=args.stream_json,
            code="user_cancelled",
        )

    try:
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
    except OSError as exc:
        emit_run_access_error(
            exc,
            stream_json=args.stream_json,
            extra={
                "run_id": run_id,
                "planning_run_id": run_id,
                **locator_fields(resolved_runs, args),
            },
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
    except (PersistenceError, OSError, RunOwnershipError) as exc:
        emit_continue_run_error(
            exc,
            stream_json=args.stream_json,
            extra={
                "planning_run_id": run_id,
                "run_id": run_id,
                **locator_fields(resolved_runs, args),
            },
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

    try:
        snapshot = store.load_canonical_snapshot(run_id)
    except (PersistenceError, OSError) as exc:
        emit_run_access_error(
            exc,
            stream_json=args.stream_json,
            extra={
                "planning_run_id": run_id,
                "run_id": run_id,
                **locator_fields(resolved_runs, args),
            },
        )
    if str(snapshot.run.get("phase") or "") != PLAN_VALIDATED:
        emit_error_with_fields(
            continuation.reason or "prepare did not reach plan_validated",
            exit_code=1,
            stream_json=args.stream_json,
            code="prepare_incomplete",
            extra={
                "run_id": run_id,
                "planning_run_id": run_id,
                "phase": str(snapshot.run.get("phase") or ""),
                **locator_fields(resolved_runs, args),
                "recovery": recovery_fields(
                    code="prepare_incomplete",
                    run_id=run_id,
                    planning_run_id=run_id,
                    phase=str(snapshot.run.get("phase") or ""),
                    runs_dir=str(resolved_runs.path),
                ),
            },
        )

    _materialize_prepare_package(
        args,
        store=store,
        run_id=run_id,
        output_dir=output_dir,
        snapshot=snapshot,
        resolved_runs=resolved_runs,
    )


def _materialize_prepare_package(
    args: Namespace,
    *,
    store: FileRunStore,
    run_id: str,
    output_dir: Path,
    snapshot: Any | None = None,
    resolved_runs: Any | None = None,
) -> None:
    locators = locator_fields(resolved_runs, args)
    try:
        built = ExecutionPackageBuilder().build_from_planning_run(
            store,
            run_id,
            output_dir=output_dir,
            replace=getattr(args, "replace", False),
            snapshot=snapshot,
        )
    except ValueError as exc:
        emit_error_with_fields(
            str(exc),
            code="package_build_failed",
            stream_json=args.stream_json,
            extra={
                "planning_run_id": run_id,
                "run_id": run_id,
                **locators,
                "recovery": recovery_fields(
                    code="package_build_failed",
                    run_id=run_id,
                    planning_run_id=run_id,
                    phase=PLAN_VALIDATED,
                    runs_dir=locators.get("runs_dir"),
                    output=locators.get("output"),
                    replace=bool(locators.get("replace")),
                ),
            },
        )
    except PersistenceError as exc:
        emit_run_access_error(
            exc,
            stream_json=args.stream_json,
            extra={"planning_run_id": run_id, "run_id": run_id, **locators},
        )
    except OSError as exc:
        emit_run_access_error(
            exc,
            stream_json=args.stream_json,
            extra={
                "planning_run_id": run_id,
                "run_id": run_id,
                "phase": PLAN_VALIDATED,
                **locators,
            },
        )
    except KeyboardInterrupt:
        emit_error_with_fields(
            "cancelled by user",
            exit_code=130,
            stream_json=args.stream_json,
            code="user_cancelled",
            extra={"run_id": run_id, "planning_run_id": run_id, **locators},
        )

    planning = built.manifest.get("planning_run") or {}
    payload: dict[str, Any] = {
        "ok": True,
        "planning_run_id": run_id,
        "package_id": built.package_id,
        "manifest": str(built.manifest_path),
        "plan_revision": planning.get("approved_plan_revision"),
        "plan_digest": planning.get("approved_plan_digest"),
    }
    warning = getattr(built, "cleanup_warning", None)
    if warning:
        payload["cleanup_warning"] = warning
    human_message = (
        f"Prepared package {built.package_id} from planning run {run_id} "
        f"(manifest: {built.manifest_path})."
    )
    if warning:
        human_message = f"{human_message}\nWarning: {warning}"
    emit_command_result(
        payload,
        human_message=human_message,
        stream_json=args.stream_json,
    )


__all__ = ["handle_prepare_command"]
