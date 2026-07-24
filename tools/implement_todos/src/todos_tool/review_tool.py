"""Session-scoped CLI for review agents to submit structured decisions."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import sys
from pathlib import Path
from typing import Any

from todos_tool.errors import ReviewError
from todos_tool.models import ReviewDecision
from todos_tool.persistence import write_json
from todos_tool.review_scaffold import load_review_scaffold, validate_review_decision
from todos_tool.review_scaffold import SCAFFOLD_FILENAME

ENV_SUBMISSION_FILE = "TODOS_TOOL_REVIEW_SUBMISSION_FILE"
ENV_ITEM_ID = "TODOS_TOOL_ITEM_ID"
ENV_LOGICAL_ATTEMPT = "TODOS_TOOL_LOGICAL_ATTEMPT"
REVIEW_TOOL_COMMAND_ENV = "TODOS_TOOL_REVIEW_TOOL_COMMAND"


class ReviewToolError(ReviewError):
    """Invalid review-tool invocation or submission state."""


def resolve_review_tool_command(*, explicit: str | None = None) -> str:
    """Return the shell command agents should invoke for this session."""
    if explicit and explicit.strip():
        return explicit.strip()
    env_command = os.environ.get(REVIEW_TOOL_COMMAND_ENV, "").strip()
    if env_command:
        return env_command
    if shutil.which("todos-review-tool"):
        return "todos-review-tool"
    return f"{sys.executable} -m todos_tool.review_tool"


def review_tool_argv(command: str, *args: str) -> list[str]:
    """Split a resolved review-tool command into argv for subprocess use."""
    if " " in command.strip():
        return shlex.split(command) + list(args)
    return [command, *args]


def review_submission_path(attempt_dir: Path, session_number: int) -> Path:
    return attempt_dir / f"review-submission-{session_number}.json"


def build_session_env(
    *,
    submission_path: Path,
    item_id: str,
    logical_attempt: int,
    review_tool_command: str | None = None,
) -> dict[str, str]:
    """Environment variables scoped to one review session."""
    command = resolve_review_tool_command(explicit=review_tool_command)
    return {
        ENV_SUBMISSION_FILE: str(submission_path.resolve()),
        ENV_ITEM_ID: item_id,
        ENV_LOGICAL_ATTEMPT: str(logical_attempt),
        REVIEW_TOOL_COMMAND_ENV: command,
    }


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ReviewToolError(f"Missing required environment variable: {name}")
    return value


def _submission_file() -> Path:
    return Path(_require_env(ENV_SUBMISSION_FILE)).resolve()


def _session_scaffold_file() -> Path:
    return _submission_file().parent / SCAFFOLD_FILENAME


def _load_session_scaffold():
    return load_review_scaffold(_session_scaffold_file())


def _expected_item_id() -> str:
    return _require_env(ENV_ITEM_ID)


def _expected_logical_attempt() -> int:
    raw = _require_env(ENV_LOGICAL_ATTEMPT)
    try:
        return int(raw)
    except ValueError as exc:
        raise ReviewToolError(
            f"{ENV_LOGICAL_ATTEMPT} must be an integer, got {raw!r}"
        ) from exc


def _validate_identity(decision: ReviewDecision) -> None:
    expected_item = _expected_item_id()
    expected_attempt = _expected_logical_attempt()
    if decision.item_id != expected_item:
        raise ReviewToolError(
            f"Review item_id mismatch: got {decision.item_id!r}, "
            f"expected {expected_item!r}"
        )
    if decision.logical_attempt != expected_attempt:
        raise ReviewToolError(
            f"Review logical_attempt mismatch: got {decision.logical_attempt}, "
            f"expected {expected_attempt}"
        )


def reset_review_submission(path: Path) -> None:
    """Remove a prior submission artifact before a new review session."""
    if path.is_file():
        path.unlink()


def load_review_submission(path: Path) -> ReviewDecision:
    """Load a finalized review submission artifact."""
    if not path.is_file():
        raise ReviewToolError(f"Review submission artifact not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        decision = ReviewDecision.model_validate(data)
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        raise ReviewToolError(f"Invalid review submission artifact {path}: {exc}") from exc
    return decision


def _submission_status(path: Path) -> dict[str, Any]:
    status: dict[str, Any] = {
        "submission_file": str(path),
        "submitted": path.is_file(),
        "item_id": _expected_item_id(),
        "logical_attempt": _expected_logical_attempt(),
    }
    if path.is_file():
        try:
            decision = load_review_submission(path)
            status["decision"] = decision.decision
            status["summary"] = decision.summary
        except ReviewError as exc:
            status["error"] = str(exc)
    return status


def submit_review_decision(json_payload: str) -> ReviewDecision:
    """Validate and atomically write one review submission."""
    path = _submission_file()
    if path.is_file():
        raise ReviewToolError(
            f"Review submission already exists at {path}; "
            "run reset before submitting again"
        )
    try:
        raw = json.loads(json_payload)
    except json.JSONDecodeError as exc:
        raise ReviewToolError(f"Invalid review decision JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ReviewToolError("Review decision JSON must be an object")
    try:
        decision = ReviewDecision.model_validate(raw)
    except ValueError as exc:
        raise ReviewToolError(f"Invalid review decision: {exc}") from exc
    _validate_identity(decision)
    scaffold_file = _session_scaffold_file()
    if scaffold_file.is_file():
        validate_review_decision(load_review_scaffold(scaffold_file), decision)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, decision.model_dump(mode="json"))
    return decision


def cmd_scaffold() -> None:
    scaffold = _load_session_scaffold()
    print(json.dumps(scaffold.decision_template(), indent=2))


def cmd_validate(json_payload: str) -> None:
    scaffold = _load_session_scaffold()
    try:
        raw = json.loads(json_payload)
    except json.JSONDecodeError as exc:
        raise ReviewToolError(f"Invalid review decision JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ReviewToolError("Review decision JSON must be an object")
    try:
        decision = ReviewDecision.model_validate(raw)
    except ValueError as exc:
        raise ReviewToolError(f"Invalid review decision: {exc}") from exc
    _validate_identity(decision)
    validate_review_decision(scaffold, decision)
    print("Review decision is valid for submission.")


def cmd_submit(json_payload: str) -> None:
    decision = submit_review_decision(json_payload)
    print(f"Submitted review decision: {decision.decision}")


def cmd_status() -> None:
    print(json.dumps(_submission_status(_submission_file()), indent=2))


def cmd_reset() -> None:
    reset_review_submission(_submission_file())
    print("Review submission reset")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="todos-review-tool",
        description="Submit structured review decisions for todos-tool sessions.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    submit = subparsers.add_parser(
        "submit",
        help="Validate and write one review decision JSON object",
    )
    submit.add_argument(
        "--json",
        required=True,
        help="Review decision JSON object",
    )

    subparsers.add_parser("status", help="Show current submission artifact state")
    subparsers.add_parser("reset", help="Remove the current submission artifact")

    subparsers.add_parser(
        "scaffold",
        help="Print a fill-in review decision template with exact criterion strings",
    )

    validate = subparsers.add_parser(
        "validate",
        help="Validate review decision JSON without writing the submission artifact",
    )
    validate.add_argument(
        "--json",
        required=True,
        help="Review decision JSON object",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "submit":
            cmd_submit(args.json)
        elif args.command == "status":
            cmd_status()
        elif args.command == "reset":
            cmd_reset()
        elif args.command == "scaffold":
            cmd_scaffold()
        elif args.command == "validate":
            cmd_validate(args.json)
        else:
            parser.error(f"Unknown command: {args.command}")
            return 2
    except ReviewToolError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
