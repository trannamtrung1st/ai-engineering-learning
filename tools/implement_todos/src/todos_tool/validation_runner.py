"""Run configured validation commands independently of Cursor sessions."""

from __future__ import annotations

import asyncio
import fnmatch
import json
import os
import re
import signal
from pathlib import Path

from todos_tool.errors import ValidationError
from todos_tool.models import Manifest, TodoItem, ValidationCommandResult
from todos_tool.project_context import ProjectContext

MAX_VALIDATION_OUTPUT_CHARS = 12_000

_FORMAT_CHECK_MARKERS = (
    "format:check",
    "oxfmt --check",
    "format issues found",
    "checking formatting",
)
_TYPECHECK_FAILURE_MARKERS = ("error ts",)


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


def validation_commands_imply_format_check(commands: list[str]) -> bool:
    blob = " ".join(commands).lower()
    if any(marker in blob for marker in _FORMAT_CHECK_MARKERS):
        return True
    normalized_commands = {_normalize_command(command) for command in commands}
    return normalized_commands.intersection(
        {
            "pnpm run check",
            "npm run check",
            "yarn run check",
            "yarn check",
        }
    ) != set()


def infer_format_fix_commands(
    workspace_root: Path,
    validation_commands: list[str],
) -> list[str]:
    """Derive formatter fix commands from configured validation commands."""
    if not validation_commands_imply_format_check(validation_commands):
        return []

    fixes: list[str] = []
    seen: set[str] = set()

    def add(command: str) -> None:
        key = _normalize_command(command)
        if key not in seen:
            seen.add(key)
            fixes.append(command)

    package_json = workspace_root / "package.json"
    if package_json.is_file():
        if (workspace_root / "pnpm-lock.yaml").is_file():
            add("pnpm run format")
        elif (workspace_root / "package-lock.json").is_file():
            add("npm run format")
        elif (workspace_root / "yarn.lock").is_file():
            add("yarn format")

    for command in validation_commands:
        if "oxfmt --check" in command:
            add(re.sub(r"oxfmt\s+--check\b", "oxfmt", command))
        if "format:check" in command and "pnpm run format:check" in command:
            add(command.replace("format:check", "format"))
        if "format:check" in command and "npm run format:check" in command:
            add(command.replace("format:check", "format"))
        if "pnpm exec oxfmt --check" in command:
            add(command.replace("pnpm exec oxfmt --check", "pnpm exec oxfmt"))
        if "npx oxfmt --check" in command:
            add(command.replace("npx oxfmt --check", "npx oxfmt"))

    return fixes


def is_format_only_validation_failure(
    results: list[ValidationCommandResult],
) -> bool:
    """Return True when failures look limited to formatting checks."""
    failed = [result for result in results if not result.passed]
    if not failed:
        return False

    for result in failed:
        summary = (result.summary or "").lower()
        if any(marker in summary for marker in _TYPECHECK_FAILURE_MARKERS):
            return False
        if re.search(r"found \d+ errors?\.", summary) and "format" not in summary:
            return False
        if not any(marker in summary for marker in _FORMAT_CHECK_MARKERS):
            return False
    return True


async def run_validation_preflight(
    workspace_root: Path,
    validation_commands: list[str],
    *,
    timeout_seconds: int,
) -> list[ValidationCommandResult]:
    """Run formatter fix commands before the authoritative validation gate."""
    fix_commands = infer_format_fix_commands(workspace_root, validation_commands)
    if not fix_commands:
        return []
    return await run_validation_commands(
        workspace_root,
        fix_commands,
        timeout_seconds=timeout_seconds,
    )


async def run_mechanical_format_repair(
    workspace_root: Path,
    validation_commands: list[str],
    *,
    timeout_seconds: int,
) -> list[ValidationCommandResult]:
    """Apply formatter fixes and rerun validation without an agent repair session."""
    fix_commands = infer_format_fix_commands(workspace_root, validation_commands)
    if not fix_commands:
        return []
    await run_validation_commands(
        workspace_root,
        fix_commands,
        timeout_seconds=timeout_seconds,
    )
    return await run_validation_commands(
        workspace_root,
        validation_commands,
        timeout_seconds=timeout_seconds,
    )


def load_persisted_validation_results(
    attempt_dir: Path,
    *,
    validation_repair_count: int,
) -> list[ValidationCommandResult]:
    """Load the most recent validation artifact for repair prompts/resume."""
    candidates: list[Path] = []
    if validation_repair_count:
        candidates.append(
            attempt_dir / f"validation-results-repair-{validation_repair_count}.json"
        )
    candidates.append(attempt_dir / "validation-results.json")
    for path in candidates:
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            continue
        parsed: list[ValidationCommandResult] = []
        for entry in raw_results:
            if isinstance(entry, dict):
                parsed.append(ValidationCommandResult.from_dict(entry))
        if parsed:
            return parsed
    return []


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
