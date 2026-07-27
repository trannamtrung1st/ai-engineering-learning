"""Transaction CLI for whole-plan review and final confirmation sessions."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from pathlib import Path
from typing import Annotated, Any, Literal

import typer
from pydantic import TypeAdapter, ValidationError as PydanticValidationError

from top_down_planning.errors import PlanningToolError
from top_down_planning.models import (
    FinalConfirmationResult,
    RenderBatchReviewResult,
    RenderedOutputReviewResult,
    WholePlanReviewResult,
)
from top_down_planning.persistence import write_json

ENV_RESULT_FILE = "PLANNING_REVIEW_RESULT_FILE"
ENV_STAGE = "PLANNING_REVIEW_STAGE"
ENV_REVIEW_PASS = "PLANNING_REVIEW_PASS"
REVIEW_TOOL_COMMAND_ENV = "PLANNING_REVIEW_TOOL_COMMAND"

StageName = Literal["whole_plan_review", "final_confirmation", "rendered_output_review", "render_batch_review"]
_RESULT_ADAPTERS: dict[StageName, TypeAdapter[Any]] = {
    "whole_plan_review": TypeAdapter(WholePlanReviewResult),
    "final_confirmation": TypeAdapter(FinalConfirmationResult),
    "rendered_output_review": TypeAdapter(RenderedOutputReviewResult),
    "render_batch_review": TypeAdapter(RenderBatchReviewResult),
}

app = typer.Typer(
    name="planning-review-tool",
    help="Record structured review or confirmation results.",
    add_completion=False,
    no_args_is_help=True,
)


class ReviewToolError(PlanningToolError):
    """Invalid review-tool invocation or result state."""


def resolve_review_tool_command(*, explicit: str | None = None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    env_command = os.environ.get(REVIEW_TOOL_COMMAND_ENV, "").strip()
    if env_command:
        return env_command
    if shutil.which("planning-review-tool"):
        return "planning-review-tool"
    return f"{sys.executable} -m top_down_planning.review_tool"


def review_tool_argv(command: str, *args: str) -> list[str]:
    if " " in command.strip():
        return shlex.split(command) + list(args)
    return [command, *args]


def build_review_session_env(
    *,
    result_path: Path,
    stage: StageName,
    review_tool_command: str | None = None,
    review_pass: int | None = None,
) -> dict[str, str]:
    command = resolve_review_tool_command(explicit=review_tool_command)
    env = {
        ENV_RESULT_FILE: str(result_path.resolve()),
        ENV_STAGE: stage,
        REVIEW_TOOL_COMMAND_ENV: command,
    }
    if review_pass is not None:
        env[ENV_REVIEW_PASS] = str(review_pass)
    return env


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ReviewToolError(f"Missing required environment variable: {name}")
    return value


def _result_file() -> Path:
    return Path(_require_env(ENV_RESULT_FILE)).resolve()


def _stage() -> StageName:
    raw = _require_env(ENV_STAGE)
    if raw not in _RESULT_ADAPTERS:
        raise ReviewToolError(
            f"Invalid {ENV_STAGE}: {raw!r} "
            "(expected whole_plan_review, final_confirmation, rendered_output_review, or render_batch_review)"
        )
    return raw  # type: ignore[return-value]


def _draft_path(result_file: Path) -> Path:
    return result_file.with_suffix(result_file.suffix + ".draft")


def _load_draft(result_file: Path) -> dict[str, Any]:
    draft_path = _draft_path(result_file)
    if not draft_path.is_file():
        return {}
    try:
        data = json.loads(draft_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewToolError(f"Failed to read draft review result: {exc}") from exc
    if not isinstance(data, dict):
        raise ReviewToolError("Draft review result must be a JSON object")
    return data


def _save_draft(result_file: Path, payload: dict[str, Any]) -> None:
    draft_path = _draft_path(result_file)
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(draft_path, payload)


def _clear_draft(result_file: Path) -> None:
    draft_path = _draft_path(result_file)
    if draft_path.is_file():
        draft_path.unlink()


def reset_review_result(result_path: Path) -> None:
    _clear_draft(result_path)
    if result_path.is_file():
        result_path.unlink()


def load_review_result(
    path: Path,
    *,
    stage: StageName,
) -> (
    WholePlanReviewResult
    | FinalConfirmationResult
    | RenderedOutputReviewResult
    | RenderBatchReviewResult
):
    if not path.is_file():
        raise ReviewToolError(f"Review result file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return _RESULT_ADAPTERS[stage].validate_python(data)
    except (OSError, json.JSONDecodeError, PydanticValidationError) as exc:
        raise ReviewToolError(f"Invalid review result file {path}: {exc}") from exc


@app.command("status")
def status() -> None:
    result_file = _result_file()
    typer.echo(
        json.dumps(
            {
                "result_file": str(result_file),
                "stage": _stage(),
                "finalized": result_file.is_file(),
                "has_draft": _draft_path(result_file).is_file(),
            },
            indent=2,
        )
    )


@app.command("set-result")
def set_result(
    json_payload: Annotated[
        str,
        typer.Option("--json", help="Structured review or confirmation result JSON"),
    ],
) -> None:
    stage = _stage()
    result_file = _result_file()
    try:
        raw = json.loads(json_payload)
    except json.JSONDecodeError as exc:
        raise ReviewToolError(f"Invalid result JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ReviewToolError("Result JSON must be an object")
    raw.setdefault("stage", stage)
    if raw.get("stage") != stage:
        raise ReviewToolError(
            f"Result stage must be {stage!r}, got {raw.get('stage')!r}"
        )
    try:
        validated = _RESULT_ADAPTERS[stage].validate_python(raw)
    except PydanticValidationError as exc:
        raise ReviewToolError(f"Invalid structured result: {exc}") from exc
    _save_draft(result_file, validated.model_dump(mode="json"))
    typer.echo(f"Draft {stage} result saved")


@app.command("reset")
def reset() -> None:
    reset_review_result(_result_file())
    typer.echo("Review result reset")


@app.command("finalize")
def finalize() -> None:
    stage = _stage()
    result_file = _result_file()
    draft = _load_draft(result_file)
    if not draft:
        raise ReviewToolError("Cannot finalize: no draft result recorded")
    try:
        validated = _RESULT_ADAPTERS[stage].validate_python(draft)
    except PydanticValidationError as exc:
        raise ReviewToolError(f"Cannot finalize invalid result: {exc}") from exc
    result_file.parent.mkdir(parents=True, exist_ok=True)
    write_json(result_file, validated.model_dump(mode="json"))
    _clear_draft(result_file)
    typer.echo(f"Finalized review result: {result_file}")


def main() -> None:
    try:
        app()
    except ReviewToolError as exc:
        typer.echo(str(exc), err=True)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
