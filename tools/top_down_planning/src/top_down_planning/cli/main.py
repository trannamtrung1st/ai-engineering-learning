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


def _add_operational_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--runs-dir", help=RUNS_DIR_HELP)
    parser.add_argument(
        "--stream-json",
        action="store_true",
        help="Emit structured JSON instead of human-readable output.",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable color output (reserved for future renderer use).",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tdp",
        description=(
            "Top Down Planning — orchestrate high-level planning and production "
            "with structured agent tools."
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

    resume_parser = subparsers.add_parser("resume", help="Resume an interrupted run.")
    resume_parser.add_argument("--run", help="Run id.")
    resume_parser.add_argument(
        "--config",
        help=(
            "YAML configuration file. Uses runtime.runs_dir (resolved from process "
            "cwd) when locating the store."
        ),
    )
    _add_operational_flags(resume_parser)

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
        help="Inspection view (currently only tree).",
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

    parser.error(f"unknown command: {args.command!r}")


if __name__ == "__main__":
    main()
