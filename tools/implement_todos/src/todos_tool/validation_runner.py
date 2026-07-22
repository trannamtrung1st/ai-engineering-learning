"""Run configured validation commands independently of Cursor sessions."""

from __future__ import annotations

import asyncio
import fnmatch
import os
import re
import signal
from pathlib import Path

from todos_tool.errors import ValidationError
from todos_tool.models import Manifest, TodoItem, ValidationCommandResult
from todos_tool.project_context import ProjectContext

MAX_VALIDATION_OUTPUT_CHARS = 12_000


def _normalize_command(command: str) -> str:
    return " ".join(command.strip().split()).lower()


def _command_matches_pattern(command: str, pattern: str) -> bool:
    normalized = command.strip()
    if any(ch in pattern for ch in "*?[]"):
        return fnmatch.fnmatch(normalized, pattern)
    try:
        return re.search(pattern, normalized) is not None
    except re.error:
        return pattern in normalized


def _assert_commands_allowed(
    commands: list[str],
    project_context: ProjectContext | None,
) -> None:
    if project_context is None:
        return
    forbidden = project_context.evidence.forbidden_command_patterns
    if not forbidden:
        return
    blocked: list[str] = []
    for command in commands:
        for pattern in forbidden:
            if _command_matches_pattern(command, pattern):
                blocked.append(f"{command!r} matches forbidden pattern {pattern!r}")
                break
    if blocked:
        raise ValidationError(blocked)


def resolve_validation_commands(
    manifest: Manifest,
    item: TodoItem,
    *,
    project_context: ProjectContext | None = None,
) -> list[str]:
    """Resolve profile, manifest, and item validation commands, deduplicated."""
    commands: list[str] = []
    seen: set[str] = set()

    def add(command: str) -> None:
        key = _normalize_command(command)
        if key not in seen:
            seen.add(key)
            commands.append(command)

    if project_context is not None:
        for command in project_context.evidence.required_commands:
            add(command)

    project_check = manifest.settings.project_check
    if project_check:
        add(project_check)

    for command in item.validation.commands:
        add(command)

    _assert_commands_allowed(commands, project_context)
    return commands


async def run_validation_commands(
    workspace_root: Path,
    commands: list[str],
    *,
    timeout_seconds: int,
) -> list[ValidationCommandResult]:
    """Run trusted workspace validation commands sequentially."""
    results: list[ValidationCommandResult] = []
    for command in commands:
        results.append(
            await _run_validation_command(
                workspace_root,
                command,
                timeout_seconds=timeout_seconds,
            )
        )
    return results


async def _run_validation_command(
    workspace_root: Path,
    command: str,
    *,
    timeout_seconds: int,
) -> ValidationCommandResult:
    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=str(workspace_root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
    )
    timed_out = False
    try:
        stdout, _ = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        timed_out = True
        await _terminate_process_tree(proc)
        stdout, _ = await proc.communicate()

    output = (stdout or b"").decode("utf-8", errors="replace").strip()
    if timed_out:
        output = (
            f"Timed out after {timeout_seconds}s."
            + (f"\n{output}" if output else "")
        )
        exit_code = 124
    else:
        exit_code = proc.returncode

    return ValidationCommandResult(
        command=command,
        passed=exit_code == 0,
        exit_code=exit_code,
        summary=_bounded_output(output),
    )


def format_validation_results(results: list[ValidationCommandResult]) -> str:
    """Render authoritative results for prompts and continuation context."""
    if not results:
        return "(no validation commands configured)"
    parts: list[str] = []
    for result in results:
        parts.extend(
            [
                f"$ {result.command}",
                f"passed={str(result.passed).lower()} exit_code={result.exit_code}",
                result.summary or "(no output)",
                "",
            ]
        )
    return "\n".join(parts).rstrip()


def _bounded_output(output: str) -> str:
    if len(output) <= MAX_VALIDATION_OUTPUT_CHARS:
        return output
    head = MAX_VALIDATION_OUTPUT_CHARS // 3
    tail = MAX_VALIDATION_OUTPUT_CHARS - head - 80
    return (
        output[:head]
        + f"\n... validation output truncated ({len(output)} chars total) ...\n"
        + output[-tail:]
    )


async def _terminate_process_tree(
    proc: asyncio.subprocess.Process,
) -> None:
    if proc.returncode is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.terminate()
        except ProcessLookupError:
            return
    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
        return
    except TimeoutError:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except ProcessLookupError:
            return
    await proc.wait()
