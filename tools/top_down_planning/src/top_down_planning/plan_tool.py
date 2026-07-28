"""Transaction-scoped CLI for planning agents to record operations incrementally."""

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
from top_down_planning.models import AgentResponse, PlanState, PlanningOperation
from top_down_planning.persistence import write_json
from top_down_planning.prompts import _format_item_context
from top_down_planning import schema_docs

ENV_TXN_FILE = "PLANNING_TOOL_TXN_FILE"
ENV_SELECTED_IDS = "PLANNING_TOOL_SELECTED_IDS"
ENV_PLAN_FILE = "PLANNING_TOOL_PLAN_FILE"
ENV_PLAN_DIGEST = "PLANNING_TOOL_PLAN_DIGEST"
PLAN_TOOL_COMMAND_ENV = "PLANNING_TOOL_COMMAND"

_OPERATION_ADAPTER = TypeAdapter(PlanningOperation)

app = typer.Typer(
    name="planning-plan-tool",
    help="Record planning operations into a session transaction file.",
    add_completion=False,
    no_args_is_help=True,
)


class PlanToolError(PlanningToolError):
    """Invalid plan-tool invocation or transaction state."""


def resolve_plan_tool_command(*, explicit: str | None = None) -> str:
    """Return the shell command agents should invoke for this session."""
    if explicit and explicit.strip():
        return explicit.strip()
    env_command = os.environ.get(PLAN_TOOL_COMMAND_ENV, "").strip()
    if env_command:
        return env_command
    if shutil.which("planning-plan-tool"):
        return "planning-plan-tool"
    return f"{sys.executable} -m top_down_planning.plan_tool"


def plan_tool_argv(command: str, *args: str) -> list[str]:
    """Split a resolved plan-tool command into argv for subprocess use."""
    if " " in command.strip():
        return shlex.split(command) + list(args)
    return [command, *args]


def build_session_env(
    *,
    transaction_path: Path,
    selected_ids: list[str],
    plan_file: Path,
    plan_digest: str,
    plan_tool_command: str | None = None,
) -> dict[str, str]:
    """Environment variables scoped to one planning batch session."""
    command = resolve_plan_tool_command(explicit=plan_tool_command)
    return {
        ENV_TXN_FILE: str(transaction_path.resolve()),
        ENV_SELECTED_IDS: ",".join(selected_ids),
        ENV_PLAN_FILE: str(plan_file.resolve()),
        ENV_PLAN_DIGEST: plan_digest,
        PLAN_TOOL_COMMAND_ENV: command,
    }


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise PlanToolError(f"Missing required environment variable: {name}")
    return value


def _selected_ids() -> set[str]:
    raw = _require_env(ENV_SELECTED_IDS)
    ids = {part.strip() for part in raw.split(",") if part.strip()}
    if not ids:
        raise PlanToolError(f"{ENV_SELECTED_IDS} must list at least one node id")
    return ids


def _plan_file() -> Path:
    return Path(_require_env(ENV_PLAN_FILE)).resolve()


def _txn_file() -> Path:
    return Path(_require_env(ENV_TXN_FILE)).resolve()


def _draft_path(txn_file: Path) -> Path:
    return txn_file.with_suffix(txn_file.suffix + ".draft")


def _empty_draft() -> dict[str, Any]:
    return {"assessment": {"plan_complete": False, "summary": ""}, "operations": []}


