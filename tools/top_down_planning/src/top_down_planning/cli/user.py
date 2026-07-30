"""User-facing orchestration CLI commands (proposal §20)."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from typing import Any

from top_down_planning.agent_tool.config import planning_limits_from_config
from top_down_planning.agent_tool.views import build_tree_view
from top_down_planning.cli.common import (
    RunsStoreNotFoundError,
    emit_error_message,
    emit_message,
    emit_payload,
    format_run_startup_diagnostics,
    open_run_store,
    provider_extra_env,
    resolve_runs_dir_from_args,
    run_startup_diagnostics_payload,
    store_diagnostics_payload,
)
from top_down_planning.persistence.path_ids import new_run_id
from top_down_planning.config import (
    ConfigError,
    compute_context_digest_from_config,
    compute_input_digest,
    compute_output_goal_digest,
    resolve_config,
    resolve_output_goal_text,
    resolve_workspace,
)
from top_down_planning.domain.models import Plan, PlanItem
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
from top_down_planning.orchestrator import (
    ResumeError,
    RunEngine,
    validate_resume_preconditions,
)
from top_down_planning.orchestrator.phases import (
    OUTPUT_VALIDATED,
    WHOLE_OUTPUT_REVIEW,
)
from top_down_planning.workspace import run_workspace
from top_down_planning.invocation import (
    invocation_options_from_args,
    invocation_to_dict,
)
from top_down_planning.observability import (
    ObservabilityContext,
    build_observability_context,
    cancel_console_event,
    wrap_store_with_observability,
)
from top_down_planning.persistence import FileRunStore, RunNotFoundError
from top_down_planning.persistence.digests import compute_output_digest
from core_tools.observability import ConsoleEvent
from core_tools.provider import create_provider

_CANCEL_EXIT_CODE = 130


def _exit_for_cancel(
    *,
    run_id: str,
    store: FileRunStore,
    stream_json: bool,
) -> None:
    """Exit with SIGINT convention (130) after cancellation was logged."""

    run = store.load_run(run_id)
    if stream_json:
        emit_payload(
            {
                "ok": False,
                "cancelled": True,
                "run_id": run_id,
                "phase": run.get("phase"),
                "status": run.get("status"),
                "reason": "cancelled by user",
            },
            exit_code=_CANCEL_EXIT_CODE,
        )
    raise SystemExit(_CANCEL_EXIT_CODE) from None


def _handle_blocking_run_interrupt(
    *,
    run_id: str,
    store: FileRunStore,
    observability: ObservabilityContext,
    stream_json: bool,
) -> None:
    """Emit cancel observability and exit when Ctrl+C escapes the engine loop."""

    run = store.load_run(run_id)
    observability.emit(
        cancel_console_event(
            run_id=run_id,
            phase=str(run.get("phase") or "unknown"),
        )
    )
    _exit_for_cancel(run_id=run_id, store=store, stream_json=stream_json)


def _open_run_store_for_command(
    args: Namespace,
    *,
    resolved_config: dict[str, Any] | None = None,
    create: bool = False,
) -> tuple[FileRunStore, Any]:
    try:
        return open_run_store(args, resolved_config=resolved_config, create=create)
    except ConfigError as exc:
        emit_error_message(
            str(exc),
            exit_code=2,
            stream_json=args.stream_json,
            code="config_error",
        )
    except RunsStoreNotFoundError as exc:
        emit_error_message(
            str(exc),
            exit_code=1,
            stream_json=args.stream_json,
            code="runs_store_not_found",
        )


def _create_provider_for_run(
    config: dict[str, Any],
    *,
    workspace: Path,
    resolved_runs: Any,
    on_provider_event: Any | None = None,
) -> Any:
    return create_provider(
        config,
        workspace=workspace,
        extra_env=provider_extra_env(resolved_runs),
        on_provider_event=on_provider_event,
    )


def _build_run_engine(
    store: FileRunStore,
    resolved_runs: Any,
    *,
    observability: ObservabilityContext,
) -> RunEngine:
    def create_provider(config: dict[str, Any], workspace: Path) -> Any:
        return _create_provider_for_run(
            config,
            workspace=workspace,
            resolved_runs=resolved_runs,
            on_provider_event=observability.provider_callback(),
        )

    return RunEngine(
        wrap_store_with_observability(store, observability),
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
    context_digest = compute_context_digest_from_config(resolved, workspace=workspace)
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
    store.root.mkdir(parents=True, exist_ok=True)
    invocation = invocation_options_from_args(
        args,
        resolved_config=resolved,
        resolved_runs=resolved_runs,
    )
    store.create_run(
        run_id,
        plan=plan,
        resolved_config=resolved,
        input_digest=input_digest,
        output_goal_digest=output_goal_digest,
        context_digest=context_digest,
        workspace=str(workspace),
        invocation=invocation_to_dict(invocation),
    )

    diagnostics = run_startup_diagnostics_payload(
        cwd=cwd,
        config_path=config_path,
        workspace=workspace,
        resolved_runs=resolved_runs,
        run_id=run_id,
    )
    observability = build_observability_context(
        options=invocation.observability,
        run_id=run_id,
        run_dir=resolved_runs.path / run_id,
    )
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
            engine = _build_run_engine(store, resolved_runs, observability=observability)
            continuation = engine.continue_run(run_id, until=until)
        except KeyboardInterrupt:
            _handle_blocking_run_interrupt(
                run_id=run_id,
                store=store,
                observability=observability,
                stream_json=args.stream_json,
            )
    finally:
        observability.close()

    if continuation.cancelled:
        _exit_for_cancel(run_id=run_id, store=store, stream_json=args.stream_json)

    run_record = store.load_run(run_id)
    last_step = continuation.steps[-1].details if continuation.steps else {}
    payload = {
        "ok": continuation.ok,
        "run_id": run_id,
        "revision": run_record["revision"],
        "phase": continuation.phase,
        "status": continuation.status,
        "outcome": continuation.outcome,
        "config_digest": run_record["digests"]["config"],
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

    store, resolved_runs = _open_run_store_for_command(args)
    try:
        run = store.load_run(args.run)
    except RunNotFoundError as exc:
        emit_error_message(
            str(exc),
            exit_code=1,
            stream_json=args.stream_json,
            code="run_not_found",
        )

    try:
        preconditions = validate_resume_preconditions(store, args.run)
    except ResumeError as exc:
        emit_error_message(
            exc.message,
            exit_code=1,
            stream_json=args.stream_json,
            code=exc.code,
        )

    phase = preconditions.phase
    if phase == OUTPUT_VALIDATED or preconditions.status == "completed":
        if phase == OUTPUT_VALIDATED and preconditions.status == "completed":
            message = "run already completed with final outcome"
        else:
            message = (
                f"run already terminated "
                f"(status={preconditions.status}, outcome={preconditions.outcome})"
            )
        payload = {
            "ok": True,
            "run_id": args.run,
            "phase": phase,
            "status": preconditions.status,
            "outcome": preconditions.outcome,
            "message": message,
        }
        if args.stream_json:
            emit_payload(payload)
        emit_message(
            f"Run {args.run}: {message}",
        )
        return

    until = getattr(args, "until", None)
    try:
        resolved = store.load_resolved_config(args.run)
    except RunNotFoundError:
        resolved = None
    invocation = invocation_options_from_args(
        args,
        resolved_config=resolved,
        resolved_runs=resolved_runs,
    )
    store.save_invocation(args.run, invocation_to_dict(invocation))
    observability = build_observability_context(
        options=invocation.observability,
        run_id=args.run,
        run_dir=resolved_runs.path / args.run,
    )
    observability.emit(
        ConsoleEvent(
            category="run:resume",
            message=f"Resuming run {args.run}",
            run_id=args.run,
        )
    )
    try:
        try:
            engine = _build_run_engine(store, resolved_runs, observability=observability)
            if until:
                continuation = engine.continue_run(args.run, until=until)
            else:
                continuation = engine.continue_run(
                    args.run,
                    until="completed",
                    single_step=True,
                )
        except KeyboardInterrupt:
            _handle_blocking_run_interrupt(
                run_id=args.run,
                store=store,
                observability=observability,
                stream_json=args.stream_json,
            )
    finally:
        observability.close()

    if continuation.cancelled:
        _exit_for_cancel(run_id=args.run, store=store, stream_json=args.stream_json)

    run = store.load_run(args.run)
    payload = {
        "ok": continuation.ok,
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

    store, resolved_runs = _open_run_store_for_command(args)
    try:
        run = store.load_run(args.run)
        plan = store.load_plan(args.run)
    except RunNotFoundError as exc:
        emit_error_message(
            str(exc),
            exit_code=1,
            stream_json=args.stream_json,
            code="run_not_found",
        )

    diagnostics = store_diagnostics_payload(resolved_runs, run_id=args.run)
    workspace = str(run.get("workspace") or "")
    payload = {
        "ok": True,
        "run": {
            "id": run["id"],
            "revision": run["revision"],
            "status": run.get("status"),
            "phase": run.get("phase"),
            "outcome": run.get("outcome"),
            "plan_revision": plan.get("revision"),
            "digests": dict(run.get("digests") or {}),
            "workspace": workspace,
        },
        **diagnostics,
    }
    if args.stream_json:
        emit_payload(payload)

    lines = [
        f"Run {run['id']}",
        f"  status: {run.get('status')}",
        f"  phase: {run.get('phase')}",
        f"  outcome: {run.get('outcome')}",
        f"  revision: {run['revision']}",
        f"  plan_revision: {plan.get('revision')}",
        f"  workspace: {workspace}",
        f"  runs_root: {resolved_runs.path}",
        f"  runs_root_source: {resolved_runs.source}",
        f"  run_path: {resolved_runs.path / args.run}",
    ]
    emit_message("\n".join(lines))


def handle_inspect_command(args: Namespace) -> None:
    if not args.run:
        emit_error_message(
            "tdp inspect requires --run",
            exit_code=2,
            stream_json=args.stream_json,
            code="missing_run",
        )

    view = args.view or "tree"
    if view != "tree":
        emit_error_message(
            f"unsupported inspect view: {view!r} (supported: tree)",
            exit_code=2,
            stream_json=args.stream_json,
            code="invalid_view",
        )

    store, _resolved_runs = _open_run_store_for_command(args)
    try:
        plan = store.load_plan_model(args.run)
        config = store.load_resolved_config(args.run)
    except RunNotFoundError as exc:
        emit_error_message(
            str(exc),
            exit_code=1,
            stream_json=args.stream_json,
            code="run_not_found",
        )

    limits = planning_limits_from_config(config)
    tree = build_tree_view(plan, limits=limits)
    payload = {
        "ok": True,
        "view": view,
        "revision": plan.revision,
        **tree,
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

    store, _resolved_runs = _open_run_store_for_command(args)
    try:
        run = store.load_run(args.run)
        plan = store.load_plan_model(args.run)
        config = store.load_resolved_config(args.run)
        production = store.load_production(args.run)
    except RunNotFoundError as exc:
        emit_error_message(
            str(exc),
            exit_code=1,
            stream_json=args.stream_json,
            code="run_not_found",
        )

    limits = planning_limits_from_config(config)
    dispositions = dict(production.get("dispositions") or {})
    phase = str(run.get("phase") or "")
    mode, review_state, digest_bundle = user_validate_mode_and_context(
        store,
        args.run,
        run,
        plan,
    )

    plan_validation = validate_plan(
        plan,
        limits=limits,
        dispositions=dispositions,
        mode=mode,
        review_state=review_state,
        digests=digest_bundle,
        reviews=store.list_reviews(args.run),
    )

    output_validation = None
    output_mode = "draft"
    completion_claim = production.get("completion_claim")
    output_revision = int(production.get("output_revision") or 0)
    output_approval = find_whole_output_approval(store.list_reviews(args.run), output_revision)
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
                actual_config_digest,
                actual_input_digest,
                actual_output_goal_digest,
                actual_context_digest,
            ) = compute_plan_approval_actual_digests(store, args.run, run, plan)
            output_review_state, output_digest_bundle = build_output_approval_validation_context(
                production=production,
                approval=output_approval,
                actual_output_digest=compute_output_digest(production),
                actual_plan_digest=actual_plan_digest,
                actual_config_digest=actual_config_digest,
                actual_input_digest=actual_input_digest,
                actual_output_goal_digest=actual_output_goal_digest,
                actual_context_digest=actual_context_digest,
            )
        output_validation = validate_output(
            plan,
            production,
            review_state=output_review_state,
            digests=output_digest_bundle,
            reviews=store.list_reviews(args.run),
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
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
    )
    return Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal=output_goal,
        input_refs=input_refs,
        items={"item-root": root},
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
