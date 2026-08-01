"""Top Down Planning CLI entry point (proposal §20)."""

from __future__ import annotations

import argparse

from top_down_planning import __version__
from top_down_planning.cli.common import RUNS_DIR_HELP
from top_down_planning.cli.agent import add_agent_subparsers, handle_agent_command
from top_down_planning.cli.user import (
    handle_inspect_command,
    handle_resume_command,
    handle_run_command,
    handle_status_command,
    handle_validate_command,
)
from top_down_planning.cli.doctor import handle_doctor_command


def _add_operational_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--runs-dir", help=RUNS_DIR_HELP)
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
        type=int,
        default=None,
        metavar="N",
        help=(
            "Truncate console event messages after N characters "
            "(default: from config or unlimited)."
        ),
    )
    parser.add_argument(
        "--max-tool-summary-length",
        type=int,
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
    parser = argparse.ArgumentParser(
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
    _add_operational_flags(run_parser)
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
        help="Report orphan agent processes for a run.",
    )
    doctor_parser.add_argument("--run", help="Run id.")
    doctor_parser.add_argument(
        "--config",
        help=(
            "YAML configuration file. Uses runtime.runs_dir (resolved from process "
            "cwd) when locating the store."
        ),
    )
    _add_operational_flags(doctor_parser)

    add_agent_subparsers(subparsers)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return

    if args.command == "agent":
        handle_agent_command(args)
        return

    if args.command == "run":
        handle_run_command(args)
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

    parser.error(f"unknown command: {args.command!r}")


if __name__ == "__main__":
    main()