def _load_draft(txn_file: Path) -> dict[str, Any]:
    draft_path = _draft_path(txn_file)
    if not draft_path.is_file():
        return _empty_draft()
    try:
        data = json.loads(draft_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlanToolError(f"Failed to read draft transaction: {exc}") from exc
    if not isinstance(data, dict):
        raise PlanToolError("Draft transaction must be a JSON object")
    data.setdefault("assessment", {"plan_complete": False, "summary": ""})
    data.setdefault("operations", [])
    return data


def _save_draft(txn_file: Path, payload: dict[str, Any]) -> None:
    draft_path = _draft_path(txn_file)
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(draft_path, payload)


def _clear_draft(txn_file: Path) -> None:
    draft_path = _draft_path(txn_file)
    if draft_path.is_file():
        draft_path.unlink()


def load_transaction(path: Path) -> AgentResponse:
    """Load a finalized planning transaction file."""
    if not path.is_file():
        raise PlanToolError(f"Transaction file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        response = AgentResponse.model_validate(data)
    except (OSError, json.JSONDecodeError, PydanticValidationError) as exc:
        raise PlanToolError(f"Invalid transaction file {path}: {exc}") from exc
    if not response.operations:
        raise PlanToolError(f"Transaction file {path} contains no operations")
    return response


def reset_transaction(txn_file: Path) -> None:
    """Remove draft and finalized transaction artifacts for a new attempt."""
    _clear_draft(txn_file)
    if txn_file.is_file():
        txn_file.unlink()


def _load_plan_state() -> PlanState:
    plan_path = _plan_file()
    if not plan_path.is_file():
        raise PlanToolError(f"Plan file not found: {plan_path}")
    try:
        data = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
        return PlanState.model_validate(data)
    except (OSError, yaml.YAMLError, ValueError) as exc:
        raise PlanToolError(f"Failed to load plan from {plan_path}: {exc}") from exc


def _expected_plan_digest() -> str:
    value = os.environ.get(ENV_PLAN_DIGEST, "").strip()
    if not value:
        raise PlanToolError(f"Missing required environment variable: {ENV_PLAN_DIGEST}")
    return value


def _validate_plan_digest(draft: dict[str, Any]) -> None:
    expected = _expected_plan_digest()
    recorded = draft.get("plan_digest")
    if isinstance(recorded, str) and recorded and recorded != expected:
        raise PlanToolError(
            f"Transaction plan_digest mismatch: expected {expected}, got {recorded}"
        )
    draft["plan_digest"] = expected
    draft["selected_items"] = sorted(_selected_ids())


def _draft_status(txn_file: Path) -> dict[str, Any]:
    draft = _load_draft(txn_file)
    operations = draft.get("operations") or []
    assessment = draft.get("assessment") or {}
    selected = _selected_ids()
    covered = {
        op.get("node_id")
        for op in operations
        if isinstance(op, dict) and isinstance(op.get("node_id"), str)
    }
    return {
        "transaction_file": str(txn_file),
        "finalized": txn_file.is_file(),
        "selected_ids": sorted(selected),
        "recorded_operations": len(operations),
        "covered_node_ids": sorted(covered),
        "missing_node_ids": sorted(selected - covered),
        "assessment": assessment,
        "plan_digest": draft.get("plan_digest"),
    }


@app.command("usage")
def usage_cmd() -> None:
    """Show the planning transaction workflow and discovery commands."""
    typer.echo(schema_docs.format_plan_tool_usage(plan_tool_command=resolve_plan_tool_command()))


@app.command("schema")
def schema_cmd(
    target: Annotated[
        str,
        typer.Option(
            "--target",
            help="Schema target: operation or transaction",
        ),
    ] = "operation",
    fmt: Annotated[
        str,
        typer.Option("--format", help="Output format: json or yaml"),
    ] = "json",
) -> None:
    """Show authoritative JSON Schema for planning operations."""
    if target not in {"operation", "transaction"}:
        raise PlanToolError("target must be 'operation' or 'transaction'")
    payload = schema_docs.operation_schema(target=target)  # type: ignore[arg-type]
    if fmt == "yaml":
        typer.echo(yaml.safe_dump(payload, sort_keys=False), nl=False)
    else:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True), nl=False)


@app.command("example")
def example_cmd(
    type_name: Annotated[
        str,
        typer.Option("--type", help="Example operation type"),
    ] = "mark_actionable",
    fmt: Annotated[
        str,
        typer.Option("--format", help="Output format: json or yaml"),
    ] = "json",
) -> None:
    """Show a minimal valid planning operation example."""
    examples = schema_docs.operation_examples()
    if type_name not in examples:
        known = ", ".join(sorted(examples))
        raise PlanToolError(f"Unknown example type {type_name!r}; known: {known}")
    payload = examples[type_name]
    if fmt == "yaml":
        typer.echo(yaml.safe_dump(payload, sort_keys=False), nl=False)
    else:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True), nl=False)


