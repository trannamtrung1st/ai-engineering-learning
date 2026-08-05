"""tdp execute — parent or unit execution from a prepared package (proposal §6.2–6.3)."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from typing import Any

from core_tools.observability import ConsoleEvent
from core_tools.provider import create_provider as build_provider

from top_down_planning.cli.common import (
    ResolvedRunsDir,
    emit_error_message,
    emit_payload,
    format_run_startup_diagnostics,
    provider_extra_env,
    resolve_runs_dir_from_args,
    run_startup_diagnostics_payload,
)
from top_down_planning.cli.user import (
    _build_run_engine,
    _exit_for_cancel,
    _handle_blocking_run_interrupt,
)
from top_down_planning.config import ConfigError, resolve_config
from top_down_planning.config.resume_policy import RESUME_PRESENTATION_ALLOWLIST
from top_down_planning.domain.sub_tdp_units import SubTdpUnit
from top_down_planning.invocation import invocation_options_from_args, invocation_to_dict
from top_down_planning.notifications import NotificationContext
from top_down_planning.observability import build_observability_context
from top_down_planning.orchestrator.phases import OUTPUT_VALIDATED
from top_down_planning.orchestrator.prepared_run_factory import PreparedRunFactory
from top_down_planning.orchestrator.prepared_unit_executor import PreparedUnitExecutor
from top_down_planning.orchestrator.run_lifecycle_reconciliation import cleanup_staging_dirs
from top_down_planning.package.execution_validation import verify_package_authoritative_inputs
from top_down_planning.package.loader import ExecutionPackageError, ExecutionPackageLoader
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.sub_tdp_state import (
    initial_sub_tdp_state_from_package,
    merge_sub_tdp_state_into_production,
)


def _presentation_sets(set_overrides: list[str] | None) -> list[str]:
    """Keep only presentation/runtime overrides for execute-time --set."""

    allowed_prefixes = tuple(RESUME_PRESENTATION_ALLOWLIST)
    kept: list[str] = []
    for item in set_overrides or []:
        path = item.split("=", 1)[0].strip()
        if path in RESUME_PRESENTATION_ALLOWLIST or any(
            path.startswith(prefix.rstrip(".")) for prefix in allowed_prefixes
        ):
            kept.append(item)
        elif path.startswith("observability.") or path.startswith("notifications."):
            kept.append(item)
        elif path == "runtime.runs_dir":
            kept.append(item)
    return kept


def _resolved_config_for_execute(args: Namespace, package) -> dict[str, Any]:
    """Load semantic config from the package; optional YAML only for presentation."""

    base = dict(package.resolved_config)
    presentation_sets = _presentation_sets(getattr(args, "set", None))
    config_path = getattr(args, "config", None)
    if config_path or presentation_sets:
        # Optional presentation overlay — never required.
        if config_path:
            overlay = resolve_config(
                Path(config_path).resolve(),
                presentation_sets,
            )
        else:
            # Apply presentation --set onto package config without reading cwd YAML.
            from core_tools.config import apply_cli_overrides
            from top_down_planning.config.defaults import ALLOWED_OVERRIDE_PATHS

            overlay = apply_cli_overrides(
                base,
                presentation_sets,
                allowed_paths=ALLOWED_OVERRIDE_PATHS,
            )
        for section in ("observability", "notifications", "runtime"):
            if section in overlay:
                base[section] = overlay[section]
    return base


def handle_execute_command(args: Namespace) -> None:
    manifest_path = Path(args.manifest).resolve()
    package_dir = manifest_path.parent
    try:
        package = ExecutionPackageLoader().load(package_dir)
        verify_package_authoritative_inputs(package)
        resolved = _resolved_config_for_execute(args, package)
    except ExecutionPackageError as exc:
        emit_error_message(
            str(exc),
            exit_code=1,
            stream_json=args.stream_json,
            code=getattr(exc, "code", "package_invalid"),
        )
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
    parent_run = store.load_run(run_id)
    binding = parent_run.get("package_binding") or {}
    persisted_manifest = str(binding.get("manifest_path") or package.manifest_path)
    production = store.load_production(run_id)
    state = initial_sub_tdp_state_from_package(
        package.manifest,
        manifest_path=persisted_manifest,
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


def _child_success(child_run: dict[str, Any]) -> bool:
    return (
        str(child_run.get("status") or "") == "completed"
        and str(child_run.get("phase") or "") == OUTPUT_VALIDATED
        and str(child_run.get("outcome") or "") == "accepted"
    )


def _execute_unit(
    args: Namespace,
    *,
    store: FileRunStore,
    package,
    unit_id: str,
    resolved: dict[str, Any],
    resolved_runs: ResolvedRunsDir,
    invocation_dict: dict[str, Any],
    run_factory: PreparedRunFactory,
    workspace: Path,
) -> None:
    if unit_id not in package.units:
        known = ", ".join(sorted(package.units))
        emit_error_message(
            f"unknown unit: {unit_id!r}; valid units: {known}",
            exit_code=1,
            stream_json=args.stream_json,
            code="unknown_unit",
        )

    executor = PreparedUnitExecutor(run_factory=run_factory)
    invocation_opts = invocation_options_from_args(
        args, resolved_config=resolved, resolved_runs=resolved_runs
    )
    notifications = NotificationContext(options=invocation_opts.notifications)

    try:
        child_run_id = executor.create_or_load_child_run(
            store,
            package,
            unit_id,
            resolved_config=resolved,
            invocation=invocation_dict,
        )
    except PreparedUnitExecutor.DependencyUnmetError as exc:
        emit_error_message(
            str(exc),
            exit_code=1,
            stream_json=args.stream_json,
            code=exc.stop_code,
        )
    except ExecutionPackageError as exc:
        emit_error_message(
            str(exc),
            exit_code=1,
            stream_json=args.stream_json,
            code=getattr(exc, "code", "package_invalid"),
        )

    observability = build_observability_context(
        options=invocation_opts.observability,
        run_id=child_run_id,
        run_dir=resolved_runs.path / child_run_id,
    )
    observability.emit(
        ConsoleEvent(
            category="run:start",
            message=f"Starting unit execution for {unit_id}.",
            fields={"unit_id": unit_id, "package_id": package.manifest.get("package_id")},
            run_id=child_run_id,
        )
    )

    def _provider_factory(config: dict[str, Any], ws: Path) -> Any:
        return build_provider(
            config,
            workspace=ws,
            extra_env=provider_extra_env(
                resolved_runs, run_id=child_run_id, store=store
            ),
            on_provider_event=observability.provider_callback(),
        )

    continuation_ok = False
    cancelled = False
    try:
        child_run = executor.drive_child_run(
            store,
            child_run_id,
            create_provider=_provider_factory,
            workspace=workspace,
            observability=observability,
        )
        continuation_ok = _child_success(child_run)
    except KeyboardInterrupt:
        cancelled = True
        _handle_blocking_run_interrupt(
            run_id=child_run_id,
            store=store,
            observability=observability,
            notifications=notifications,
            stream_json=args.stream_json,
        )
    finally:
        observability.close()

    if cancelled:
        return

    child_run = store.load_run(child_run_id)
    ok = _child_success(child_run)
    payload: dict[str, Any] = {
        "ok": ok,
        "run_id": child_run_id,
        "unit_id": unit_id,
        "phase": child_run.get("phase"),
        "status": child_run.get("status"),
        "outcome": child_run.get("outcome"),
        "package_id": package.manifest.get("package_id"),
    }
    if not ok:
        stop = child_run.get("stop")
        if isinstance(stop, dict):
            payload["stop"] = stop
            payload["reason"] = stop.get("message") or stop.get("code")
        else:
            payload["reason"] = "unit execution did not complete successfully"
    emit_payload(payload, exit_code=0 if ok else 1)


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
        config_path=Path(args.config).resolve()
        if getattr(args, "config", None)
        else package.manifest_path,
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
