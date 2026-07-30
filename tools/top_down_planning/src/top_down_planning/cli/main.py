"""Top Down Planning CLI entry point (proposal §20)."""

from __future__ import annotations

import argparse
import sys

from top_down_planning import __version__


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
    run_parser.add_argument("--config", help="YAML configuration file.")
    run_parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="PATH=VALUE",
        help="Resolved-config override (repeatable; proposal §14).",
    )

    resume_parser = subparsers.add_parser("resume", help="Resume an interrupted run.")
    resume_parser.add_argument("--run", help="Run id.")

    status_parser = subparsers.add_parser("status", help="Show run status.")
    status_parser.add_argument("--run", help="Run id.")

    inspect_parser = subparsers.add_parser("inspect", help="Inspect run artifacts.")
    inspect_parser.add_argument("--run", help="Run id.")
    inspect_parser.add_argument(
        "--view",
        help="Inspection view (e.g. tree, ready).",
    )

    validate_parser = subparsers.add_parser(
        "validate",
        help="Run deterministic validators.",
    )
    validate_parser.add_argument("--run", help="Run id.")

    agent_parser = subparsers.add_parser(
        "agent",
        help="Agent-facing structured tool commands.",
    )
    agent_parser.add_argument(
        "agent_command",
        nargs="?",
        help="Agent subcommand (help, plan, production, review, run, …).",
    )

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return

    print(f"tdp {args.command}: not implemented yet.", file=sys.stderr)
    raise SystemExit(2)


if __name__ == "__main__":
    main()
