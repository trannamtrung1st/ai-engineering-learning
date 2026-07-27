"""Transaction CLI for per-node render agents."""

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
from top_down_planning.models import (
    ArtifactIntent,
    DeferredTo,
    RenderDecisionKind,
    RenderNodeTransaction,
)
from top_down_planning.persistence import write_json

ENV_TXN_FILE = "PLANNING_RENDER_TXN_FILE"
ENV_NODE_ID = "PLANNING_RENDER_NODE_ID"
ENV_CONTEXT_DIGEST = "PLANNING_RENDER_CONTEXT_DIGEST"
ENV_PLAN_DIGEST = "PLANNING_RENDER_PLAN_DIGEST"
ENV_OUTPUT_GOAL_DIGEST = "PLANNING_RENDER_OUTPUT_GOAL_DIGEST"
ENV_RENDER_CONFIG_DIGEST = "PLANNING_RENDER_RENDER_CONFIG_DIGEST"
ENV_STAGING_DIR = "PLANNING_RENDER_STAGING_DIR"
RENDER_TOOL_COMMAND_ENV = "PLANNING_RENDER_TOOL_COMMAND"

_NODE_TRANSACTION_ADAPTER = TypeAdapter(RenderNodeTransaction)
_ARTIFACT_INTENT_ADAPTER = TypeAdapter(ArtifactIntent)

app = typer.Typer(
    name="planning-render-tool",
    help="Record per-node render artifacts into a session transaction file.",
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
    node_id: str,
    context_digest: str,
    plan_digest: str,
    output_goal_digest: str,
    render_config_digest: str,
    staging_dir: Path,
    render_tool_command: str | None = None,
) -> dict[str, str]:
    command = resolve_render_tool_command(explicit=render_tool_command)
    return {
        ENV_TXN_FILE: str(transaction_path.resolve()),
        ENV_NODE_ID: node_id,
        ENV_CONTEXT_DIGEST: context_digest,
        ENV_PLAN_DIGEST: plan_digest,
        ENV_OUTPUT_GOAL_DIGEST: output_goal_digest,
        ENV_RENDER_CONFIG_DIGEST: render_config_digest,
        ENV_STAGING_DIR: str(staging_dir.resolve()),
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
    return {"artifacts": [], "staged_files": {}, "resolves": []}


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
    data.setdefault("staged_files", {})
    data.setdefault("resolves", [])
    return data


def _save_draft(txn_file: Path, draft: dict[str, Any]) -> None:
    draft_path = _draft_path(txn_file)
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text(
        yaml.safe_dump(draft, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def load_render_node_transaction(path: Path) -> RenderNodeTransaction:
    if not path.is_file():
        raise RenderToolError(f"Render node transaction not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return _NODE_TRANSACTION_ADAPTER.validate_python(data)
    except (OSError, yaml.YAMLError, PydanticValidationError) as exc:
        raise RenderToolError(f"Invalid render node transaction at {path}: {exc}") from exc


@app.command("begin")
def begin(
    node_id: Annotated[str, typer.Option("--node-id")],
    context_digest: Annotated[str, typer.Option("--context-digest")],
) -> None:
    txn_file = _txn_file()
    draft = _empty_draft()
    draft["node_id"] = node_id
    draft["context_digest"] = context_digest
    draft["read_set_digest"] = context_digest
    _save_draft(txn_file, draft)
    typer.echo(f"Started render session for {node_id}")


@app.command("declare-artifact")
def declare_artifact(
    json_payload: Annotated[str, typer.Option("--json")],
) -> None:
    txn_file = _txn_file()
    draft = _load_draft(txn_file)
    try:
        intent = _ARTIFACT_INTENT_ADAPTER.validate_json(json_payload)
    except PydanticValidationError as exc:
        raise RenderToolError(f"Invalid artifact intent JSON: {exc}") from exc
    draft["artifacts"].append(intent.model_dump(mode="json"))
    _save_draft(txn_file, draft)
    typer.echo(f"Declared artifact {intent.artifact_key}")


@app.command("stage-artifact")
def stage_artifact(
    artifact_key: Annotated[str, typer.Option("--artifact-key")],
    content_file: Annotated[Path, typer.Option("--content-file")],
) -> None:
    txn_file = _txn_file()
    staging_dir = Path(_require_env(ENV_STAGING_DIR))
    draft = _load_draft(txn_file)
    if not content_file.is_file():
        raise RenderToolError(f"content file not found: {content_file}")
    content = content_file.read_text(encoding="utf-8")
    staged_path = staging_dir / artifact_key
    staged_path.parent.mkdir(parents=True, exist_ok=True)
    staged_path.write_text(content, encoding="utf-8")
    draft["staged_files"][artifact_key] = content
    _save_draft(txn_file, draft)
    typer.echo(f"Staged artifact {artifact_key}")


@app.command("record-decision")
def record_decision(
    decision: Annotated[str, typer.Option("--decision")],
    reason: Annotated[str, typer.Option("--reason")] = "",
    deferred_to_kind: Annotated[str | None, typer.Option("--deferred-to-kind")] = None,
    deferred_to_id: Annotated[str | None, typer.Option("--deferred-to-id")] = None,
    deferred_to_phase: Annotated[str | None, typer.Option("--deferred-to-phase")] = None,
) -> None:
    txn_file = _txn_file()
    draft = _load_draft(txn_file)
    try:
        decision_kind = RenderDecisionKind(decision)
    except ValueError as exc:
        raise RenderToolError(f"invalid decision: {decision}") from exc
    draft["decision"] = decision_kind.value
    draft["reason"] = reason
    if decision_kind == RenderDecisionKind.DEFER:
        if not deferred_to_kind or not deferred_to_id:
            raise RenderToolError("defer requires --deferred-to-kind and --deferred-to-id")
        draft["deferred_to"] = {
            "kind": deferred_to_kind,
            "id": deferred_to_id,
            "phase": deferred_to_phase,
        }
    _save_draft(txn_file, draft)
    typer.echo(f"Recorded decision {decision_kind.value}")


@app.command("submit")
def submit() -> None:
    txn_file = _txn_file()
    draft = _load_draft(txn_file)
    node_id = draft.get("node_id") or _require_env(ENV_NODE_ID)
    if "decision" not in draft:
        raise RenderToolError("record-decision must be called before submit")
    deferred_to = None
    if draft.get("deferred_to"):
        deferred_to = DeferredTo.model_validate(draft["deferred_to"])
    transaction = RenderNodeTransaction(
        transaction_id=f"txn-{node_id}-render",
        node_id=node_id,
        context_digest=draft.get("context_digest") or _require_env(ENV_CONTEXT_DIGEST),
        read_set_digest=draft.get("read_set_digest") or _require_env(ENV_CONTEXT_DIGEST),
        plan_digest=_require_env(ENV_PLAN_DIGEST),
        output_goal_digest=_require_env(ENV_OUTPUT_GOAL_DIGEST),
        render_config_digest=_require_env(ENV_RENDER_CONFIG_DIGEST),
        decision=RenderDecisionKind(draft["decision"]),
        reason=draft.get("reason", ""),
        deferred_to=deferred_to,
        resolves=list(draft.get("resolves", [])),
        artifacts=[
            ArtifactIntent.model_validate(entry) for entry in draft.get("artifacts", [])
        ],
        staged_files=dict(draft.get("staged_files", {})),
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
    typer.echo("Render node transaction submitted.")


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
