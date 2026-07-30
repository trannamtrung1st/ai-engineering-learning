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
from top_down_planning.domain.validators import (
    DigestBundle,
    ReviewState,
    ValidationMode,
    validate_plan,
)
from top_down_planning.persistence import FileRunStore, RunNotFoundError
from top_down_planning.persistence.digests import compute_config_digest, compute_plan_digest


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
    )

    payload = {
        "ok": True,
        "run_id": run_id,
        "revision": run_record["revision"],
        "phase": run_record["phase"],
        "config_digest": run_record["digests"]["config"],
        "next_phase": "planning orchestration not implemented",
    }
    if args.stream_json:
        emit_payload(payload, exit_code=2)
    message = (
        f"Created run {run_id} (phase={run_record['phase']}, "
        f"config_digest={run_record['digests']['config']}).\n"
        "Planning orchestration is not implemented yet."
    )
    emit_message(message, exit_code=2)


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

    payload = {
        "ok": False,
        "run_id": args.run,
        "phase": run.get("phase"),
        "status": run.get("status"),
        "error": {
            "code": "not_implemented",
            "message": "orchestration resume is not implemented yet",
        },
    }
    if args.stream_json:
        emit_payload(payload, exit_code=2)
    emit_error_message(
        f"Run {args.run} loaded; orchestration resume is not implemented yet.",
        exit_code=2,
        stream_json=False,
        code="not_implemented",
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
    approval = _load_whole_plan_approval(store, run_id, plan.revision)
    if approval is None:
        return "draft", None, None

    digests = run.get("digests") or {}
    resolved_config = store.load_resolved_config(run_id)
    digest_bundle = DigestBundle(
        plan_revision=plan.revision,
        expected_plan_digest=digests.get("plan"),
        actual_plan_digest=compute_plan_digest(plan),
        input_digest=digests.get("input"),
        expected_input_digest=digests.get("input"),
        output_goal_digest=digests.get("output_goal"),
        expected_output_goal_digest=digests.get("output_goal"),
        config_digest=compute_config_digest(resolved_config),
        expected_config_digest=digests.get("config"),
        context_digest=digests.get("context"),
        expected_context_digest=digests.get("context"),
    )
    review_state = ReviewState(
        approved_revision=int(approval["target_revision"]),
        unresolved_blocking_findings=_blocking_unresolved_findings(approval),
    )
    return "approval", review_state, digest_bundle


def _load_whole_plan_approval(
    store: FileRunStore,
    run_id: str,
    plan_revision: int,
) -> dict[str, Any] | None:
    reviews_dir = store.run_dir(run_id) / "reviews"
    if not reviews_dir.is_dir():
        return None

    for path in sorted(reviews_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("type") != "whole_plan":
            continue
        if payload.get("status") != "approved":
            continue
        target_revision = payload.get("target_revision")
        if target_revision is None:
            continue
        if int(target_revision) != plan_revision:
            continue
        return payload
    return None


def _blocking_unresolved_findings(review: dict[str, Any]) -> list[str]:
    findings = review.get("findings") or []
    unresolved: list[str] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        if finding.get("importance") != "blocking":
            continue
        if finding.get("status") != "unresolved":
            continue
        finding_id = finding.get("id")
        if finding_id is not None:
            unresolved.append(str(finding_id))
    return unresolved
