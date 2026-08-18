"""tdp execute — parent or unit execution from a prepared package (proposal §6.2–6.3)."""

from __future__ import annotations

import copy
from argparse import Namespace
from pathlib import Path
from typing import Any

from core_tools.observability import ConsoleEvent

from top_down_planning.cli.common import (
    ResolvedRunsDir,
    emit_command_result,
    emit_error_message,
    emit_operational_error,
    format_run_startup_diagnostics,
    resolve_runs_dir_from_args,
    run_startup_diagnostics_payload,
)
from top_down_planning.cli.user import (
    _build_run_engine,
    _exit_for_cancel,
    _handle_blocking_run_interrupt,
)
from top_down_planning.config import (
    ConfigError,
    is_allowed_presentation_override_path,
    validate_presentation_config,
)
from core_tools.config import apply_cli_overrides, collect_leaf_paths, deep_merge, load_yaml_config
from top_down_planning.domain.sub_tdp_units import SubTdpUnit
from top_down_planning.invocation import invocation_options_from_args, invocation_to_dict
from top_down_planning.notifications import NotificationContext
from top_down_planning.observability import build_observability_context
from top_down_planning.orchestrator.phases import OUTPUT_VALIDATED
from top_down_planning.orchestrator.prepared_run_factory import PreparedRunFactory
from top_down_planning.orchestrator.prepared_unit_executor import (
    PreparedUnitExecutor,
    validate_explicit_upstream_bindings,
)
from top_down_planning.orchestrator.run_lifecycle_reconciliation import cleanup_staging_dirs
from top_down_planning.package.execution_validation import (
    verify_package_authoritative_inputs,
    verify_package_immutable_contract,
)
from top_down_planning.package.loader import ExecutionPackageError, ExecutionPackageLoader
from top_down_planning.persistence import FileRunStore, PersistenceError
from top_down_planning.persistence.path_ids import validate_run_id
from top_down_planning.persistence.sub_tdp_state import (
    initial_sub_tdp_state_from_package,
    merge_sub_tdp_state_into_production,
)


def parse_upstream_bindings(raw: list[str] | None) -> dict[str, str]:
    """Parse ``unit_id=run_id`` bindings for ``tdp execute --upstream``."""

    bindings: dict[str, str] = {}
    for item in raw or []:
        text = str(item or "")
        if "=" not in text:
            raise ValueError(
                f"invalid --upstream binding {text!r}; expected unit_id=run_id"
            )
        unit_id, raw_run_id = text.split("=", 1)
        unit_id = unit_id.strip()
        if not unit_id or raw_run_id == "":
            raise ValueError(
                f"invalid --upstream binding {text!r}; expected unit_id=run_id"
            )
        try:
            run_id = validate_run_id(raw_run_id)
        except PersistenceError as exc:
            raise ValueError(str(exc)) from exc
        if unit_id in bindings:
            raise ValueError(f"duplicate --upstream unit_id {unit_id!r}")
        bindings[unit_id] = run_id
    return bindings


def parse_baseline_run_ids(raw: list[str] | None) -> list[str]:
    """Parse accepted run ids for ``tdp execute --baseline`` workspace lineage."""

    run_ids: list[str] = []
    seen: set[str] = set()
    for item in raw or []:
        run_id = str(item or "")
        if run_id == "":
            raise ValueError("invalid --baseline value; expected a non-empty run id")
        try:
            run_id = validate_run_id(run_id)
        except PersistenceError as exc:
            raise ValueError(str(exc)) from exc
        if run_id in seen:
            raise ValueError(f"duplicate --baseline run id {run_id!r}")
        seen.add(run_id)
        run_ids.append(run_id)
    return run_ids


def _is_execute_presentation_path(path: str) -> bool:
    return is_allowed_presentation_override_path(path)


