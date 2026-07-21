"""Cursor Agent CLI process adapter with streaming and recovery.

Adapted from tools/implement_todos/src/todos_tool/cursor_client.py.
Planning sessions always use ask/read-only mode.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from top_down_planning.console_renderer import ConsoleRenderer
from top_down_planning.errors import CursorEnvironmentError, CursorSessionError, UserInterrupted
from top_down_planning.event_normalizer import EventNormalizer
from top_down_planning.stream_parser import NdjsonStreamParser

AgentStartedCallback = Callable[[int], None]

PROMPT_FILE_ENV = "PLANNING_TOOL_PROMPT_FILE"


@dataclass
class SessionResult:
    exit_code: int
    events: list[dict[str, Any]] = field(default_factory=list)
    assistant_text: str = ""
    timed_out: bool = False
    parse_errors: int = 0
    malformed: list[str] = field(default_factory=list)
    stderr_text: str = ""
    agent_pid: int | None = None


def resolve_agent_bin(explicit: str | None = None) -> str:
    if explicit:
        path = shutil.which(explicit) or explicit
        if not (os.path.isfile(path) and os.access(path, os.X_OK)):
            raise CursorEnvironmentError(f"Cursor agent binary not executable: {explicit}")
        return path
    for name in ("agent", "cursor-agent"):
        found = shutil.which(name)
        if found:
            return found
    raise CursorEnvironmentError(
        "Cursor CLI not found. Install: curl https://cursor.com/install -fsS | bash "
        "then run: agent login"
    )


def default_stream_flags() -> list[str]:
    return ["--output-format", "stream-json", "--stream-partial-output"]


async def probe_stream_flags(agent_bin: str) -> list[str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            agent_bin,
            "--help",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
    except (TimeoutError, OSError):
        return default_stream_flags()

    help_text = (stdout or b"").decode("utf-8", errors="replace") + (
        stderr or b""
    ).decode("utf-8", errors="replace")
    flags: list[str] = []
    if "stream-json" in help_text or "--output-format" in help_text:
        flags.extend(["--output-format", "stream-json"])
    if "--stream-partial-output" in help_text:
        flags.append("--stream-partial-output")
    return flags or default_stream_flags()


def build_bootstrap_prompt(prompt_path: Path, workspace: Path) -> str:
    try:
        rel = prompt_path.relative_to(workspace)
        display_path = str(rel).replace("\\", "/")
    except ValueError:
        display_path = str(prompt_path)
    return (
        "Read and follow the complete instructions in the prompt file at "
        f"`{display_path}` (absolute: {prompt_path}). "
        "Open that file first and execute it exactly."
    )


def build_agent_args(
    *,
    workspace: Path,
    prompt: str,
    model: str | None,
    stream_flags: list[str],
) -> list[str]:
    args = [
        "-p",
        "--trust",
        "--workspace",
        str(workspace),
        *stream_flags,
        "--mode",
        "ask",
    ]
    if model:
        args.extend(["--model", model])
    args.append(prompt)
    return args


class CursorClient:
    def __init__(
        self,
        *,
        agent_bin: str | None = None,
        model: str | None = None,
        no_color: bool = False,
        parse_error_threshold: int = 20,
        skip_probe: bool = False,
        stream_flags: list[str] | None = None,
    ) -> None:
        self._agent_bin_explicit = agent_bin
        self._agent_bin: str | None = None
        self.model = model
        self.no_color = no_color
        self.parse_error_threshold = parse_error_threshold
        self.skip_probe = skip_probe
        self._stream_flags = stream_flags
        self._probed = False

    @property
    def agent_bin(self) -> str:
        if self._agent_bin is None:
            self._agent_bin = resolve_agent_bin(self._agent_bin_explicit)
        return self._agent_bin

    async def ensure_ready(self) -> None:
        _ = self.agent_bin
        if self._stream_flags is not None:
            self._probed = True
            return
        if self.skip_probe:
            self._stream_flags = default_stream_flags()
            self._probed = True
            return
        self._stream_flags = await probe_stream_flags(self.agent_bin)
        self._probed = True

    async def run_session(
        self,
        *,
        workspace: Path,
        prompt: str,
        timeout_seconds: int,
        events_path: Path | None = None,
        log_path: Path | None = None,
        prompt_path: Path | None = None,
        renderer: ConsoleRenderer | None = None,
        on_agent_started: AgentStartedCallback | None = None,
    ) -> SessionResult:
        await self.ensure_ready()
        assert self._stream_flags is not None

        if prompt_path is not None:
            prompt_arg = build_bootstrap_prompt(prompt_path, workspace)
        else:
            prompt_arg = prompt

        args = build_agent_args(
            workspace=workspace,
            prompt=prompt_arg,
            model=self.model,
            stream_flags=self._stream_flags,
        )
        renderer = renderer or ConsoleRenderer(no_color=self.no_color, log_path=log_path)
        parser = NdjsonStreamParser(parse_error_threshold=self.parse_error_threshold)
        normalizer = EventNormalizer()
        assistant_parts: list[str] = []
        all_events: list[dict[str, Any]] = []
        stderr_chunks: list[str] = []

        stdout_path, stderr_path, tmp_paths = _resolve_capture_paths(events_path, log_path)
        proc: subprocess.Popen[bytes] | None = None
        extra_env: dict[str, str] = {}
        if prompt_path is not None:
            extra_env[PROMPT_FILE_ENV] = str(prompt_path.resolve())

        try:
            proc = _spawn_agent(
                self.agent_bin,
                args,
                workspace=workspace,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                extra_env=extra_env,
            )
        except OSError as exc:
            _cleanup_tmp_paths(tmp_paths)
            raise CursorEnvironmentError(f"Failed to start Cursor agent: {exc}") from exc

        if on_agent_started is not None:
            on_agent_started(proc.pid)

        timed_out = False

        def handle_stdout_events(events: list[dict[str, Any]]) -> None:
            for event in events:
                all_events.append(event)
                for normalized in normalizer.normalize(event):
                    renderer.render(normalized)
                    if normalized.category == "assistant":
                        assistant_parts.append(normalized.text)
            if parser.threshold_exceeded():
                raise CursorSessionError(
                    f"Parse error threshold exceeded ({parser.parse_errors})",
                    recoverable=True,
                )

        def handle_stderr_text(text: str) -> None:
            if not text:
                return
            stderr_chunks.append(text)
            for line in text.splitlines():
                if line.strip():
                    renderer.warn(line.rstrip())

        try:
            await asyncio.wait_for(
                _watch_agent_output(
                    proc,
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    parser=parser,
                    on_events=handle_stdout_events,
                    on_stderr=handle_stderr_text,
                ),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            timed_out = True
            await _terminate_process_tree(proc)
        except CursorSessionError:
            await _terminate_process_tree(proc)
            raise
        except (asyncio.CancelledError, KeyboardInterrupt):
            renderer.flush()
            raise UserInterrupted(
                f"Interrupted; Cursor agent left running (pid={proc.pid})",
                agent_pid=proc.pid,
            ) from None

        for event in parser.finish():
            all_events.append(event)
            for normalized in normalizer.normalize(event):
                renderer.render(normalized)
                if normalized.category == "assistant":
                    assistant_parts.append(normalized.text)
        renderer.flush()

        exit_code = proc.poll()
        if exit_code is None:
            exit_code = await asyncio.to_thread(proc.wait)
        stderr_text = "".join(stderr_chunks)
        if not stderr_text and stderr_path.is_file():
            stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace")
        _raise_if_environment_failure(exit_code, stderr_text, timed_out)
        _cleanup_tmp_paths(tmp_paths)

        result = SessionResult(
            exit_code=exit_code if not timed_out else 124,
            events=all_events,
            assistant_text="".join(assistant_parts),
            timed_out=timed_out,
            parse_errors=parser.parse_errors,
            malformed=list(parser.malformed),
            stderr_text=stderr_text,
            agent_pid=proc.pid,
        )
        if timed_out:
            raise CursorSessionError(
                f"Cursor session timed out after {timeout_seconds}s",
                recoverable=True,
            )
        if exit_code != 0:
            raise CursorSessionError(
                f"Cursor session exited with code {exit_code}",
                recoverable=True,
            )
        return result


def _resolve_capture_paths(
    events_path: Path | None,
    log_path: Path | None,
) -> tuple[Path, Path, list[Path]]:
    tmp_paths: list[Path] = []
    if events_path is not None:
        stdout_path = events_path
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_bytes(b"")
    else:
        fd, name = tempfile.mkstemp(prefix="planning-agent-", suffix=".ndjson")
        os.close(fd)
        stdout_path = Path(name)
        tmp_paths.append(stdout_path)

    if log_path is not None:
        stderr_path = log_path.with_suffix(".stderr")
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_path.write_bytes(b"")
    else:
        fd, name = tempfile.mkstemp(prefix="planning-agent-", suffix=".stderr")
        os.close(fd)
        stderr_path = Path(name)
        tmp_paths.append(stderr_path)
    return stdout_path, stderr_path, tmp_paths


def _spawn_agent(
    agent_bin: str,
    args: list[str],
    *,
    workspace: Path,
    stdout_path: Path,
    stderr_path: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.Popen[bytes]:
    stdout_f: TextIO[bytes] = stdout_path.open("wb")
    stderr_f: TextIO[bytes] = stderr_path.open("wb")
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    try:
        return subprocess.Popen(
            [agent_bin, *args],
            stdout=stdout_f,
            stderr=stderr_f,
            cwd=str(workspace),
            start_new_session=True,
            env=env,
        )
    finally:
        stdout_f.close()
        stderr_f.close()


async def _watch_agent_output(
    proc: subprocess.Popen[bytes],
    *,
    stdout_path: Path,
    stderr_path: Path,
    parser: NdjsonStreamParser,
    on_events: Any,
    on_stderr: Any,
) -> None:
    stdout_offset = 0
    stderr_offset = 0
    while True:
        stdout_offset = _consume_file_bytes(
            stdout_path,
            stdout_offset,
            lambda data: on_events(parser.feed(data)),
        )
        stderr_offset = _consume_file_bytes(
            stderr_path,
            stderr_offset,
            lambda data: on_stderr(data.decode("utf-8", errors="replace")),
        )
        if proc.poll() is not None:
            stdout_offset = _consume_file_bytes(
                stdout_path,
                stdout_offset,
                lambda data: on_events(parser.feed(data)),
            )
            stderr_offset = _consume_file_bytes(
                stderr_path,
                stderr_offset,
                lambda data: on_stderr(data.decode("utf-8", errors="replace")),
            )
            return
        await asyncio.sleep(0.05)


def _consume_file_bytes(path: Path, offset: int, consumer: Any) -> int:
    if not path.is_file():
        return offset
    with path.open("rb") as handle:
        handle.seek(offset)
        data = handle.read()
    if data:
        consumer(data)
        return offset + len(data)
    return offset


def _cleanup_tmp_paths(paths: list[Path]) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _raise_if_environment_failure(
    exit_code: int,
    stderr_text: str,
    timed_out: bool,
) -> None:
    if timed_out:
        return
    lowered = stderr_text.lower()
    markers = (
        "not authenticated",
        "please run 'agent login'",
        "unauthorized",
        "authentication required",
        "api key",
        "cursor cli not found",
    )
    if any(marker in lowered for marker in markers):
        raise CursorEnvironmentError(
            f"Cursor environment failure (exit {exit_code}): {stderr_text.strip()}"
        )


async def _terminate_process_tree(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    pid = proc.pid
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.terminate()
        except ProcessLookupError:
            return
    if await _wait_proc(proc, timeout=5):
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass
    await _wait_proc(proc, timeout=5)


async def _wait_proc(proc: subprocess.Popen[bytes], *, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return True
        await asyncio.sleep(0.05)
    return proc.poll() is not None
