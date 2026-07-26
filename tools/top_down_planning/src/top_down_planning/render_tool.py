"""Transaction CLI for render batch agents."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from pydantic import TypeAdapter, ValidationError as PydanticValidationError

from top_down_planning.errors import PlanningToolError
from top_down_planning.models import RenderBatchArtifact, RenderBatchTransaction
from top_down_planning.persistence import write_json
from top_down_planning.render_manifest import FINAL_BATCH_ID

ENV_TXN_FILE = "PLANNING_RENDER_TXN_FILE"
ENV_BATCH_ID = "PLANNING_RENDER_BATCH_ID"
ENV_PLAN_DIGEST = "PLANNING_RENDER_PLAN_DIGEST"
ENV_OUTPUT_GOAL_DIGEST = "PLANNING_RENDER_OUTPUT_GOAL_DIGEST"
ENV_RENDER_CONFIG_DIGEST = "PLANNING_RENDER_RENDER_CONFIG_DIGEST"
RENDER_TOOL_COMMAND_ENV = "PLANNING_RENDER_TOOL_COMMAND"

_ARTIFACT_ADAPTER = TypeAdapter(RenderBatchArtifact)
_TRANSACTION_ADAPTER = TypeAdapter(RenderBatchTransaction)

app = typer.Typer(
    name="planning-render-tool",
    help="Record render batch artifacts into a session transaction file.",
    add_completion=False,
    no_args_is_help=True,
)


class RenderToolError(PlanningToolError):
    """Invalid render-tool invocation or transaction state."""


def resolve_render_tool_command(*, explicit: str | None = None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    env_command = os.environ.get(RENDER_TOOL_COMMAND_ENV, "").strip()
    if env_command:
        return env_command
    if shutil.which("planning-render-tool"):
        return "planning-render-tool"
    return f"{sys.executable} -m top_down_planning.render_tool"


def render_tool_argv(command: str, *args: str) -> list[str]:
    if " " in command.strip():
        return shlex.split(command) + list(args)
    return [command, *args]


def build_render_session_env(
    *,
    transaction_path: Path,
    batch_id: str,
    plan_digest: str,
    output_goal_digest: str,
    render_config_digest: str,
    render_tool_command: str | None = None,
) -> dict[str, str]:
    command = resolve_render_tool_command(explicit=render_tool_command)
    return {
        ENV_TXN_FILE: str(transaction_path.resolve()),
        ENV_BATCH_ID: batch_id,
        ENV_PLAN_DIGEST: plan_digest,
        ENV_OUTPUT_GOAL_DIGEST: output_goal_digest,
        ENV_RENDER_CONFIG_DIGEST: render_config_digest,
        RENDER_TOOL_COMMAND_ENV: command,
    }


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RenderToolError(f"Missing required environment variable: {name}")
    return value


def _txn_file() -> Path:
    return Path(_require_env(ENV_TXN_FILE)).resolve()


def _draft_path(txn_file: Path) -> Path:
    return txn_file.with_suffix(txn_file.suffix + ".draft")


def _empty_draft() -> dict[str, Any]:
    return {"artifacts": []}


def _load_draft(txn_file: Path) -> dict[str, Any]:
    draft_path = _draft_path(txn_file)
    if not draft_path.is_file():
        return _empty_draft()
    try:
        data = yaml.safe_load(draft_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RenderToolError(f"Failed to read draft transaction: {exc}") from exc
    if not isinstance(data, dict):
        raise RenderToolError("Draft transaction must be a mapping")
    data.setdefault("artifacts", [])
    return data


def _save_draft(txn_file: Path, draft: dict[str, Any]) -> None:
    draft_path = _draft_path(txn_file)
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text(
        yaml.safe_dump(draft, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def load_render_transaction(path: Path) -> RenderBatchTransaction:
    if not path.is_file():
        raise RenderToolError(f"Render transaction not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return _TRANSACTION_ADAPTER.validate_python(data)
    except (OSError, yaml.YAMLError, PydanticValidationError) as exc:
        raise RenderToolError(f"Invalid render transaction at {path}: {exc}") from exc


@app.command("record-artifact")
def record_artifact(
    json_payload: Annotated[str, typer.Option("--json")],
) -> None:
    txn_file = _txn_file()
    draft = _load_draft(txn_file)
    try:
        artifact = _ARTIFACT_ADAPTER.validate_json(json_payload)
    except PydanticValidationError as exc:
        raise RenderToolError(f"Invalid artifact JSON: {exc}") from exc
    draft["artifacts"].append(artifact.model_dump(mode="json"))
    _save_draft(txn_file, draft)
    typer.echo(f"Recorded artifact for {artifact.plan_item_id}")


@app.command("finalize")
def finalize() -> None:
    txn_file = _txn_file()
    batch_id = _require_env(ENV_BATCH_ID)
    draft = _load_draft(txn_file)
    artifacts = [
        RenderBatchArtifact.model_validate(entry)
        for entry in draft.get("artifacts", [])
    ]
    if not artifacts and batch_id != FINAL_BATCH_ID:
        raise RenderToolError("Intermediate batch must record at least one artifact")
    transaction = RenderBatchTransaction(
        batch_id=batch_id,
        plan_digest=_require_env(ENV_PLAN_DIGEST),
        output_goal_digest=_require_env(ENV_OUTPUT_GOAL_DIGEST),
        render_config_digest=_require_env(ENV_RENDER_CONFIG_DIGEST),
        artifacts=artifacts,
    )
    txn_file.parent.mkdir(parents=True, exist_ok=True)
    txn_file.write_text(
        yaml.safe_dump(transaction.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    draft_path = _draft_path(txn_file)
    if draft_path.is_file():
        draft_path.unlink()
    write_json(txn_file.with_suffix(".json"), transaction.model_dump(mode="json"))
    typer.echo("Render transaction finalized.")


@app.command("reset")
def reset() -> None:
    txn_file = _txn_file()
    draft_path = _draft_path(txn_file)
    if draft_path.is_file():
        draft_path.unlink()
    if txn_file.is_file():
        txn_file.unlink()
    typer.echo("Render transaction reset.")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
