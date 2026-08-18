"""Agent-facing CLI command wiring (proposal §20)."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from top_down_planning.agent_tool import (
    AgentToolError,
    PlanAgentService,
    ProductionAgentService,
    ReviewAgentService,
    RunAgentService,
)
from top_down_planning.agent_tool.request_audit import (
    AgentRequestContext,
    complete_agent_request,
    consume_agent_request,
    map_exception_to_result,
    map_response_to_result,
)
from top_down_planning.cli.common import (
    AGENT_RUNS_DIR_HELP,
    RunsStoreNotFoundError,
    emit_message,
    emit_payload,
    open_run_store,
)
from top_down_planning.persistence import FileRunStore, RunNotFoundError
from top_down_planning.domain.plan_schema import UnsupportedPlanSchemaVersionError
from top_down_planning import schema_docs


def add_agent_subparsers(subparsers: argparse._SubParsersAction) -> None:
    agent_parser = subparsers.add_parser(
        "agent",
        help="Agent-facing tdp agent CLI commands.",
    )
    agent_sub = agent_parser.add_subparsers(dest="agent_command")

    agent_sub.add_parser(
        "help",
        help="Summarize agent commands, schemas, and examples.",
    )
    agent_sub.add_parser(
        "readme",
        help="Agent protocol overview and discoverability pointers.",
    )

    schema_parser = agent_sub.add_parser(
        "schema",
        help="Show JSON Schema for a published contract (or list all).",
    )
    schema_parser.add_argument(
        "name",
        nargs="?",
        help="Schema name (omit to list published schemas).",
    )

    example_parser = agent_sub.add_parser(
        "example",
        help="Show a minimal valid example payload (or list all).",
    )
    example_parser.add_argument(
        "name",
        nargs="?",
        help="Example name (omit to list published examples).",
    )

    plan_parser = agent_sub.add_parser("plan", help="Plan snapshot/apply/check commands.")
    plan_sub = plan_parser.add_subparsers(dest="plan_command")

    snapshot_parser = plan_sub.add_parser("snapshot", help="Return a bounded plan view.")
    _add_run_flags(snapshot_parser)
    snapshot_parser.add_argument(
        "--view",
        choices=["active", "audit", "ready", "issues", "budget"],
        default="active",
        help=(
            "Snapshot view (default: active). audit includes inactive history; "
            "budget returns planning_budget for the requested root/item subtree."
        ),
    )
    snapshot_parser.add_argument("--root", help="Subtree root item id.")
    snapshot_parser.add_argument("--depth", type=int, help="Maximum subtree depth.")
    snapshot_parser.add_argument(
        "--mode",
        choices=["draft", "approval"],
        default="draft",
        help="Validation mode for --view issues.",
    )

    apply_parser = plan_sub.add_parser("apply", help="Apply an atomic plan transaction.")
    _add_run_flags(apply_parser)
    apply_parser.add_argument(
        "--request",
        help="JSON or YAML request file (default: stdin).",
    )

    check_parser = plan_sub.add_parser("check", help="Run deterministic plan validation.")
    _add_run_flags(check_parser)
    check_parser.add_argument(
        "--mode",
        choices=["draft", "approval"],
        default="draft",
        help="Validation mode (default: draft).",
    )

    production_parser = agent_sub.add_parser(
        "production",
        help="Production snapshot/apply/check commands.",
    )
    production_sub = production_parser.add_subparsers(dest="production_command")

    production_snapshot_parser = production_sub.add_parser(
        "snapshot",
        help="Return a bounded production view.",
    )
    _add_run_flags(production_snapshot_parser)
    production_snapshot_parser.add_argument(
        "--view",
        choices=["tree", "ready", "dispositions"],
        default="ready",
        help=(
            "Snapshot view (default: ready). dispositions returns the full "
            "disposition map; ready includes compact disposition_summary counts."
        ),
    )

    production_apply_parser = production_sub.add_parser(
        "apply",
        help="Record an atomic production batch.",
    )
    _add_run_flags(production_apply_parser)
    production_apply_parser.add_argument(
        "--request",
        help="JSON or YAML request file (default: stdin).",
    )

    production_check_parser = production_sub.add_parser(
        "check",
        help="Run deterministic production validation.",
    )
    _add_run_flags(production_check_parser)

    production_amendment_parser = production_sub.add_parser(
        "request-amendment",
        help="Record a controlled plan amendment request.",
    )
    _add_run_flags(production_amendment_parser)
    production_amendment_parser.add_argument(
        "--request",
        help="JSON or YAML request file (default: stdin).",
    )

    production_completion_parser = production_sub.add_parser(
        "submit-completion",
        help="Record a production completion claim.",
    )
    _add_run_flags(production_completion_parser)
    production_completion_parser.add_argument(
        "--request",
        help="JSON or YAML request file (default: stdin).",
    )

    production_blocked_parser = production_sub.add_parser(
        "report-blocked",
        help="Record a production blocker with evidence.",
    )
    _add_run_flags(production_blocked_parser)
    production_blocked_parser.add_argument(
        "--request",
        help="JSON or YAML request file (default: stdin).",
    )

    review_parser = agent_sub.add_parser(
        "review",
        help="Review request and respond commands.",
    )
    review_sub = review_parser.add_subparsers(dest="review_command")

    respond_parser = review_sub.add_parser(
        "respond",
        help="Submit review findings and a decision.",
    )
    _add_run_flags(respond_parser)
    respond_parser.add_argument(
        "--request",
        help="JSON or YAML request file (default: stdin).",
    )

    request_parser = review_sub.add_parser(
        "request",
        help="Request an optional focused plan or output review.",
    )
    _add_run_flags(request_parser)
    request_parser.add_argument(
        "--request",
        help="JSON or YAML request file (default: stdin).",
    )

    record_actions_parser = review_sub.add_parser(
        "record-actions",
        help="Record primary-agent finding_actions (fix/defer/accept_as_is/challenge).",
    )
    _add_run_flags(record_actions_parser)
    record_actions_parser.add_argument(
        "--request",
        help="JSON or YAML request file (default: stdin).",
    )

    run_parser = agent_sub.add_parser("run", help="Run-level agent commands.")
    run_sub = run_parser.add_subparsers(dest="run_command")
    status_parser = run_sub.add_parser("status", help="Return minimal run status.")
    _add_run_flags(status_parser)


def _add_run_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run", required=True, help="Run id.")
    parser.add_argument("--runs-dir", help=AGENT_RUNS_DIR_HELP)


def _open_agent_store(args: argparse.Namespace) -> FileRunStore:
    try:
        store, _resolved = open_run_store(args)
    except RunsStoreNotFoundError as exc:
        raise AgentToolError(str(exc)) from exc
    return store


def emit_response(payload: dict[str, Any], *, exit_code: int = 0) -> None:
    emit_payload(payload, exit_code=exit_code)


def emit_error(exc: Exception, *, exit_code: int = 1) -> None:
    if isinstance(exc, AgentToolError):
        payload = {"ok": False, "error": exc.to_dict()}
    elif isinstance(exc, RunNotFoundError):
        payload = {
            "ok": False,
            "error": {
                "code": "run_not_found",
                "message": str(exc),
            },
        }
    elif isinstance(exc, UnsupportedPlanSchemaVersionError):
        payload = {
            "ok": False,
            "error": {
                "code": exc.code,
                "message": str(exc),
            },
        }
    else:
        payload = {
            "ok": False,
            "error": {
                "code": "internal_error",
                "message": str(exc),
            },
        }
    emit_response(payload, exit_code=exit_code)


def _run_mutating_command(
    store: FileRunStore,
    run_id: str,
    operation: str,
    args: argparse.Namespace,
    handler: Callable[..., dict[str, Any]],
    *,
    default_exit_code: int | None = None,
) -> None:
    context: AgentRequestContext | None = None
    try:
        payload, context = consume_agent_request(
            store,
            run_id,
            operation=operation,
            request_path=args.request,
        )
        result = handler(payload, request_audit=context)
        applied = map_response_to_result(result)
        try:
            complete_agent_request(
                store,
                run_id,
                context,
                result=applied,
            )
        except Exception:
            if applied == "applied":
                result = dict(result)
                result["audit_degraded"] = True
            else:
                raise
        if default_exit_code is not None:
            exit_code = default_exit_code
        else:
            exit_code = 0 if result.get("ok") else 1
        emit_response(result, exit_code=exit_code)
    except AgentToolError as exc:
        audit_context = context or getattr(exc, "request_context", None)
        if audit_context is not None:
            complete_agent_request(
                store,
                run_id,
                audit_context,
                result=map_exception_to_result(exc),
            )
        emit_error(exc)
    except Exception as exc:
        if context is not None:
            complete_agent_request(store, run_id, context, result="failed")
        emit_error(exc)


def handle_agent_command(args: argparse.Namespace) -> None:
    if args.agent_command is None:
        emit_message(schema_docs.AGENT_HELP_TEXT)
        return

    if args.agent_command == "help":
        emit_message(schema_docs.AGENT_HELP_TEXT)
        return

    if args.agent_command == "readme":
        emit_message(schema_docs.AGENT_README_TEXT)
        return

    if args.agent_command == "schema":
        _handle_schema_command(args)
        return

    if args.agent_command == "example":
        _handle_example_command(args)
        return

    if args.agent_command == "plan":
        _handle_plan_command(args)
        return

    if args.agent_command == "production":
        _handle_production_command(args)
        return

    if args.agent_command == "review":
        _handle_review_command(args)
        return

    if args.agent_command == "run":
        if args.run_command == "status":
            _handle_run_status(args)
            return
        emit_error(AgentToolError("run command required: status"), exit_code=2)
        return

    emit_error(
        AgentToolError(f"unknown agent command: {args.agent_command!r}"),
        exit_code=2,
    )


def _handle_schema_command(args: argparse.Namespace) -> None:
    name = getattr(args, "name", None)
    if not name:
        emit_response(schema_docs.schema_list_payload())
        return

    try:
        emit_response(
            {
                "ok": True,
                "name": name,
                "schema": schema_docs.show_schema(name),
            }
        )
    except KeyError:
        emit_response(schema_docs.unknown_schema_response(name))


def _handle_example_command(args: argparse.Namespace) -> None:
    name = getattr(args, "name", None)
    if not name:
        emit_response(schema_docs.example_list_payload())
        return

    try:
        emit_response({"ok": True, **schema_docs.show_example(name)})
    except KeyError:
        emit_response(schema_docs.unknown_example_response(name))


def _handle_plan_command(args: argparse.Namespace) -> None:
    if args.plan_command is None:
        emit_error(
            AgentToolError("plan command required: snapshot, apply, or check"),
            exit_code=2,
        )

    store = _open_agent_store(args)
    service = PlanAgentService(store, args.run)

    try:
        if args.plan_command == "snapshot":
            payload = service.snapshot(
                view=args.view,
                root_id=args.root,
                depth=args.depth,
                mode=args.mode,
            )
            emit_response(payload, exit_code=0 if payload["ok"] else 1)
        elif args.plan_command == "apply":
            _run_mutating_command(
                store,
                args.run,
                "plan.apply",
                args,
                service.apply,
            )
        elif args.plan_command == "check":
            payload = service.check(mode=args.mode)
            emit_response(payload, exit_code=0 if payload["ok"] else 1)
        else:
            emit_error(
                AgentToolError(f"unknown plan command: {args.plan_command!r}"),
                exit_code=2,
            )
    except AgentToolError as exc:
        emit_error(exc)
    except Exception as exc:
        emit_error(exc)


def _handle_production_command(args: argparse.Namespace) -> None:
    if args.production_command is None:
        emit_error(
            AgentToolError(
                "production command required: snapshot, apply, check, "
                "request-amendment, submit-completion, or report-blocked"
            ),
            exit_code=2,
        )

    store = _open_agent_store(args)
    service = ProductionAgentService(store, args.run)

    try:
        if args.production_command == "snapshot":
            payload = service.snapshot(view=args.view)
            emit_response(payload, exit_code=0 if payload["ok"] else 1)
        elif args.production_command == "apply":
            _run_mutating_command(
                store,
                args.run,
                "production.apply",
                args,
                service.apply,
            )
        elif args.production_command == "check":
            payload = service.check()
            emit_response(payload, exit_code=0 if payload["ok"] else 1)
        elif args.production_command == "request-amendment":
            _run_mutating_command(
                store,
                args.run,
                "production.request_amendment",
                args,
                service.request_amendment,
            )
        elif args.production_command == "submit-completion":
            _run_mutating_command(
                store,
                args.run,
                "production.submit_completion",
                args,
                service.submit_completion,
            )
        elif args.production_command == "report-blocked":
            _run_mutating_command(
                store,
                args.run,
                "production.report_blocked",
                args,
                service.report_blocked,
            )
        else:
            emit_error(
                AgentToolError(f"unknown production command: {args.production_command!r}"),
                exit_code=2,
            )
    except AgentToolError as exc:
        emit_error(exc)
    except Exception as exc:
        emit_error(exc)


def _handle_review_command(args: argparse.Namespace) -> None:
    if args.review_command is None:
        emit_error(
            AgentToolError(
                "review command required: request, respond, or record-actions"
            ),
            exit_code=2,
        )

    store = _open_agent_store(args)
    service = ReviewAgentService(store, args.run)

    try:
        if args.review_command == "respond":
            _run_mutating_command(
                store,
                args.run,
                "review.respond",
                args,
                service.respond,
                default_exit_code=0,
            )
        elif args.review_command == "request":
            _run_mutating_command(
                store,
                args.run,
                "review.request",
                args,
                service.request,
                default_exit_code=0,
            )
        elif args.review_command == "record-actions":
            _run_mutating_command(
                store,
                args.run,
                "review.record_actions",
                args,
                service.record_finding_actions,
                default_exit_code=0,
            )
        else:
            emit_error(
                AgentToolError(f"unknown review command: {args.review_command!r}"),
                exit_code=2,
            )
    except AgentToolError as exc:
        emit_error(exc)
    except Exception as exc:
        emit_error(exc)


def _handle_run_status(args: argparse.Namespace) -> None:
    store = _open_agent_store(args)
    service = RunAgentService(store, args.run)
    try:
        emit_response(service.status())
    except Exception as exc:
        emit_error(exc)
