"""Typer CLI for the todos tool."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import NoReturn, Optional

import typer
from rich.console import Console
from rich.table import Table

from todos_tool import __version__
from todos_tool.errors import TodosToolError, UserInterrupted, ValidationError
from todos_tool.manifest import load_workspace
from todos_tool.orchestrator import Orchestrator, RunConfig
from todos_tool.persistence import load_state
from todos_tool.scheduler import readiness_rows

app = typer.Typer(
    name="todos-tool",
    help="Execute a structured todos/ workspace with Cursor Agent CLI.",
    add_completion=False,
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit(0)


def _exit_interrupted(exc: BaseException, *, no_color: bool) -> NoReturn:
    console = Console(no_color=no_color)
    if isinstance(exc, UserInterrupted):
        console.print(f"[yellow]{exc}[/]")
    else:
        console.print(
            "[yellow]Interrupted — Cursor agent session left running if still active.[/]"
        )
    raise typer.Exit(130) from exc


def _workspace_options(
    workspace: Path,
    todos_dir: str,
    allow_dirty: bool,
    no_color: bool,
    model: Optional[str],
    stop_on_failure: Optional[bool],
    agent_bin: Optional[str],
    skip_probe: bool,
) -> RunConfig:
    env_skip = os.environ.get("TODOS_TOOL_SKIP_PROBE", "").lower() in {
        "1",
        "true",
        "yes",
    }
    return RunConfig(
        workspace_root=workspace.resolve(),
        todos_dir=todos_dir,
        allow_dirty=allow_dirty,
        no_color=no_color,
        model=model,
        stop_on_failure=stop_on_failure,
        agent_bin=agent_bin,
        skip_probe=skip_probe or env_skip,
    )


@app.callback()
def main_callback(
    version: bool = typer.Option(
        False,
        "--version",
        help="Show version and exit",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """Execute a structured todos/ workspace with Cursor Agent CLI."""


@app.command("validate")
def validate_cmd(
    workspace: Path = typer.Option(Path("."), "--workspace"),
    todos_dir: str = typer.Option("todos", "--todos-dir"),
) -> None:
    """Validate schemas, files, dependencies, cycles, and duplicate IDs."""
    console = Console()
    try:
        ws = load_workspace(workspace.resolve(), todos_dir)
    except ValidationError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    console.print(
        f"[green]OK[/] {len(ws.items)} item(s) in {ws.todos_dir}"
    )


@app.command("status")
def status_cmd(
    workspace: Path = typer.Option(Path("."), "--workspace"),
    todos_dir: str = typer.Option("todos", "--todos-dir"),
    no_color: bool = typer.Option(False, "--no-color"),
) -> None:
    """Show item readiness and active execution state."""
    console = Console(no_color=no_color or False)
    try:
        ws = load_workspace(workspace.resolve(), todos_dir)
    except ValidationError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc

    table = Table(title="Todos status")
    table.add_column("ID")
    table.add_column("Title")
    table.add_column("Status")
    table.add_column("Priority")
    table.add_column("Ready")
    table.add_column("Run phase")

    for row in readiness_rows(ws):
        state = load_state(ws.runs_dir(row["id"]))
        phase = state.phase.value if state else "-"
        if state and state.logical_attempt:
            phase = f"{phase} a{state.logical_attempt}"
        if state and state.agent_pid:
            phase = f"{phase} pid={state.agent_pid}"
        table.add_row(
            row["id"],
            row["title"],
            row["status"],
            row["priority"],
            row["ready"],
            phase,
        )
    console.print(table)


@app.command("run")
def run_cmd(
    workspace: Path = typer.Option(Path("."), "--workspace"),
    todos_dir: str = typer.Option("todos", "--todos-dir"),
    todo: Optional[str] = typer.Option(None, "--todo", help="Execute one item id"),
    allow_dirty: bool = typer.Option(False, "--allow-dirty"),
    no_color: bool = typer.Option(False, "--no-color"),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help="Cursor model override (overrides manifest settings.model)",
    ),
    stop_on_failure: Optional[bool] = typer.Option(
        None,
        "--stop-on-failure/--no-stop-on-failure",
        help="Override manifest stop_on_failure",
    ),
    agent_bin: Optional[str] = typer.Option(
        None,
        "--agent-bin",
        help="Path to Cursor agent binary (default: agent/cursor-agent on PATH)",
        envvar="TODOS_TOOL_AGENT_BIN",
    ),
    skip_probe: bool = typer.Option(
        False,
        "--skip-probe",
        help="Skip probing agent --help for stream flags (use documented defaults)",
        envvar="TODOS_TOOL_SKIP_PROBE",
    ),
) -> None:
    """Execute ready items in dependency-safe order."""
    config = _workspace_options(
        workspace,
        todos_dir,
        allow_dirty,
        no_color,
        model,
        stop_on_failure,
        agent_bin,
        skip_probe,
    )
    orch = Orchestrator(config)
    try:
        report = asyncio.run(orch.run(todo_id=todo))
    except (UserInterrupted, KeyboardInterrupt) as exc:
        _exit_interrupted(exc, no_color=no_color)
    except TodosToolError as exc:
        Console(no_color=no_color).print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc

    console = Console(no_color=no_color)
    console.print(
        f"completed={report.completed} failed={report.failed} blocked={report.blocked}"
    )
    if report.failed or report.blocked:
        raise typer.Exit(1)


@app.command("resume")
def resume_cmd(
    workspace: Path = typer.Option(Path("."), "--workspace"),
    todos_dir: str = typer.Option("todos", "--todos-dir"),
    allow_dirty: bool = typer.Option(False, "--allow-dirty"),
    no_color: bool = typer.Option(False, "--no-color"),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help="Cursor model override (overrides manifest settings.model)",
    ),
    stop_on_failure: Optional[bool] = typer.Option(
        None,
        "--stop-on-failure/--no-stop-on-failure",
    ),
    agent_bin: Optional[str] = typer.Option(
        None,
        "--agent-bin",
        envvar="TODOS_TOOL_AGENT_BIN",
    ),
    skip_probe: bool = typer.Option(
        False,
        "--skip-probe",
        envvar="TODOS_TOOL_SKIP_PROBE",
    ),
) -> None:
    """Recover from persisted state and actual Git state."""
    config = _workspace_options(
        workspace,
        todos_dir,
        allow_dirty,
        no_color,
        model,
        stop_on_failure,
        agent_bin,
        skip_probe,
    )
    orch = Orchestrator(config)
    try:
        report = asyncio.run(orch.resume())
    except (UserInterrupted, KeyboardInterrupt) as exc:
        _exit_interrupted(exc, no_color=no_color)
    except TodosToolError as exc:
        Console(no_color=no_color).print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc

    console = Console(no_color=no_color)
    console.print(
        f"completed={report.completed} failed={report.failed} blocked={report.blocked}"
    )
    if report.failed or report.blocked:
        raise typer.Exit(1)


def run() -> None:
    app()


if __name__ == "__main__":
    app()
