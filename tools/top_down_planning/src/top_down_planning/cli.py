"""Typer CLI for the top-down planning tool."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import NoReturn, Optional

import typer
from rich.console import Console

from top_down_planning import __version__
from top_down_planning.config_loader import merge_run_options, options_to_planning_limits
from top_down_planning.errors import PlanningToolError, ResumeError, UserInterrupted, ValidationError
from top_down_planning.input_loader import load_output_goal, load_stop_hint
from top_down_planning.model_config import resolve_model
from top_down_planning.models import DEFAULT_CURSOR_MODEL, DEFAULT_INLINE_EMBED_THRESHOLD
from top_down_planning.notifications import (
    notify_error,
    notify_interrupted,
    notify_planning_report,
    resolve_notify_enabled,
)
from top_down_planning.orchestrator import Orchestrator, RunConfig

app = typer.Typer(
    name="top-down-planning",
    help="Progressively decompose Markdown input into a structured plan via Cursor Agent CLI.",
    add_completion=False,
    no_args_is_help=True,
    invoke_without_command=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit(0)


def _cli_notify_override(*, notify: bool, no_notify: bool) -> bool | None:
    if no_notify:
        return False
    if notify:
        return True
    return None


def _exit_interrupted(
    exc: BaseException,
    *,
    no_color: bool,
    notify_enabled: bool = False,
) -> NoReturn:
    console = Console(no_color=no_color, stderr=True)
    if isinstance(exc, UserInterrupted):
        console.print(f"[yellow]{exc}[/]")
        notify_interrupted(enabled=notify_enabled, message=str(exc))
    else:
        console.print("[yellow]Interrupted — Cursor agent session terminated.[/]")
        notify_interrupted(enabled=notify_enabled)
    raise typer.Exit(130) from exc


def _resolve_run_goal(
    *,
    output_goal: str | None,
    output_goal_file: Path | None,
):
    try:
        return load_output_goal(inline=output_goal, goal_file=output_goal_file)
    except PlanningToolError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _resolve_stop_hint(
    *,
    stop_hint: str | None,
    stop_hint_file: Path | None,
):
    try:
        return load_stop_hint(inline=stop_hint, hint_file=stop_hint_file)
    except PlanningToolError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _execute_run(
    *,
    config_path: Path | None,
    input_path: Path | None,
    output_goal: str | None,
    output_goal_file: Path | None,
    stop_hint: str | None,
    stop_hint_file: Path | None,
    output_dir: Path | None,
    max_iterations: int | None,
    max_depth: int | None,
    max_items: int | None,
    batch_size: int | None,
    concurrent_batches: int | None,
    max_retries: int | None,
    resume: bool,
    stream_json: bool,
    workspace: Path | None,
    no_color: bool,
    model: Optional[str],
    agent_bin: Optional[str],
    skip_probe: bool,
    embed_threshold: Optional[int],
    notify: bool = False,
    no_notify: bool = False,
) -> None:
    cli_notify = _cli_notify_override(notify=notify, no_notify=no_notify)
    try:
        options = merge_run_options(
            config_path=config_path,
            input_path=input_path,
            output_dir=output_dir,
            output_goal=output_goal,
            output_goal_file=output_goal_file,
            stop_hint=stop_hint,
            stop_hint_file=stop_hint_file,
            workspace=workspace,
            max_iterations=max_iterations,
            max_depth=max_depth,
            max_items=max_items,
            batch_size=batch_size,
            concurrent_batches=concurrent_batches,
            max_retries=max_retries,
            resume=resume,
            stream_json=stream_json,
            no_color=no_color,
            notify=cli_notify,
            model=model,
            agent_bin=agent_bin,
            skip_probe=skip_probe,
            embed_threshold=embed_threshold,
        )
    except PlanningToolError as exc:
        raise typer.BadParameter(str(exc)) from exc

    notify_enabled = resolve_notify_enabled(
        cli_value=cli_notify,
        config_value=options.notify,
    )

    env_skip = os.environ.get("PLANNING_TOOL_SKIP_PROBE", "").lower() in {
        "1",
        "true",
        "yes",
    }
    limits = options_to_planning_limits(options)
    config = RunConfig(
        input_path=options.input_path,
        output_goal=_resolve_run_goal(
            output_goal=options.output_goal,
            output_goal_file=options.output_goal_file,
        ),
        output_dir=options.output_dir,
        workspace_root=options.workspace.resolve(),
        limits=limits,
        resume=options.resume,
        stream_json=options.stream_json,
        no_color=options.no_color,
        model=resolve_model(options.model),
        agent_bin=options.agent_bin,
        skip_probe=options.skip_probe or env_skip,
        embed_threshold=options.embed_threshold,
        stop_hint=_resolve_stop_hint(
            stop_hint=options.stop_hint,
            stop_hint_file=options.stop_hint_file,
        ),
        notify=notify_enabled,
        agent_context=options.agent_context,
    )
    orch = Orchestrator(config)
    try:
        report = asyncio.run(orch.run())
    except (UserInterrupted, KeyboardInterrupt) as exc:
        _exit_interrupted(exc, no_color=options.no_color, notify_enabled=notify_enabled)
    except (PlanningToolError, ResumeError, ValidationError) as exc:
        if not options.stream_json:
            Console(no_color=options.no_color, stderr=True).print(f"[red]{exc}[/]")
        notify_error(enabled=notify_enabled, message=str(exc))
        raise typer.Exit(1) from exc

    notify_planning_report(
        report,
        enabled=notify_enabled,
        render_fallback=report.render_fallback,
    )

    if not options.stream_json:
        console = Console(stderr=True)
        console.print(
            f"status={report.status.value} items={report.items} "
            f"actionable={report.actionable_items} blocked={report.blocked_items} "
            f"iterations={report.iterations} output={report.output_dir}"
        )
        if report.artifacts:
            console.print("artifacts:")
            for artifact in report.artifacts:
                console.print(f"  - {artifact}")
    if report.status.value not in {"complete"}:
        raise typer.Exit(1)


@app.callback()
def main_callback(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        help="Show version and exit",
        callback=_version_callback,
        is_eager=True,
    ),
    config_path: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="YAML config file with optional run settings (CLI flags override)",
        exists=True,
        dir_okay=False,
        readable=True,
    ),
    input_path: Optional[Path] = typer.Option(None, "--input", help="Primary Markdown input file"),
    output_goal: Optional[str] = typer.Option(
        None,
        "--output-goal",
        help="Short inline prompt describing the desired final plan",
    ),
    output_goal_file: Optional[Path] = typer.Option(
        None,
        "--output-goal-file",
        help="Markdown or text file describing the desired final plan",
    ),
    stop_hint: Optional[str] = typer.Option(
        None,
        "--stop-hint",
        help="Guidance for when to stop expanding vs mark items actionable",
    ),
    stop_hint_file: Optional[Path] = typer.Option(
        None,
        "--stop-hint-file",
        help="Markdown or text file with expansion stop guidance",
    ),
    output_dir: Optional[Path] = typer.Option(
        None,
        "--output",
        help="Output directory for resumable planning state (.planning-output/)",
    ),
    max_iterations: Optional[int] = typer.Option(None, "--max-iterations"),
    max_depth: Optional[int] = typer.Option(None, "--max-depth"),
    max_items: Optional[int] = typer.Option(None, "--max-items"),
    batch_size: Optional[int] = typer.Option(None, "--batch-size"),
    concurrent_batches: Optional[int] = typer.Option(None, "--concurrent-batches"),
    max_retries: Optional[int] = typer.Option(None, "--max-retries"),
    resume: bool = typer.Option(False, "--resume", help="Resume an existing planning run"),
    stream_json: bool = typer.Option(
        False,
        "--stream-json",
        help="Emit planning events as JSONL on stdout (logs go to stderr)",
    ),
    workspace: Optional[Path] = typer.Option(
        None,
        "--workspace",
        help="Workspace passed to Cursor Agent CLI",
    ),
    no_color: bool = typer.Option(False, "--no-color"),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help=f"Cursor model override (default: {DEFAULT_CURSOR_MODEL}; env: PLANNING_TOOL_MODEL)",
        envvar="PLANNING_TOOL_MODEL",
    ),
    agent_bin: Optional[str] = typer.Option(
        None,
        "--agent-bin",
        envvar="PLANNING_TOOL_AGENT_BIN",
    ),
    skip_probe: bool = typer.Option(
        False,
        "--skip-probe",
        envvar="PLANNING_TOOL_SKIP_PROBE",
    ),
    embed_threshold: Optional[int] = typer.Option(
        None,
        "--embed-threshold",
        min=0,
        help=(
            "Inline input and output-goal content in prompts when at or below this "
            f"character count; otherwise reference by path (default: "
            f"{DEFAULT_INLINE_EMBED_THRESHOLD}; env: PLANNING_TOOL_EMBED_THRESHOLD)"
        ),
        envvar="PLANNING_TOOL_EMBED_THRESHOLD",
    ),
    notify: bool = typer.Option(
        False,
        "--notify",
        help="Enable desktop notifications when the run finishes",
    ),
    no_notify: bool = typer.Option(
        False,
        "--no-notify",
        help="Disable desktop notifications",
    ),
) -> None:
    """Top-down planning via Cursor Agent CLI."""
    if ctx.invoked_subcommand is not None:
        return
    if config_path is None and (input_path is None or output_dir is None):
        raise typer.BadParameter(
            "Planning requires --input and --output, or --config with those fields "
            "(plus an output goal)."
        )
    _execute_run(
        config_path=config_path,
        input_path=input_path,
        output_goal=output_goal,
        output_goal_file=output_goal_file,
        stop_hint=stop_hint,
        stop_hint_file=stop_hint_file,
        output_dir=output_dir,
        max_iterations=max_iterations,
        max_depth=max_depth,
        max_items=max_items,
        batch_size=batch_size,
        concurrent_batches=concurrent_batches,
        max_retries=max_retries,
        resume=resume,
        stream_json=stream_json,
        workspace=workspace,
        no_color=no_color,
        model=model,
        agent_bin=agent_bin,
        skip_probe=skip_probe,
        embed_threshold=embed_threshold,
        notify=notify,
        no_notify=no_notify,
    )


@app.command("run")
def run_cmd(
    config_path: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="YAML config file with optional run settings (CLI flags override)",
        exists=True,
        dir_okay=False,
        readable=True,
    ),
    input_path: Optional[Path] = typer.Option(None, "--input", help="Primary Markdown input file"),
    output_goal: Optional[str] = typer.Option(
        None,
        "--output-goal",
        help="Short inline prompt describing the desired final plan",
    ),
    output_goal_file: Optional[Path] = typer.Option(
        None,
        "--output-goal-file",
        help="Markdown or text file describing the desired final plan",
    ),
    stop_hint: Optional[str] = typer.Option(
        None,
        "--stop-hint",
        help="Guidance for when to stop expanding vs mark items actionable",
    ),
    stop_hint_file: Optional[Path] = typer.Option(
        None,
        "--stop-hint-file",
        help="Markdown or text file with expansion stop guidance",
    ),
    output_dir: Optional[Path] = typer.Option(
        None,
        "--output",
        help="Output directory for resumable planning state (.planning-output/)",
    ),
    max_iterations: Optional[int] = typer.Option(None, "--max-iterations"),
    max_depth: Optional[int] = typer.Option(None, "--max-depth"),
    max_items: Optional[int] = typer.Option(None, "--max-items"),
    batch_size: Optional[int] = typer.Option(None, "--batch-size"),
    concurrent_batches: Optional[int] = typer.Option(None, "--concurrent-batches"),
    max_retries: Optional[int] = typer.Option(None, "--max-retries"),
    resume: bool = typer.Option(False, "--resume", help="Resume an existing planning run"),
    stream_json: bool = typer.Option(
        False,
        "--stream-json",
        help="Emit planning events as JSONL on stdout (logs go to stderr)",
    ),
    workspace: Optional[Path] = typer.Option(
        None,
        "--workspace",
        help="Workspace passed to Cursor Agent CLI",
    ),
    no_color: bool = typer.Option(False, "--no-color"),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help=f"Cursor model override (default: {DEFAULT_CURSOR_MODEL}; env: PLANNING_TOOL_MODEL)",
        envvar="PLANNING_TOOL_MODEL",
    ),
    agent_bin: Optional[str] = typer.Option(
        None,
        "--agent-bin",
        envvar="PLANNING_TOOL_AGENT_BIN",
    ),
    skip_probe: bool = typer.Option(
        False,
        "--skip-probe",
        envvar="PLANNING_TOOL_SKIP_PROBE",
    ),
    embed_threshold: Optional[int] = typer.Option(
        None,
        "--embed-threshold",
        min=0,
        help=(
            "Inline input and output-goal content in prompts when at or below this "
            f"character count; otherwise reference by path (default: "
            f"{DEFAULT_INLINE_EMBED_THRESHOLD}; env: PLANNING_TOOL_EMBED_THRESHOLD)"
        ),
        envvar="PLANNING_TOOL_EMBED_THRESHOLD",
    ),
    notify: bool = typer.Option(
        False,
        "--notify",
        help="Enable desktop notifications when the run finishes",
    ),
    no_notify: bool = typer.Option(
        False,
        "--no-notify",
        help="Disable desktop notifications",
    ),
) -> None:
    """Run or resume top-down planning."""
    _execute_run(
        config_path=config_path,
        input_path=input_path,
        output_goal=output_goal,
        output_goal_file=output_goal_file,
        stop_hint=stop_hint,
        stop_hint_file=stop_hint_file,
        output_dir=output_dir,
        max_iterations=max_iterations,
        max_depth=max_depth,
        max_items=max_items,
        batch_size=batch_size,
        concurrent_batches=concurrent_batches,
        max_retries=max_retries,
        resume=resume,
        stream_json=stream_json,
        workspace=workspace,
        no_color=no_color,
        model=model,
        agent_bin=agent_bin,
        skip_probe=skip_probe,
        embed_threshold=embed_threshold,
        notify=notify,
        no_notify=no_notify,
    )


def run() -> None:
    app()


if __name__ == "__main__":
    app()