def _validate_execute_presentation_sets(set_overrides: list[str] | None) -> list[str]:
    """Reject semantic overrides on execute; package config is authoritative."""

    kept: list[str] = []
    for item in set_overrides or []:
        path = item.split("=", 1)[0].strip()
        if _is_execute_presentation_path(path):
            kept.append(item)
            continue
        raise ConfigError(
            f"execute --set path {path!r} is not allowed; "
            "semantic config is fixed by the execution package"
        )
    return kept


def _presentation_sets(set_overrides: list[str] | None) -> list[str]:
    """Keep only presentation/runtime overrides for execute-time --set."""

    return _validate_execute_presentation_sets(set_overrides)


def _load_execute_presentation_overlay(config_path: Path) -> dict[str, Any]:
    overlay = load_yaml_config(config_path)
    for path in sorted(collect_leaf_paths(overlay)):
        if not _is_execute_presentation_path(path):
            raise ConfigError(
                f"execute --config path {path!r} is not allowed; "
                "semantic config is fixed by the execution package",
                path=path,
            )
    return overlay


def _resolved_config_for_execute(args: Namespace, package) -> dict[str, Any]:
    """Load semantic config from the package; optional YAML only for presentation."""

    from top_down_planning.config.defaults import ALLOWED_OVERRIDE_PATHS

    base = copy.deepcopy(dict(package.resolved_config))
    config_path = getattr(args, "config", None)
    if config_path:
        overlay = _load_execute_presentation_overlay(Path(config_path).resolve())
        base = deep_merge(base, overlay)
    presentation_sets = _presentation_sets(getattr(args, "set", None))
    if presentation_sets:
        base = apply_cli_overrides(
            base,
            presentation_sets,
            allowed_paths=ALLOWED_OVERRIDE_PATHS,
        )
    validate_presentation_config(base)
    return base


