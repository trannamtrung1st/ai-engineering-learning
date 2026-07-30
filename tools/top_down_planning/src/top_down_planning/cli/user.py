"""User-facing orchestration CLI commands (proposal §20)."""

from __future__ import annotations

import json
import uuid
from argparse import Namespace
from pathlib import Path
from typing import Any

from top_down_planning.agent_tool.config import planning_limits_from_config
from top_down_planning.agent_tool.views import build_tree_view
from top_down_planning.cli.common import (
    emit_error_message,
    emit_message,
    emit_payload,
    resolve_runs_dir,
)
from top_down_planning.config import (
    ConfigError,
    compute_input_digest,
    compute_output_goal_digest,
    resolve_config,
)
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.reviews import find_whole_plan_approval
from top_down_planning.domain.validators import (
    DigestBundle,
    ReviewState,
    ValidationMode,
    build_plan_approval_validation_context,
    validate_plan,
)
from top_down_planning.orchestrator import (
    PlanningPhaseOrchestrator,
    ProductionPhaseOrchestrator,
    ProviderRunError,
    WholePlanReviewOrchestrator,
)
from top_down_planning.orchestrator.phases import (
    PLANNING,
    PLAN_VALIDATED,
    PRODUCTION,
    WHOLE_OUTPUT_REVIEW,
    WHOLE_PLAN_REVIEW,
)
from top_down_planning.persistence import FileRunStore, RunNotFoundError
from top_down_planning.persistence.digests import compute_config_digest, compute_plan_digest
from top_down_planning.provider import create_provider


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

    output_goal = str((resolved.get("run") or {}).get("output_goal") or "").strip()
    if not output_goal:
        emit_error_message(
            "resolved config requires run.output_goal",
            exit_code=2,
            stream_json=args.stream_json,
            code="config_error",
        )

    run_id = f"run-{uuid.uuid4().hex[:12]}"
    base_dir = config_path.parent
    input_digest = compute_input_digest(resolved, base_dir=base_dir)
    output_goal_digest = compute_output_goal_digest(resolved)
    plan = _initial_plan(run_id, resolved)

    store = FileRunStore(resolve_runs_dir(args.runs_dir))
    store.root.mkdir(parents=True, exist_ok=True)
    run_record = store.create_run(
        run_id,
        plan=plan,
        resolved_config=resolved,
        input_digest=input_digest,
        output_goal_digest=output_goal_digest,
        workspace=str(base_dir),
    )

    provider = create_provider(resolved, workspace=base_dir)
    try:
        result = PlanningPhaseOrchestrator(store, run_id, provider).run()
    except ProviderRunError as exc:
        emit_error_message(
            str(exc),
            exit_code=1,
            stream_json=args.stream_json,
            code="provider_run_error",
        )

    run_record = store.load_run(run_id)
    payload = {
        "ok": result.ok,
        "run_id": run_id,
        "revision": run_record["revision"],
        "phase": run_record["phase"],
        "status": run_record.get("status"),
        "outcome": run_record.get("outcome"),
        "config_digest": run_record["digests"]["config"],
        "session_id": result.session_id,
        "agent_turns": result.agent_turns,
        "expansion_iterations": result.expansion_iterations,
    }
    if result.reason:
        payload["reason"] = result.reason

    exit_code = 0 if result.ok else 1
    if args.stream_json:
        emit_payload(payload, exit_code=exit_code)

    if result.ok and result.phase == WHOLE_PLAN_REVIEW:
        message = (
            f"Run {run_id} completed planning construction "
            f"(phase={WHOLE_PLAN_REVIEW}, session={result.session_id}, "
            f"turns={result.agent_turns})."
        )
    elif not result.ok:
        message = (
            f"Run {run_id} stopped during planning: {result.reason} "
            f"(outcome={result.outcome})."
        )
    else:
        message = f"Run {run_id} phase={result.phase} status={result.status}."
    emit_message(message, exit_code=exit_code)


