"""Typer CLI for the top-down planning tool."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import NoReturn, Optional

import typer
from rich.console import Console

from top_down_planning import __version__
from top_down_planning.errors import PlanningToolError, ResumeError, UserInterrupted, ValidationError
from top_down_planning.model_config import resolve_model
from top_down_planning.models import DEFAULT_CURSOR_MODEL, PlanningLimits
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


def _exit_interrupted(exc: BaseException, *, no_color: bool) -> NoReturn:
    console = Console(no_color=no_color, stderr=True)
    if isinstance(exc, UserInterrupted):
        console.print(f"[yellow]{exc}[/]")
    else:
        console.print(
            "[yellow]Interrupted — Cursor agent session left running if still active.[/]"
        )
    raise typer.Exit(130) from exc


def _execute_run(
    *,
    input_path: Path,
    output_goal: str,
    output_dir: Path,
    max_iterations: int,
    max_depth: int,
    max_items: int,
    batch_size: int,
    max_retries: int,
    resume: bool,
    stream_json: bool,
    workspace: Path,
    no_color: bool,
    model: Optional[str],
    agent_bin: Optional[str],
    skip_probe: bool,
) -> None:
    env_skip = os.environ.get("PLANNING_TOOL_SKIP_PROBE", "").lower() in {
        "1",
        "true",
        "yes",
    }
    limits = PlanningLimits(
        max_iterations=max_iterations,
        max_depth=max_depth,
        max_items=max_items,
        batch_size=batch_size,
        max_retries=max_retries,
    )
    config = RunConfig(
        input_path=input_path,
        output_goal=output_goal,
        output_dir=output_dir,
        workspace_root=workspace.resolve(),
        limits=limits,
        resume=resume,
        stream_json=stream_json,
        no_color=no_color,
        model=resolve_model(model),
        agent_bin=agent_bin,
        skip_probe=skip_probe or env_skip,
    )
    orch = Orchestrator(config)
    try:
        report = asyncio.run(orch.run())
    except (UserInterrupted, KeyboardInterrupt) as exc:
        _exit_interrupted(exc, no_color=no_color)
    except (PlanningToolError, ResumeError, ValidationError) as exc:
        if not stream_json:
            Console(no_color=no_color, stderr=True).print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc

    if not stream_json:
        console = Console(stderr=True)
        console.print(
            f"status={report.status.value} items={report.items} "
            f"actionable={report.actionable_items} blocked={report.blocked_items} "
            f"iterations={report.iterations} output={report.output_dir}"
        )
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
    input_path: Optional[Path] = typer.Option(None, "--input", help="Primary Markdown input file"),
    output_goal: Optional[str] = typer.Option(
        None,
        "--output-goal",
        help="Short prompt describing the desired final plan",
    ),
    output_dir: Optional[Path] = typer.Option(
        None,
        "--output",
        help="Output directory for plan artifacts",
    ),
    max_iterations: int = typer.Option(50, "--max-iterations"),
    max_depth: int = typer.Option(6, "--max-depth"),
    max_items: int = typer.Option(200, "--max-items"),
    batch_size: int = typer.Option(3, "--batch-size"),
    max_retries: int = typer.Option(3, "--max-retries"),
    resume: bool = typer.Option(False, "--resume", help="Resume an existing planning run"),
    stream_json: bool = typer.Option(
        False,
        "--stream-json",
        help="Emit planning events as JSONL on stdout (logs go to stderr)",
    ),
    workspace: Path = typer.Option(
        Path("."),
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
) -> None:
    """Top-down planning via Cursor Agent CLI."""
    if ctx.invoked_subcommand is not None:
        return
    if input_path is None or output_goal is None or output_dir is None:
        raise typer.BadParameter(
            "Planning requires --input, --output-goal, and --output "
            "(or use the explicit `run` subcommand)."
        )
    _execute_run(
        input_path=input_path,
        output_goal=output_goal,
        output_dir=output_dir,
        max_iterations=max_iterations,
        max_depth=max_depth,
        max_items=max_items,
        batch_size=batch_size,
        max_retries=max_retries,
        resume=resume,
        stream_json=stream_json,
        workspace=workspace,
        no_color=no_color,
        model=resolve_model(model),
        agent_bin=agent_bin,
        skip_probe=skip_probe,
    )


@app.command("run")
def run_cmd(
    input_path: Path = typer.Option(..., "--input", help="Primary Markdown input file"),
    output_goal: str = typer.Option(
        ...,
        "--output-goal",
        help="Short prompt describing the desired final plan",
    ),
    output_dir: Path = typer.Option(..., "--output", help="Output directory for plan artifacts"),
    max_iterations: int = typer.Option(50, "--max-iterations"),
    max_depth: int = typer.Option(6, "--max-depth"),
    max_items: int = typer.Option(200, "--max-items"),
    batch_size: int = typer.Option(3, "--batch-size"),
    max_retries: int = typer.Option(3, "--max-retries"),
    resume: bool = typer.Option(False, "--resume", help="Resume an existing planning run"),
    stream_json: bool = typer.Option(
        False,
        "--stream-json",
        help="Emit planning events as JSONL on stdout (logs go to stderr)",
    ),
    workspace: Path = typer.Option(
        Path("."),
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
) -> None:
    """Run or resume top-down planning."""
    _execute_run(
        input_path=input_path,
        output_goal=output_goal,
        output_dir=output_dir,
        max_iterations=max_iterations,
        max_depth=max_depth,
        max_items=max_items,
        batch_size=batch_size,
        max_retries=max_retries,
        resume=resume,
        stream_json=stream_json,
        workspace=workspace,
        no_color=no_color,
        model=resolve_model(model),
        agent_bin=agent_bin,
        skip_probe=skip_probe,
    )


def run() -> None:
    app()


if __name__ == "__main__":
    app()
