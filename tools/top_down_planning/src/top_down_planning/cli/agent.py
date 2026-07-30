"""Agent-facing CLI command wiring (proposal §20)."""

from __future__ import annotations

import argparse
from typing import Any

from top_down_planning.agent_tool import (
    AgentToolError,
    PlanAgentService,
    ProductionAgentService,
    RequestError,
    ReviewAgentService,
    RunAgentService,
    load_structured_request,
)
from top_down_planning.cli.common import emit_payload, resolve_runs_dir
from top_down_planning.persistence import FileRunStore, RunNotFoundError


def add_agent_subparsers(subparsers: argparse._SubParsersAction) -> None:
    agent_parser = subparsers.add_parser(
        "agent",
        help="Agent-facing structured tool commands.",
    )
    agent_sub = agent_parser.add_subparsers(dest="agent_command")

    plan_parser = agent_sub.add_parser("plan", help="Plan snapshot/apply/check commands.")
    plan_sub = plan_parser.add_subparsers(dest="plan_command")

    snapshot_parser = plan_sub.add_parser("snapshot", help="Return a bounded plan view.")
    _add_run_flags(snapshot_parser)
    snapshot_parser.add_argument(
        "--view",
        choices=["tree", "ready", "issues"],
        default="tree",
        help="Snapshot view (default: tree).",
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
    apply_parser.add_argument(
        "--role",
        help="Agent role (required unless request.role is set).",
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
        choices=["tree", "ready"],
        default="ready",
        help="Snapshot view (default: ready).",
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
    production_apply_parser.add_argument(
        "--role",
        help="Agent role (required unless request.role is set).",
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
    production_amendment_parser.add_argument(
        "--role",
        help="Agent role (required unless request.role is set).",
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
    production_completion_parser.add_argument(
        "--role",
        help="Agent role (required unless request.role is set).",
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
    production_blocked_parser.add_argument(
        "--role",
        help="Agent role (required unless request.role is set).",
    )

    review_parser = agent_sub.add_parser("review", help="Review respond commands.")
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
    respond_parser.add_argument(
        "--role",
        help="Agent role (required unless request.role is set).",
    )

    run_parser = agent_sub.add_parser("run", help="Run-level agent commands.")
    run_sub = run_parser.add_subparsers(dest="run_command")
    status_parser = run_sub.add_parser("status", help="Return minimal run status.")
    _add_run_flags(status_parser)

    for stub_name in ("help", "readme", "schema", "example"):
        stub_parser = agent_sub.add_parser(
            stub_name,
            help=f"Agent {stub_name} (not implemented).",
        )
        stub_parser.add_argument("name", nargs="?", help="Optional schema/example name.")


def _add_run_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run", required=True, help="Run id.")
    parser.add_argument(
        "--runs-dir",
        help="Run store root directory (default: $TDP_RUNS_DIR or ./runs).",
    )


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
    else:
        payload = {
            "ok": False,
            "error": {
                "code": "internal_error",
                "message": str(exc),
            },
        }
    emit_response(payload, exit_code=exit_code)


def handle_agent_command(args: argparse.Namespace) -> None:
    if args.agent_command in {"help", "readme", "schema", "example"}:
        emit_response(
            {
                "ok": False,
                "error": {
                    "code": "not_implemented",
                    "message": f"agent {args.agent_command} is not implemented yet",
                },
            },
            exit_code=2,
        )

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


def _resolve_apply_role(args: argparse.Namespace, request: dict[str, Any]) -> str:
    role = args.role if args.role is not None else request.get("role")
    if role is None or not str(role).strip():
        raise RequestError("apply requires --role or request.role")
    return str(role).strip()


def _resolve_respond_role(args: argparse.Namespace, request: dict[str, Any]) -> str:
    role = args.role if args.role is not None else request.get("role")
    if role is None or not str(role).strip():
        raise RequestError("respond requires --role or request.role")
    return str(role).strip()


def _handle_plan_command(args: argparse.Namespace) -> None:
    if args.plan_command is None:
        emit_error(
            AgentToolError("plan command required: snapshot, apply, or check"),
            exit_code=2,
        )

    store = FileRunStore(resolve_runs_dir(args.runs_dir))
    service = PlanAgentService(store, args.run)

    try:
        if args.plan_command == "snapshot":
            payload = service.snapshot(
                view=args.view,
                root_id=args.root,
                depth=args.depth,
                mode=args.mode,
            )
            emit_response(payload)
        elif args.plan_command == "apply":
            request = load_structured_request(request_path=args.request)
            role = _resolve_apply_role(args, request)
            payload = service.apply(request, role=role)
            emit_response(payload)
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

    store = FileRunStore(resolve_runs_dir(args.runs_dir))
    service = ProductionAgentService(store, args.run)

    try:
        if args.production_command == "snapshot":
            payload = service.snapshot(view=args.view)
            emit_response(payload)
        elif args.production_command == "apply":
            request = load_structured_request(request_path=args.request)
            role = _resolve_apply_role(args, request)
            payload = service.apply(request, role=role)
            emit_response(payload)
        elif args.production_command == "check":
            payload = service.check()
            emit_response(payload, exit_code=0 if payload["ok"] else 1)
        elif args.production_command == "request-amendment":
            request = load_structured_request(request_path=args.request)
            role = _resolve_apply_role(args, request)
            payload = service.request_amendment(request, role=role)
            emit_response(payload)
        elif args.production_command == "submit-completion":
            request = load_structured_request(request_path=args.request)
            role = _resolve_apply_role(args, request)
            payload = service.submit_completion(request, role=role)
            emit_response(payload)
        elif args.production_command == "report-blocked":
            request = load_structured_request(request_path=args.request)
            role = _resolve_apply_role(args, request)
            payload = service.report_blocked(request, role=role)
            emit_response(payload)
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
            AgentToolError("review command required: respond"),
            exit_code=2,
        )

    store = FileRunStore(resolve_runs_dir(args.runs_dir))
    service = ReviewAgentService(store, args.run)

    try:
        if args.review_command == "respond":
            request = load_structured_request(request_path=args.request)
            role = _resolve_respond_role(args, request)
            payload = service.respond(request, role=role)
            emit_response(payload)
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
    store = FileRunStore(resolve_runs_dir(args.runs_dir))
    service = RunAgentService(store, args.run)
    try:
        emit_response(service.status())
    except Exception as exc:
        emit_error(exc)
