"""Argparse CLI for the todos tool."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import NoReturn

from todos_tool import __version__
from todos_tool.models import DEFAULT_CURSOR_MODEL
from todos_tool.errors import SchedulingError, TodosToolError, UserInterrupted, ValidationError
from todos_tool.flags import env_truthy, parse_optional_bool
from todos_tool.config_loader import build_run_config
from todos_tool.manifest import load_workspace
from todos_tool.orchestrator import Orchestrator, RunConfig, RunReport
from todos_tool.persistence import load_state
from todos_tool.workspace_loader import DryRunReport, load_workspace_repairable
from todos_tool.scheduler import readiness_rows


def _optional_bool_arg(value: str) -> bool:
    try:
        parsed = parse_optional_bool(value, name="flag")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if parsed is None:
        raise argparse.ArgumentTypeError("expected true or false")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="todos-tool",
        description="Execute a structured todos/ workspace with Cursor Agent CLI.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=__version__,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Validate schemas and dependencies")
    _add_workspace_args(validate)

    status = subparsers.add_parser("status", help="Show item readiness and execution state")
    _add_workspace_args(status)
    status.add_argument("--no-color", action="store_true", help="Disable color output")

    for name, help_text in (
        ("run", "Execute ready items in dependency-safe order"),
        ("resume", "Recover from persisted state and actual Git state"),
    ):
        cmd = subparsers.add_parser(name, help=help_text)
        _add_run_args(cmd)

    commit = subparsers.add_parser(
        "commit",
        help="Commit trackable changes for a done item with no commit SHA",
    )
    _add_workspace_args(commit)
    commit.add_argument("--todo", required=True, help="Done item id to commit")
    commit.add_argument("--no-color", action="store_true")
    commit.add_argument(
        "--auto-commit",
        type=_optional_bool_arg,
        metavar="BOOL",
        help="Override manifest auto_commit (true/false)",
    )

    return parser


def _add_workspace_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Repository workspace root (default: .)",
    )
    parser.add_argument(
        "--todos-dir",
        default="todos",
        help="Relative path to the todos workspace (default: todos)",
    )


def _add_optional_workspace_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Repository workspace root (default: . or config workspace)",
    )
    parser.add_argument(
        "--todos-dir",
        default=None,
        help="Relative path to the todos workspace (default: todos or config todos_dir)",
    )


def _add_run_args(parser: argparse.ArgumentParser) -> None:
    _add_optional_workspace_args(parser)
    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        default=None,
        help="Optional YAML run config (CLI flags override config values)",
    )
    parser.add_argument("--todo", help="Execute one item id")
    parser.add_argument("--no-color", action="store_true", help="Disable color output")
    parser.add_argument(
        "--model",
        help=(
            "Cursor model override "
            f"(default: {DEFAULT_CURSOR_MODEL}; env: TODOS_TOOL_MODEL; "
            "manifest: settings.model)"
        ),
    )
    parser.add_argument(
        "--stop-on-failure",
        type=_optional_bool_arg,
        metavar="BOOL",
        help="Override manifest stop_on_failure (true/false)",
    )
    parser.add_argument(
        "--auto-commit",
        type=_optional_bool_arg,
        metavar="BOOL",
        help="Override manifest auto_commit (true/false; manifest default: true)",
    )
    parser.add_argument(
        "--agent-bin",
        default=None,
        help="Path to Cursor agent binary (default: agent/cursor-agent on PATH)",
    )
    parser.add_argument(
        "--skip-probe",
        action="store_true",
        help="Skip probing agent --help for stream flags (use documented defaults)",
    )
    parser.add_argument(
        "--project-config",
        type=Path,
        default=None,
        help="Path to repository profile YAML (default: .implement-todos.yaml when present)",
    )
    parser.add_argument(
        "--context-file",
        action="append",
        default=[],
        metavar="PATH",
        help="Additional repository context file (repeatable)",
    )
    parser.add_argument(
        "--skip-commit",
        action="store_true",
        help="Do not stage or commit worktree changes during finalization",
    )
    parser.add_argument(
        "--no-auto-repair-yaml",
        action="store_true",
        help="Disable bounded YAML auto-repair for malformed TODO documents",
    )
    parser.add_argument(
        "--max-yaml-repair-attempts",
        type=int,
        default=None,
        metavar="N",
        help="Maximum YAML repair attempts before failing (default: 2; 0 is fail-fast)",
    )
    parser.add_argument(
        "--commit-hint",
        default=None,
        help="Markdown guidance for proposed commit subjects in review",
    )
    parser.add_argument(
        "--commit-hint-file",
        type=Path,
        default=None,
        help="Markdown file with commit-subject guidance for review",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report whether YAML repair would be required without invoking Cursor",
    )
    parser.add_argument(
        "--dry-run-prompts",
        action="store_true",
        help="Write work/review prompt previews without agents or state changes",
    )
    parser.add_argument(
        "--evidence-mode",
        choices=("captured", "driver"),
        default=None,
        help="Completion-evidence mode for item evidence.commands (default: captured)",
    )
    parser.add_argument(
        "--max-identical-evidence-failures",
        type=int,
        default=None,
        metavar="N",
        help="Stop after N identical completion-evidence failures (default: 3)",
    )
    parser.add_argument(
        "--evidence-batch-timeout-seconds",
        type=int,
        default=None,
        metavar="SECONDS",
        help="Optional global timeout for driver-mode evidence command batches",
    )
    parser.add_argument(
        "--force-reset",
        action="store_true",
        help="Clear run state and reset incomplete items to pending before running",
    )


def _run_config_from_args(args: argparse.Namespace) -> RunConfig:
    env_skip = env_truthy("TODOS_TOOL_SKIP_PROBE")
    agent_bin = args.agent_bin
    if agent_bin is None:
        import os

        agent_bin = os.environ.get("TODOS_TOOL_AGENT_BIN")

    dry_run_prompts = bool(getattr(args, "dry_run_prompts", False))
    dry_run = bool(getattr(args, "dry_run", False))
    if dry_run and not dry_run_prompts:
        dry_run_prompts = False

    return build_run_config(
        config_path=getattr(args, "config", None),
        workspace=getattr(args, "workspace", None),
        todos_dir=getattr(args, "todos_dir", None),
        no_color=bool(getattr(args, "no_color", False)),
        model=getattr(args, "model", None),
        stop_on_failure=getattr(args, "stop_on_failure", None),
        auto_commit=getattr(args, "auto_commit", None),
        agent_bin=agent_bin,
        skip_probe=bool(getattr(args, "skip_probe", False)) or env_skip,
        dry_run_prompts=dry_run_prompts,
        dry_run=dry_run,
        project_config=getattr(args, "project_config", None),
        context_files=tuple(getattr(args, "context_file", []) or ()),
        skip_commit=bool(getattr(args, "skip_commit", False)),
        no_auto_repair_yaml=bool(getattr(args, "no_auto_repair_yaml", False)),
        max_yaml_repair_attempts=getattr(args, "max_yaml_repair_attempts", None),
        commit_hint=getattr(args, "commit_hint", None),
        commit_hint_file=getattr(args, "commit_hint_file", None),
        evidence_mode=getattr(args, "evidence_mode", None),
        max_identical_evidence_failures=getattr(
            args, "max_identical_evidence_failures", None
        ),
        evidence_batch_timeout_seconds=getattr(
            args, "evidence_batch_timeout_seconds", None
        ),
        force_reset=bool(getattr(args, "force_reset", False)),
    )


def _print_error(message: str, *, no_color: bool = False) -> None:
    prefix = "" if no_color else "\033[1;31m"
    suffix = "" if no_color else "\033[0m"
    print(f"{prefix}{message}{suffix}", file=sys.stderr)


def _print_info(message: str, *, no_color: bool = False) -> None:
    prefix = "" if no_color else "\033[1;34m"
    suffix = "" if no_color else "\033[0m"
    print(f"{prefix}{message}{suffix}")


def _exit_interrupted(exc: BaseException, *, no_color: bool) -> NoReturn:
    if isinstance(exc, UserInterrupted):
        _print_error(str(exc), no_color=no_color)
    else:
        _print_error("Interrupted — Cursor agent session terminated.", no_color=no_color)
    raise SystemExit(130) from exc


def _cmd_validate(args: argparse.Namespace) -> int:
    try:
        ws = load_workspace(args.workspace.resolve(), args.todos_dir)
    except ValidationError as exc:
        _print_error(str(exc))
        return 1
    print(f"OK {len(ws.items)} item(s) in {ws.todos_dir}")
    return 0


async def _cmd_dry_run(args: argparse.Namespace) -> int:
    config = _run_config_from_args(args)
    report = DryRunReport()
    try:
        await load_workspace_repairable(
            config,
            allow_repair=False,
            dry_run_report=report,
        )
    except ValidationError:
        if report.repair_required:
            _print_info(
                "YAML repair would be required:\n"
                f"{report.diagnostic}",
                no_color=config.no_color,
            )
            return 1
        _print_error(report.diagnostic or "Validation failed", no_color=config.no_color)
        return 1
    _print_info("Workspace valid; YAML repair not required.", no_color=config.no_color)
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    try:
        ws = load_workspace(args.workspace.resolve(), args.todos_dir)
    except ValidationError as exc:
        _print_error(str(exc), no_color=args.no_color)
        return 1

    auto_commit = ws.manifest.settings.auto_commit
    print(f"auto_commit={auto_commit}")
    print(
        f"{'ID':<12} {'Title':<24} {'Status':<12} {'Priority':<8} "
        f"{'Ready':<6} {'Commit':<8} Evidence Run phase"
    )
    for row in readiness_rows(ws):
        state = load_state(ws.runs_dir(row["id"]))
        phase = state.phase.value if state else "-"
        evidence = "-"
        if state and state.evidence_mode is not None:
            evidence = state.evidence_mode.value
            if state.evidence_identical_failure_count:
                evidence = f"{evidence} stall={state.evidence_identical_failure_count}"
            if state.last_transition and state.last_transition.value.startswith("evidence_"):
                evidence = f"{evidence} {state.last_transition.value.replace('evidence_', '')}"
        if state and state.logical_attempt:
            phase = f"{phase} a{state.logical_attempt}"
        if state and state.agent_pid:
            phase = f"{phase} pid={state.agent_pid}"
        print(
            f"{row['id']:<12} {row['title'][:24]:<24} {row['status']:<12} "
            f"{row['priority']:<8} {row['ready']:<6} {row['commit']:<8} "
            f"{evidence:<18} {phase}"
        )
    return 0


def _print_report(report, *, no_color: bool) -> int:
    _print_info(
        f"completed={report.completed} failed={report.failed} "
        f"retryable={report.retryable} blocked={report.blocked} "
        f"skipped={report.skipped} planned={report.planned}",
        no_color=no_color,
    )
    if report.failed or report.retryable or report.blocked:
        return 1
    return 0


async def _cmd_run(args: argparse.Namespace) -> int:
    config = _run_config_from_args(args)
    if config.dry_run:
        return await _cmd_dry_run(args)
    orch = Orchestrator(config)
    try:
        report = await orch.run(todo_id=args.todo)
    except (UserInterrupted, KeyboardInterrupt) as exc:
        _exit_interrupted(exc, no_color=config.no_color)
    except TodosToolError as exc:
        _print_error(str(exc), no_color=config.no_color)
        return 1
    return _print_report(report, no_color=config.no_color)


async def _cmd_resume(args: argparse.Namespace) -> int:
    config = _run_config_from_args(args)
    orch = Orchestrator(config)
    try:
        report = await orch.resume()
    except (UserInterrupted, KeyboardInterrupt) as exc:
        _exit_interrupted(exc, no_color=config.no_color)
    except TodosToolError as exc:
        _print_error(str(exc), no_color=config.no_color)
        return 1
    return _print_report(report, no_color=config.no_color)


async def _cmd_commit(args: argparse.Namespace) -> int:
    config = _run_config_from_args(args)
    orch = Orchestrator(config)
    try:
        sha = await orch.commit_item(args.todo)
    except SchedulingError as exc:
        _print_error(str(exc), no_color=config.no_color)
        return 1
    except TodosToolError as exc:
        _print_error(str(exc), no_color=config.no_color)
        return 1
    prefix = "" if config.no_color else "\033[32m"
    suffix = "" if config.no_color else "\033[0m"
    print(f"{prefix}Committed{suffix} {args.todo} as {sha[:8]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "validate":
        return _cmd_validate(args)
    if args.command == "status":
        return _cmd_status(args)
    if args.command == "run":
        return asyncio.run(_cmd_run(args))
    if args.command == "resume":
        return asyncio.run(_cmd_resume(args))
    if args.command == "commit":
        return asyncio.run(_cmd_commit(args))
    parser.error(f"Unknown command: {args.command}")
    return 2


def run() -> None:
    raise SystemExit(main())


# Stale console scripts may still import `app` from an older Typer entry point.
app = run


if __name__ == "__main__":
    run()