def handle_resume_command(args: Namespace) -> None:
    if not args.run:
        emit_error_message(
            "tdp resume requires --run",
            exit_code=2,
            stream_json=args.stream_json,
            code="missing_run",
        )

    store = FileRunStore(resolve_runs_dir(args.runs_dir))
    try:
        run = store.load_run(args.run)
    except RunNotFoundError as exc:
        emit_error_message(
            str(exc),
            exit_code=1,
            stream_json=args.stream_json,
            code="run_not_found",
        )

    phase = str(run.get("phase") or "")
    if phase == WHOLE_OUTPUT_REVIEW:
        payload = {
            "ok": True,
            "run_id": args.run,
            "phase": phase,
            "status": run.get("status"),
            "outcome": run.get("outcome"),
            "message": "production already completed",
        }
        if args.stream_json:
            emit_payload(payload)
        emit_message(
            f"Run {args.run} already completed production (phase={WHOLE_OUTPUT_REVIEW}).",
        )
        return

    if phase == PLAN_VALIDATED or phase == PRODUCTION:
        config = store.load_resolved_config(args.run)
        workspace = _run_workspace(run)
        provider = create_provider(config, workspace=workspace)
        try:
            result = ProductionPhaseOrchestrator(store, args.run, provider).run()
        except ProviderRunError as exc:
            emit_error_message(
                str(exc),
                exit_code=1,
                stream_json=args.stream_json,
                code="provider_run_error",
            )

        run = store.load_run(args.run)
        payload = {
            "ok": result.ok,
            "run_id": args.run,
            "phase": run.get("phase"),
            "status": run.get("status"),
            "outcome": run.get("outcome"),
            "session_id": result.session_id,
            "batch_count": result.batch_count,
        }
        if result.reason:
            payload["reason"] = result.reason
        exit_code = 0 if result.ok else 1
        if args.stream_json:
            emit_payload(payload, exit_code=exit_code)

        if result.ok and result.phase == WHOLE_OUTPUT_REVIEW:
            message = (
                f"Run {args.run} completed production "
                f"(phase={WHOLE_OUTPUT_REVIEW}, batches={result.batch_count})."
            )
        elif not result.ok:
            message = (
                f"Run {args.run} stopped during production: {result.reason} "
                f"(outcome={result.outcome})."
            )
        else:
            message = f"Run {args.run} phase={result.phase} status={result.status}."
        emit_message(message, exit_code=exit_code)
        return

    if phase == WHOLE_PLAN_REVIEW:
        config = store.load_resolved_config(args.run)
        workspace = _run_workspace(run)
        provider = create_provider(config, workspace=workspace)
        try:
            result = WholePlanReviewOrchestrator(store, args.run, provider).run()
        except ProviderRunError as exc:
            emit_error_message(
                str(exc),
                exit_code=1,
                stream_json=args.stream_json,
                code="provider_run_error",
            )

        run = store.load_run(args.run)
        payload = {
            "ok": result.ok,
            "run_id": args.run,
            "phase": run.get("phase"),
            "status": run.get("status"),
            "outcome": run.get("outcome"),
            "loop_id": result.loop_id,
            "reviewer_session_id": result.reviewer_session_id,
            "revision_cycles": result.revision_cycles,
        }
        if result.reason:
            payload["reason"] = result.reason
        exit_code = 0 if result.ok else 1
        if args.stream_json:
            emit_payload(payload, exit_code=exit_code)

        if result.ok and result.phase == PLAN_VALIDATED:
            message = (
                f"Run {args.run} passed whole-plan review "
                f"(phase={PLAN_VALIDATED}, loop={result.loop_id})."
            )
        elif not result.ok:
            message = (
                f"Run {args.run} stopped during whole-plan review: {result.reason} "
                f"(outcome={result.outcome})."
            )
        else:
            message = f"Run {args.run} phase={result.phase} status={result.status}."
        emit_message(message, exit_code=exit_code)
        return

    if phase != PLANNING:
        emit_error_message(
            f"resume for phase {phase!r} is not implemented yet",
            exit_code=2,
            stream_json=args.stream_json,
            code="not_implemented",
        )

    config = store.load_resolved_config(args.run)
    workspace = _run_workspace(run)
    provider = create_provider(config, workspace=workspace)
    try:
        result = PlanningPhaseOrchestrator(store, args.run, provider).run()
    except ProviderRunError as exc:
        emit_error_message(
            str(exc),
            exit_code=1,
            stream_json=args.stream_json,
            code="provider_run_error",
        )

    run = store.load_run(args.run)
    payload = {
        "ok": result.ok,
        "run_id": args.run,
        "phase": run.get("phase"),
        "status": run.get("status"),
        "outcome": run.get("outcome"),
        "session_id": result.session_id,
    }
    if result.reason:
        payload["reason"] = result.reason
    exit_code = 0 if result.ok else 1
    if args.stream_json:
        emit_payload(payload, exit_code=exit_code)
    if result.ok:
        emit_message(
            f"Resumed run {args.run} to phase {run.get('phase')} "
            f"(session={result.session_id}).",
            exit_code=exit_code,
        )
    else:
        emit_message(
            f"Resumed run {args.run} stopped: {result.reason} (outcome={result.outcome}).",
            exit_code=exit_code,
        )


