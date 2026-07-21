"""Run configured validation commands independently of Cursor sessions."""

from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path

from todos_tool.models import Manifest, TodoItem, ValidationCommandResult

MAX_VALIDATION_OUTPUT_CHARS = 12_000


def _normalize_command(command: str) -> str:
    return " ".join(command.strip().split()).lower()


def resolve_validation_commands(manifest: Manifest, item: TodoItem) -> list[str]:
    """Resolve manifest project check plus item-specific commands, deduplicated."""
    commands: list[str] = []
    seen: set[str] = set()
    project_check = manifest.settings.project_check
    key = _normalize_command(project_check)
    seen.add(key)
    commands.append(project_check)
    for command in item.validation.commands:
        key = _normalize_command(command)
        if key not in seen:
            seen.add(key)
            commands.append(command)
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