def handle_execute_command(args: Namespace) -> None:
    manifest_path = Path(args.manifest).resolve()
    unit_id = str(getattr(args, "unit", "") or "").strip() or None
    try:
        loader = ExecutionPackageLoader()
        package = loader.load_from_manifest(manifest_path)
        if unit_id:
            verify_package_immutable_contract(package)
        else:
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
    try:
        store.root.mkdir(parents=True, exist_ok=True)
        cleanup_staging_dirs(store)
    except OSError as exc:
        emit_operational_error(exc, stream_json=args.stream_json)

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
    parent_only = bool(getattr(args, "parent_only", False))
    upstream_raw = list(getattr(args, "upstream", None) or [])
    if upstream_raw and not unit_id:
        emit_error_message(
            "--upstream requires --unit",
            exit_code=2,
            stream_json=args.stream_json,
            code="sub_tdp_upstream_invalid",
        )
    baseline_raw = list(getattr(args, "baseline", None) or [])
    if baseline_raw and not unit_id:
        emit_error_message(
            "--baseline requires --unit",
            exit_code=2,
            stream_json=args.stream_json,
            code="sub_tdp_baseline_invalid",
        )
    if unit_id and parent_only:
        emit_error_message(
            "--parent-only cannot be combined with --unit",
            exit_code=2,
            stream_json=args.stream_json,
            code="invalid_execute_options",
        )
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
        package_units=package.units,
    )
    merged = merge_sub_tdp_state_into_production(production, state)
    expected_revision = int(production["revision"])
    merged["revision"] = expected_revision + 1
    store.save_production(run_id, merged, expected_revision)

    if parent_only:
        # Enter sub_tdps without driving children so attach can bind independently
        # executed units. Pause the parent to prevent concurrent orchestration writes.
        from top_down_planning.domain.run_lifecycle import StopRecord
        from top_down_planning.orchestrator.phases import SUB_TDPS
        from top_down_planning.orchestrator.run_transitions import pause_run

        run = store.load_run(run_id)
        expected_run = int(run["revision"])
        run = dict(run)
        run["revision"] = expected_run + 1
        run["phase"] = SUB_TDPS
        store.save_run(run_id, run, expected_run)
        store.append_event(
            run_id,
            {
                "type": "sub_tdps_phase_entered",
                "run_id": run_id,
                "parent_only": True,
            },
        )
        pause_run(
            store,
            run_id,
            stop=StopRecord(
                code="sub_tdps_awaiting_children",
                category="operational",
                phase=SUB_TDPS,
                message="parent-only: waiting for independently executed children",
            ),
            revoke_phase=SUB_TDPS,
            event_type="sub_tdps_awaiting_children",
        )
        paused = store.load_run(run_id)
        payload = {
            "ok": True,
            "run_id": run_id,
            "phase": SUB_TDPS,
            "status": paused.get("status"),
            "parent_only": True,
            "package_id": package.manifest.get("package_id"),
            "runs_dir": str(resolved_runs.path),
        }
        emit_command_result(
            payload,
            human_message=(
                f"Created parent-only run {run_id} "
                f"(phase={SUB_TDPS}, status={paused.get('status')})."
            ),
            stream_json=args.stream_json,
        )
        return

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

    upstream_raw = list(getattr(args, "upstream", None) or [])
    upstream_bindings: dict[str, str] = {}
    baseline_run_ids: list[str] = []
    try:
        upstream_bindings = parse_upstream_bindings(upstream_raw)
    except ValueError as exc:
        emit_error_message(
            str(exc),
            exit_code=2,
            stream_json=args.stream_json,
            code="sub_tdp_upstream_invalid",
        )
    try:
        if upstream_bindings:
            validate_explicit_upstream_bindings(package, unit_id, upstream_bindings)
    except ExecutionPackageError as exc:
        emit_error_message(
            str(exc),
            exit_code=1,
            stream_json=args.stream_json,
            code=getattr(exc, "code", "sub_tdp_upstream_invalid"),
        )
    try:
        baseline_run_ids = parse_baseline_run_ids(
            list(getattr(args, "baseline", None) or [])
        )
    except ValueError as exc:
        emit_error_message(
            str(exc),
            exit_code=2,
            stream_json=args.stream_json,
            code="sub_tdp_baseline_invalid",
        )
    try:
        child_run_id = executor.create_or_load_child_run(
            store,
            package,
            unit_id,
            resolved_config=resolved,
            invocation=invocation_dict,
            explicit_upstream=upstream_bindings if upstream_bindings else None,
            explicit_upstream_only=bool(upstream_bindings),
            explicit_baseline_run_ids=baseline_run_ids or None,
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

    from top_down_planning.orchestrator.execution_runtime import build_execution_runtime

    runtime = build_execution_runtime(
        store=store,
        run_id=child_run_id,
        resolved_runs=resolved_runs,
        observability=observability,
        workspace=workspace,
    )
    _provider_factory = runtime.create_provider

    continuation_ok = False
    cancelled = False
    try:
        child_result = executor.drive_child_run(
            store,
            child_run_id,
            create_provider=_provider_factory,
            workspace=workspace,
            observability=observability,
        )
        cancelled = child_result.cancelled
        continuation_ok = child_result.ok and _child_success(child_result.run)
        if cancelled:
            _exit_for_cancel(
                run_id=child_run_id,
                store=store,
                stream_json=args.stream_json,
            )
            return
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
    emit_command_result(
        payload,
        human_message=(
            f"Executed unit {unit_id} as run {child_run_id} "
            f"(status={child_run.get('status')}, outcome={child_run.get('outcome')})."
        ),
        stream_json=args.stream_json,
        exit_code=0 if ok else 1,
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
    payload = {
        "ok": continuation.ok,
        "run_id": run_id,
        "phase": continuation.phase,
        "status": continuation.status,
        "package_id": package.manifest.get("package_id"),
        "run_kind": run_record.get("run_kind"),
    }
    emit_command_result(
        payload,
        human_message=(
            f"Executed package {package.manifest.get('package_id')} as run {run_id} "
            f"(phase={continuation.phase}, status={continuation.status})."
        ),
        stream_json=args.stream_json,
        exit_code=0 if continuation.ok else 1,
    )


__all__ = [
    "handle_execute_command",
    "parse_baseline_run_ids",
    "parse_upstream_bindings",
]