def handle_status_command(args: Namespace) -> None:
    if not args.run:
        emit_error_message(
            "tdp status requires --run",
            exit_code=2,
            stream_json=args.stream_json,
            code="missing_run",
        )

    store = FileRunStore(resolve_runs_dir(args.runs_dir))
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
        },
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

    store = FileRunStore(resolve_runs_dir(args.runs_dir))
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

    store = FileRunStore(resolve_runs_dir(args.runs_dir))
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
    mode, review_state, digest_bundle = _validation_context(store, args.run, run, plan)

    validation = validate_plan(
        plan,
        limits=limits,
        dispositions=dispositions,
        mode=mode,
        review_state=review_state,
        digests=digest_bundle,
    )
    payload = {
        "ok": validation.ok,
        "mode": mode,
        "revision": plan.revision,
        "issues": [issue.to_dict() for issue in validation.issues],
    }
    exit_code = 0 if validation.ok else 1
    if args.stream_json:
        emit_payload(payload, exit_code=exit_code)

    if validation.ok:
        emit_message(f"Validation passed ({mode} mode).", exit_code=0)
        return

    lines = [f"Validation failed ({mode} mode):"]
    for issue in validation.issues:
        path = ".".join(issue.path) if issue.path else "-"
        lines.append(f"  [{issue.severity}] {issue.code} ({path}): {issue.message}")
    emit_message("\n".join(lines), exit_code=exit_code)


def _initial_plan(run_id: str, config: dict[str, Any]) -> Plan:
    run_section = config.get("run") or {}
    output_goal = str(run_section.get("output_goal") or "")
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


def _validation_context(
    store: FileRunStore,
    run_id: str,
    run: dict[str, Any],
    plan: Plan,
) -> tuple[ValidationMode, ReviewState | None, DigestBundle | None]:
    approval = find_whole_plan_approval(store.list_reviews(run_id), plan.revision)
    if approval is None:
        return "draft", None, None

    resolved_config = store.load_resolved_config(run_id)
    review_state, digest_bundle = build_plan_approval_validation_context(
        run=run,
        plan=plan,
        approval=approval,
        actual_plan_digest=compute_plan_digest(plan),
        actual_config_digest=compute_config_digest(resolved_config),
    )
    return "approval", review_state, digest_bundle


def _run_workspace(run: dict[str, Any]) -> Path | None:
    workspace = run.get("workspace")
    if workspace is None:
        return None
    return Path(str(workspace))