@app.command("validate")
def validate_cmd(
    json_payload: Annotated[
        str,
        typer.Option("--json", help="Planning operation JSON object"),
    ],
) -> None:
    """Validate a planning operation without recording it."""
    try:
        raw = json.loads(json_payload)
    except json.JSONDecodeError as exc:
        raise PlanToolError(f"Invalid operation JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise PlanToolError("Operation JSON must be an object")
    try:
        schema_docs.validate_operation(raw)
    except PydanticValidationError as exc:
        raise PlanToolError(f"Invalid planning operation: {exc}") from exc
    typer.echo("Valid planning operation.")


@app.command("show-context")
def show_context() -> None:
    """Print context for all selected planning nodes."""
    plan = _load_plan_state()
    selected = _selected_ids()
    parts: list[str] = []
    for node_id in sorted(selected):
        item = plan.item_by_id(node_id)
        if item is None:
            raise PlanToolError(f"Unknown selected node id: {node_id}")
        parts.append(_format_item_context(plan, item))
    typer.echo("\n\n".join(parts))


@app.command("status")
def status() -> None:
    """Show the current draft or finalized transaction state."""
    typer.echo(json.dumps(_draft_status(_txn_file()), indent=2))


@app.command("record-operation")
def record_operation(
    json_payload: Annotated[
        str,
        typer.Option("--json", help="Planning operation JSON object"),
    ],
) -> None:
    """Append one planning operation for an allowed selected node."""
    txn_file = _txn_file()
    selected = _selected_ids()
    try:
        raw = json.loads(json_payload)
    except json.JSONDecodeError as exc:
        raise PlanToolError(f"Invalid operation JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise PlanToolError("Operation JSON must be an object")

    node_id = raw.get("node_id")
    if not isinstance(node_id, str) or node_id not in selected:
        raise PlanToolError(
            f"Operation node_id must be one of the selected items: "
            f"{', '.join(sorted(selected))}"
        )

    try:
        operation = _OPERATION_ADAPTER.validate_python(raw)
    except PydanticValidationError as exc:
        raise PlanToolError(f"Invalid planning operation: {exc}") from exc

    draft = _load_draft(txn_file)
    _validate_plan_digest(draft)
    operations = draft.setdefault("operations", [])
    if not isinstance(operations, list):
        raise PlanToolError("Draft operations must be a list")
    for existing in operations:
        if isinstance(existing, dict) and existing.get("node_id") == node_id:
            raise PlanToolError(
                f"Operation already recorded for node {node_id}; "
                "run reset or finalize before replacing it"
            )
    operations.append(operation.model_dump(mode="json"))
    _save_draft(txn_file, draft)
    typer.echo(f"Recorded {operation.type} for {node_id}")


@app.command("set-assessment")
def set_assessment(
    plan_complete: Annotated[
        bool,
        typer.Option(
            "--plan-complete/--no-plan-complete",
            help="Whether planning is complete",
        ),
    ] = False,
    summary: Annotated[str, typer.Option(help="Planning assessment summary")] = "",
) -> None:
    """Set the session assessment metadata."""
    txn_file = _txn_file()
    draft = _load_draft(txn_file)
    draft["assessment"] = {
        "plan_complete": plan_complete,
        "summary": summary.strip(),
    }
    _save_draft(txn_file, draft)
    typer.echo("Assessment updated")


@app.command("reset")
def reset() -> None:
    """Clear the current draft and any finalized transaction file."""
    reset_transaction(_txn_file())
    typer.echo("Transaction reset")


@app.command("finalize")
def finalize() -> None:
    """Validate the draft and atomically write the finalized transaction file."""
    txn_file = _txn_file()
    draft = _load_draft(txn_file)
    _validate_plan_digest(draft)
    try:
        response = AgentResponse.model_validate(draft)
    except PydanticValidationError as exc:
        raise PlanToolError(f"Cannot finalize invalid transaction: {exc}") from exc

    if not response.operations:
        raise PlanToolError("Cannot finalize: at least one operation is required")

    selected = _selected_ids()
    covered = {operation.node_id for operation in response.operations}
    missing = selected - covered
    if missing:
        raise PlanToolError(
            "Cannot finalize: missing operations for selected nodes: "
            + ", ".join(sorted(missing))
        )

    expected = _expected_plan_digest()
    if response.plan_digest != expected:
        raise PlanToolError(
            f"Cannot finalize: plan_digest mismatch (expected {expected}, "
            f"got {response.plan_digest})"
        )

    txn_file.parent.mkdir(parents=True, exist_ok=True)
    write_json(txn_file, response.model_dump(mode="json"))
    _clear_draft(txn_file)
    typer.echo(f"Finalized transaction: {txn_file}")


def main() -> None:
    try:
        app()
    except PlanToolError as exc:
        typer.echo(str(exc), err=True)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
