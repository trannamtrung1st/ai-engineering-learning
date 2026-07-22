"""Driver-mode execution of item completion-evidence commands."""

from __future__ import annotations

import asyncio
import fnmatch
import os
import re
import signal
import time
from pathlib import Path

from todos_tool.errors import ValidationError
from todos_tool.evidence_matcher import normalize_cwd, normalize_command
from todos_tool.models import EvidenceCommandResult, EvidenceCommandSpec
from todos_tool.project_context import ProjectContext
MAX_EVIDENCE_OUTPUT_CHARS = 12_000


def _command_matches_pattern(command: str, pattern: str) -> bool:
    normalized = command.strip()
    if any(ch in pattern for ch in "*?[]"):
        return fnmatch.fnmatch(normalized, pattern)
    try:
        return re.search(pattern, normalized) is not None
    except re.error:
        return pattern in normalized


def _assert_commands_allowed(
    specs: list[EvidenceCommandSpec],
    project_context: ProjectContext | None,
) -> None:
    if project_context is None:
        return
    forbidden = project_context.evidence.forbidden_command_patterns
    if not forbidden:
        return
    blocked: list[str] = []
    for spec in specs:
        for pattern in forbidden:
            if _command_matches_pattern(spec.command, pattern):
                blocked.append(
                    f"{spec.command!r} matches forbidden pattern {pattern!r}"
                )
                break
    if blocked:
        raise ValidationError(blocked)


async def run_evidence_commands(
    workspace_root: Path,
    specs: list[EvidenceCommandSpec],
    *,
    timeout_seconds: int,
    batch_timeout_seconds: int | None = None,
    project_context: ProjectContext | None = None,
) -> list[EvidenceCommandResult]:
    """Run evidence commands sequentially from declared cwd values."""
    _assert_commands_allowed(specs, project_context)
    results: list[EvidenceCommandResult] = []
    batch_deadline: float | None = None
    if batch_timeout_seconds is not None:
        batch_deadline = time.monotonic() + batch_timeout_seconds

    for spec in specs:
        if batch_deadline is not None and time.monotonic() >= batch_deadline:
            results.append(
                EvidenceCommandResult(
                    command=spec.command,
                    cwd=normalize_cwd(spec.cwd),
                    passed=False,
                    source="driver",
                    exit_code=124,
                    summary=f"Evidence batch timed out after {batch_timeout_seconds}s",
                    match_kind="failed_run",
                )
            )
            continue

        per_timeout = spec.timeout_seconds or timeout_seconds
        if batch_deadline is not None:
            remaining = int(max(1, batch_deadline - time.monotonic()))
            per_timeout = min(per_timeout, remaining)

        results.append(
            await _run_evidence_command(
                workspace_root,
                spec,
                timeout_seconds=per_timeout,
            )
        )
    return results


async def _run_evidence_command(
    workspace_root: Path,
    spec: EvidenceCommandSpec,
    *,
    timeout_seconds: int,
) -> EvidenceCommandResult:
    cwd = normalize_cwd(spec.cwd)
    run_cwd = workspace_root if cwd == "." else (workspace_root / cwd).resolve()
    proc = await asyncio.create_subprocess_shell(
        spec.command,
        cwd=str(run_cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
    )
    timed_out = False
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
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

    passed = exit_code == 0
    return EvidenceCommandResult(
        command=spec.command,
        cwd=cwd,
        passed=passed,
        source="driver",
        exit_code=exit_code,
        summary=_bounded_output(output, limit=MAX_EVIDENCE_OUTPUT_CHARS),
        match_kind="exact" if passed else "failed_run",
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


def _bounded_output(output: str, *, limit: int) -> str:
    if len(output) <= limit:
        return output
    head = limit // 3
    tail = limit - head - 80
    return (
        output[:head]
        + f"\n... evidence output truncated ({len(output)} chars total) ...\n"
        + output[-tail:]
    )


def format_evidence_results(results: list[EvidenceCommandResult]) -> str:
    if not results:
        return "(no completion-evidence commands configured)"
    parts: list[str] = []
    for result in results:
        parts.extend(
            [
                f"$ {result.command}  # cwd={result.cwd} source={result.source}",
                f"passed={str(result.passed).lower()} exit_code={result.exit_code}",
                result.summary or "(no output)",
                "",
            ]
        )
    return "\n".join(parts).rstrip()


def evidence_result_key(result: EvidenceCommandResult) -> str:
    return f"{normalize_command(result.command)}@{normalize_cwd(result.cwd)}"
