"""Session-scoped CLI for render agents to record batch selection."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from top_down_planning.errors import PlanningToolError
from top_down_planning.persistence import write_json

ENV_BATCH_FILE = "RENDER_TOOL_BATCH_FILE"
ENV_ELIGIBLE_IDS = "RENDER_TOOL_ELIGIBLE_IDS"

app = typer.Typer(
    name="planning-render-tool",
    help="Record render batch selection for one authoring session.",
    add_completion=False,
    no_args_is_help=True,
)


class RenderToolError(PlanningToolError):
    """Invalid render-tool invocation or batch state."""


def build_session_env(
    *,
    batch_file: Path,
    eligible_ids: list[str],
) -> dict[str, str]:
    return {
        ENV_BATCH_FILE: str(batch_file.resolve()),
        ENV_ELIGIBLE_IDS: ",".join(eligible_ids),
    }


def _batch_file() -> Path:
    raw = os.environ.get(ENV_BATCH_FILE, "").strip()
    if not raw:
        raise RenderToolError(f"Missing required environment variable: {ENV_BATCH_FILE}")
    return Path(raw).resolve()


def _eligible_ids() -> set[str]:
    raw = os.environ.get(ENV_ELIGIBLE_IDS, "").strip()
    if not raw:
        return set()
    return {part.strip() for part in raw.split(",") if part.strip()}


def load_batch_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RenderToolError(f"Render batch manifest not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RenderToolError(f"Invalid render batch manifest {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RenderToolError("Render batch manifest must be a JSON object")
    return data


@app.command("select-batch")
def select_batch(
    node_id: Annotated[
        list[str],
        typer.Option("--node-id", help="Plan item id to include in this render batch"),
    ],
    purpose: Annotated[
        str,
        typer.Option("--purpose", help="Short description of this batch's goal"),
    ] = "",
) -> None:
    """Record the agent-selected render batch for this session."""
    if not node_id:
        raise RenderToolError("select-batch requires at least one --node-id")
    selected = {value.strip() for value in node_id if value.strip()}
    if not selected:
        raise RenderToolError("select-batch requires at least one non-empty --node-id")
    eligible = _eligible_ids()
    for item_id in selected:
        if eligible and item_id not in eligible:
            raise RenderToolError(
                f"Node {item_id} is not in the eligible item inventory for this session"
            )
    batch_file = _batch_file()
    payload = {
        "selected_items": sorted(selected),
        "purpose": purpose.strip(),
    }
    batch_file.parent.mkdir(parents=True, exist_ok=True)
    write_json(batch_file, payload)
    typer.echo(
        f"Selected render batch: {', '.join(sorted(selected))}"
        + (f" ({purpose.strip()})" if purpose.strip() else "")
    )


@app.command("status")
def status() -> None:
    """Show the current render batch manifest."""
    batch_file = _batch_file()
    if not batch_file.is_file():
        typer.echo(json.dumps({"finalized": False, "selected_items": []}, indent=2))
        return
    typer.echo(batch_file.read_text(encoding="utf-8"))


def main() -> None:
    try:
        app()
    except RenderToolError as exc:
        typer.echo(str(exc), err=True)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
