"""tdp execute — parent or unit execution from a prepared package (proposal §6.2–6.3)."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from typing import Any

from top_down_planning.cli.common import (
    emit_error_message,
    emit_payload,
    format_run_startup_diagnostics,
    open_run_store,
    resolve_runs_dir_from_args,
    run_startup_diagnostics_payload,
)
from top_down_planning.cli.user import (
    _build_run_engine,
    _exit_for_cancel,
    _handle_blocking_run_interrupt,
)
from top_down_planning.config import ConfigError, resolve_config, resolve_workspace
from top_down_planning.invocation import invocation_options_from_args, invocation_to_dict
from top_down_planning.notifications import NotificationContext
from top_down_planning.observability import build_observability_context
from top_down_planning.orchestrator.run_lifecycle_reconciliation import cleanup_staging_dirs
from top_down_planning.orchestrator.prepared_run_factory import PreparedRunFactory
from top_down_planning.orchestrator.prepared_unit_executor import PreparedUnitExecutor
from top_down_planning.package.loader import ExecutionPackageError, ExecutionPackageLoader
from top_down_planning.domain.sub_tdp_units import SubTdpUnit
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.sub_tdp_state import (
    initial_sub_tdp_state_from_package,
    merge_sub_tdp_state_into_production,
)
from core_tools.observability import ConsoleEvent
from core_tools.provider import create_provider as build_provider
from top_down_planning.cli.common import provider_extra_env


def handle_execute_command(args: Namespace) -> None:
    manifest_path = Path(args.manifest).resolve()
    package_dir = manifest_path.parent
    try:
        package = ExecutionPackageLoader().load(package_dir)
    except ExecutionPackageError as exc:
        emit_error_message(
            str(exc),
            exit_code=1,
            stream_json=args.stream_json,
            code="package_invalid",
        )

    cwd = Path.cwd().resolve()
    config_path = Path(args.config).resolve() if getattr(args, "config", None) else cwd / "config.yaml"
    try:
        resolved = resolve_config(config_path, getattr(args, "set", []) or [])
    except ConfigError as exc:
        emit_error_message(
            str(exc),
            exit_code=2,
            stream_json=args.stream_json,
            code="config_error",
        )

    resolved_runs = resolve_runs_dir_from_args(args, resolved_config=resolved)
    if resolved_runs.source == "default":
        emit_error_message(
            "tdp execute requires an explicit run store",
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
    invocation_dict["command"] = "execute"
    invocation_dict["until"] = invocation.until or "completed"
    invocation_dict["manifest"] = str(manifest_path)

    unit_id = str(getattr(args, "unit", "") or "").strip() or None
    workspace = package.workspace_path
    run_factory = PreparedRunFactory()

    if unit_id:
        _execute_unit(
            args,
            store=store,
            package=package,
            unit_id=unit_id,
            resolved=resolved,
            resolved_runs=resolved_runs,
            invocation_dict=invocation_dict,
            run_factory=run_factory,
            workspace=workspace,
        )
        return

    run_id = run_factory.create_parent_run(
        store,
        package,
        resolved_config=resolved,
        invocation=invocation_dict,
    )
    production = store.load_production(run_id)
    state = initial_sub_tdp_state_from_package(
        package.manifest,
        manifest_path=str(package.manifest_path),
        units=[
            SubTdpUnit(
                plan_item_id=unit.unit_id,
                title=unit.title,
                outcome="",
                directory=unit.plan_file.parent.name,
                ordinal=unit.ordinal,
            )
            for unit in sorted(package.units.values(), key=lambda item: item.ordinal)
        ],
    )
    merged = merge_sub_tdp_state_into_production(production, state)
    expected_revision = int(production["revision"])
    merged["revision"] = expected_revision + 1
    store.save_production(run_id, merged, expected_revision)

    _drive_execution_run(
        args,
        store=store,
        run_id=run_id,
        resolved=resolved,
        resolved_runs=resolved_runs,
        invocation=invocation,
        package=package,
    )


def _execute_unit(
    *,
    args: Namespace,
    store: FileRunStore,
    package,
    unit_id: str,
    resolved: dict[str, Any],
    resolved_runs,
    invocation_dict: dict[str, Any],
    run_factory: PreparedRunFactory,
    workspace: Path,
) -> None:
    unit = package.units[unit_id]
    child_store = store
    executor = PreparedUnitExecutor(run_factory=run_factory)
    observability = build_observability_context(
        options=invocation_options_from_args(
            args, resolved_config=resolved, resolved_runs=resolved_runs
        ).observability,
        run_id="pending",
        run_dir=resolved_runs.path,
    )

    def _provider_factory(config: dict[str, Any], ws: Path) -> Any:
        return build_provider(
            config,
            workspace=ws,
            extra_env=provider_extra_env(resolved_runs, run_id="", store=store),
            on_provider_event=observability.provider_callback(),
        )

    try:
        child_run = executor.execute_unit(
            child_store,
            package,
            unit_id,
            resolved_config=resolved,
            invocation=invocation_dict,
            create_provider=_provider_factory,
            workspace=workspace,
        )
    except PreparedUnitExecutor.DependencyUnmetError as exc:
        emit_error_message(
            str(exc),
            exit_code=1,
            stream_json=args.stream_json,
            code=exc.stop_code,
        )
    finally:
        observability.close()

    emit_payload(
        {
            "ok": True,
            "run_id": child_run.get("id"),
            "unit_id": unit_id,
            "phase": child_run.get("phase"),
            "status": child_run.get("status"),
            "package_id": package.manifest.get("package_id"),
        }
    )


def _drive_execution_run(
    args: Namespace,
    *,
    store: FileRunStore,
    run_id: str,
    resolved: dict[str, Any],
    resolved_runs,
    invocation,
    package,
) -> None:
    diagnostics = run_startup_diagnostics_payload(
        cwd=Path.cwd().resolve(),
        config_path=Path(args.config).resolve() if getattr(args, "config", None) else None,
        workspace=package.workspace_path,
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
                "Starting parent execution from prepared package.\n"
                f"{format_run_startup_diagnostics(diagnostics)}"
            ),
            fields={"until": invocation.until or "completed"},
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
        continuation = engine.continue_run(run_id, until=invocation.until or "completed")
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
    emit_payload(
        {
            "ok": continuation.ok,
            "run_id": run_id,
            "phase": continuation.phase,
            "status": continuation.status,
            "package_id": package.manifest.get("package_id"),
            "run_kind": run_record.get("run_kind"),
        },
        exit_code=0 if continuation.ok else 1,
    )


__all__ = ["handle_execute_command"]
