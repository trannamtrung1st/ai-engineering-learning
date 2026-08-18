"""Top Down Planning CLI entry point (proposal §20)."""

from __future__ import annotations

import argparse
import sys

from top_down_planning import __version__
from top_down_planning.cli.common import (
    RUNS_DIR_HELP,
    RUNS_DIR_REQUIRED_HELP,
    emit_error_message,
)
from top_down_planning.cli.agent import add_agent_subparsers, handle_agent_command
from top_down_planning.cli.user import (
    handle_inspect_command,
    handle_resume_command,
    handle_run_command,
    handle_status_command,
    handle_validate_command,
)
from top_down_planning.cli.doctor import handle_doctor_command
from top_down_planning.cli.prepare import handle_prepare_command
from top_down_planning.cli.execute import handle_execute_command
from top_down_planning.cli.sub_tdp import handle_sub_tdp_attach_command


def _positive_int(value: str) -> int:
    try:
        parsed = int(value, 10)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid integer: {value!r}") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer (>= 1)")
    return parsed


class TdpArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that honors ``--stream-json`` for usage/type errors."""

    def parse_known_args(self, args=None, namespace=None):
        self._tdp_argv = list(sys.argv[1:] if args is None else args)
        return super().parse_known_args(args, namespace)

    def error(self, message: str) -> None:
        argv = getattr(self, "_tdp_argv", [])
        if "--stream-json" in argv:
            emit_error_message(
                message,
                exit_code=2,
                stream_json=True,
                code="usage_error",
            )
        super().error(message)


def _add_operational_flags(
    parser: argparse.ArgumentParser,
    *,
    runs_dir_help: str = RUNS_DIR_HELP,
) -> None:
    parser.add_argument("--runs-dir", help=runs_dir_help)
    parser.add_argument(
        "--stream-json",
        action="store_true",
        help="Emit structured JSON instead of human-readable output.",
    )
    parser.add_argument(
        "--color",
        choices=["auto", "always", "never"],
        default=None,
        help="Console color mode (default: from config or auto).",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable color output (sets --color never).",
    )
    parser.add_argument(
        "--log-level",
        choices=["quiet", "normal", "verbose", "trace"],
        default=None,
        help="Console observability verbosity (default: from config or normal).",
    )
    parser.add_argument(
        "--log-format",
        choices=["console", "jsonl"],
        default=None,
        help="Console observability output format (default: from config or console).",
    )
    parser.add_argument(
        "--agent-text",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Show agent thinking and response text (default: from config or on).",
    )
    parser.add_argument(
        "--timestamps",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Include timestamps in console output (default: from config or off).",
    )
    parser.add_argument(
        "--agent-transcript",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Persist redacted agent transcript to agent-transcript.jsonl.",
    )
    parser.add_argument(
        "--max-message-length",
        type=_positive_int,
        default=None,
        metavar="N",
        help=(
            "Truncate console event messages after N characters "
            "(default: from config or unlimited)."
        ),
    )
    parser.add_argument(
        "--max-tool-summary-length",
        type=_positive_int,
        default=None,
        metavar="N",
        help=(
            "Truncate tool:start/tool:end summaries after N characters "
            "(default: from config or unlimited)."
        ),
    )


def _add_notification_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--no-notify",
        action="store_true",
        default=None,
        help="Disable desktop notifications for this invocation.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = TdpArgumentParser(
        prog="tdp",
        description=(
            "Top Down Planning — orchestrate high-level planning and production "
            "via provider sessions and the tdp agent CLI."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"tdp {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Start a new planning run.")
    run_parser.add_argument(
        "--config",
        help=(
            "YAML configuration file. Config location does not affect path "
            "resolution; relative paths resolve from the process working directory."
        ),
    )
    run_parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="PATH=VALUE",
        help="Resolved-config override (repeatable; proposal §14).",
    )
    _add_operational_flags(run_parser, runs_dir_help=RUNS_DIR_REQUIRED_HELP)
    _add_notification_flags(run_parser)
    run_parser.add_argument(
        "--until",
        choices=["plan", "validated", "completed"],
        default="plan",
        help=(
            "Continue until planning construction (plan), plan validation "
            "(validated), or final outcome (completed)."
        ),
    )
    run_parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Allow starting a new run when paused runs still have orphan agent "
            "processes in the workspace."
        ),
    )

    prepare_parser = subparsers.add_parser(
        "prepare",
        help="Plan, review, approve, and materialize an execution package.",
    )
    prepare_parser.add_argument("--config", required=True, help="YAML configuration file.")
    prepare_parser.add_argument(
        "--output",
        default=".tdp/execution",
        help="Output directory for the immutable execution package.",
    )
    prepare_parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace an existing package at --output.",
    )
    prepare_parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="PATH=VALUE",
        help="Resolved-config override (repeatable).",
    )
    _add_operational_flags(prepare_parser, runs_dir_help=RUNS_DIR_REQUIRED_HELP)
    _add_notification_flags(prepare_parser)

    execute_parser = subparsers.add_parser(
        "execute",
        help="Execute a prepared parent graph or single unit from manifest.json.",
    )
    execute_parser.add_argument(
        "--manifest",
        required=True,
        help="Path to manifest.json in the prepared execution package.",
    )
    execute_parser.add_argument(
        "--unit",
        help="Execute one prepared unit directly instead of the parent graph.",
    )
    execute_parser.add_argument(
        "--parent-only",
        action="store_true",
        help=(
            "Create the parent execution run and enter sub_tdps ready for attach, "
            "without driving child units."
        ),
    )
    execute_parser.add_argument(
        "--upstream",
        action="append",
        default=[],
        metavar="UNIT=RUN_ID",
        help=(
            "Explicit upstream accepted child run for a dependency unit "
            "(repeatable; unit_id=run_id). Skips filesystem discovery when set."
        ),
    )
    execute_parser.add_argument(
        "--baseline",
        action="append",
        default=[],
        metavar="RUN_ID",
        help=(
            "Accepted child run whose workspace changes belong in the cumulative "
            "workspace baseline for direct --unit execution (repeatable). Does not "
            "create a semantic dependency; use --upstream for depends_on bindings."
        ),
    )
    execute_parser.add_argument("--config", help="YAML configuration file.")
    execute_parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="PATH=VALUE",
        help="Resolved-config override (repeatable).",
    )
    _add_operational_flags(execute_parser, runs_dir_help=RUNS_DIR_REQUIRED_HELP)
    _add_notification_flags(execute_parser)

    resume_parser = subparsers.add_parser("resume", help="Resume an interrupted run.")
    resume_parser.add_argument("--run", help="Run id.")
    resume_parser.add_argument(
        "--config",
        help=(
            "YAML configuration file. Uses runtime.runs_dir (resolved from process "
            "cwd) when locating the store."
        ),
    )
    resume_parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="PATH=VALUE",
        help="Resolved-config override for resume candidate (repeatable; proposal §16).",
    )
    resume_parser.add_argument(
        "--check",
        action="store_true",
        help="Build and print the resume plan without mutating the run (proposal §16.3).",
    )
    resume_parser.add_argument(
        "--allow-config-drift",
        action="store_true",
        help=(
            "Accept contract and model config changes on resume. Before whole-plan "
            "approval, changes apply and rebind digests; model-only context_spec drift "
            "is accepted. Non-model context_spec fields (guidance, resources, skills, "
            "exclusion policy) still block resume. After approval, approval-bound "
            "contract and model changes are ignored with warnings."
        ),
    )
    _add_operational_flags(resume_parser)
    _add_notification_flags(resume_parser)
    resume_parser.add_argument(
        "--until",
        choices=["plan", "validated", "completed"],
        help=(
            "Continue until the target lifecycle milestone. "
            "Omit to advance one orchestrator step (default). "
            "Targets: plan (past planning), validated (plan_validated+), "
            "completed (output_validated or terminal completed)."
        ),
    )

    status_parser = subparsers.add_parser("status", help="Show run status.")
    status_parser.add_argument("--run", help="Run id.")
    status_parser.add_argument(
        "--config",
        help=(
            "YAML configuration file. Uses runtime.runs_dir (resolved from process "
            "cwd) when locating the store."
        ),
    )
    _add_operational_flags(status_parser)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect run artifacts.")
    inspect_parser.add_argument("--run", help="Run id.")
    inspect_parser.add_argument(
        "--config",
        help=(
            "YAML configuration file. Uses runtime.runs_dir (resolved from process "
            "cwd) when locating the store."
        ),
    )
    inspect_parser.add_argument(
        "--view",
        choices=["active", "audit"],
        default="active",
        help="Inspection view (default: active). audit includes inactive history.",
    )
    _add_operational_flags(inspect_parser)

    validate_parser = subparsers.add_parser(
        "validate",
        help="Run deterministic validators.",
    )
    validate_parser.add_argument("--run", help="Run id.")
    validate_parser.add_argument(
        "--config",
        help=(
            "YAML configuration file. Uses runtime.runs_dir (resolved from process "
            "cwd) when locating the store."
        ),
    )
    _add_operational_flags(validate_parser)

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Report run/workspace hygiene issues and orphan agent processes.",
    )
    doctor_parser.add_argument(
        "--fix",
        action="store_true",
        help=(
            "Reconcile stale running runs, kill orphan agents, and remove "
            "leftover .creating-* staging directories."
        ),
    )
    doctor_parser.add_argument("--run", help="Run id (omit for workspace diagnostics).")
    doctor_parser.add_argument(
        "--config",
        help=(
            "YAML configuration file. Uses runtime.runs_dir (resolved from process "
            "cwd) when locating the store."
        ),
    )
    _add_operational_flags(doctor_parser)

    sub_tdp_parser = subparsers.add_parser("sub-tdp", help="Sub-TDP orchestration commands.")
    sub_tdp_subparsers = sub_tdp_parser.add_subparsers(dest="sub_tdp_command")
    attach_parser = sub_tdp_subparsers.add_parser(
        "attach",
        help="Attach an independently completed child run to parent orchestration.",
    )
    attach_parser.add_argument("--parent", required=True, help="Parent execution run id.")
    attach_parser.add_argument("--child", required=True, help="Child execution run id.")
    attach_parser.add_argument(
        "--config",
        help="YAML configuration file for resolving the parent runs store.",
    )
    _add_operational_flags(attach_parser)

    add_agent_subparsers(subparsers)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return

    from top_down_planning.config import ConfigError

    try:
        _dispatch_command(args, parser)
    except ConfigError as exc:
        emit_error_message(
            str(exc),
            exit_code=2,
            stream_json=bool(getattr(args, "stream_json", False)),
            code="config_error",
        )


def _dispatch_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.command == "agent":
        handle_agent_command(args)
        return

    if args.command == "run":
        handle_run_command(args)
        return

    if args.command == "prepare":
        handle_prepare_command(args)
        return

    if args.command == "execute":
        handle_execute_command(args)
        return

    if args.command == "resume":
        handle_resume_command(args)
        return

    if args.command == "status":
        handle_status_command(args)
        return

    if args.command == "inspect":
        handle_inspect_command(args)
        return

    if args.command == "validate":
        handle_validate_command(args)
        return

    if args.command == "doctor":
        handle_doctor_command(args)
        return

    if args.command == "sub-tdp":
        if args.sub_tdp_command == "attach":
            handle_sub_tdp_attach_command(args)
            return
        parser.error(f"unknown sub-tdp command: {args.sub_tdp_command!r}")

    parser.error(f"unknown command: {args.command!r}")


if __name__ == "__main__":
    main()
