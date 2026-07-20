"""Cursor Agent CLI process adapter with streaming and recovery."""

from __future__ import annotations

import asyncio
import os
import shutil
import signal
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from todos_tool.console_renderer import ConsoleRenderer
from todos_tool.errors import CursorEnvironmentError, CursorSessionError
from todos_tool.event_normalizer import EventNormalizer
from todos_tool.persistence import append_ndjson
from todos_tool.stream_parser import NdjsonStreamParser

PhaseName = Literal["work", "review"]


@dataclass
class SessionResult:
    exit_code: int
    events: list[dict[str, Any]] = field(default_factory=list)
    assistant_text: str = ""
    timed_out: bool = False
    parse_errors: int = 0
    malformed: list[str] = field(default_factory=list)
    stderr_text: str = ""


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
    """Inspect ``agent --help`` and return supported streaming flags."""
    try:
        proc = await asyncio.create_subprocess_exec(
            agent_bin,
            "--help",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
    except (TimeoutError, OSError):
        # Probe is best-effort; fall back to documented Cursor flags.
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


def build_agent_args(
    *,
    workspace: Path,
    prompt: str,
    phase: PhaseName,
    model: str | None,
    stream_flags: list[str],
    force: bool = True,
) -> list[str]:
    args = [
        "-p",
        "--trust",
        "--workspace",
        str(workspace),
        *stream_flags,
    ]
    if force:
        args.append("--force")
    if phase == "review":
        args.extend(["--mode", "ask"])
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
        self.agent_bin = resolve_agent_bin(agent_bin)
        self.model = model
        self.no_color = no_color
        self.parse_error_threshold = parse_error_threshold
        self.skip_probe = skip_probe
        self._stream_flags = stream_flags
        self._probed = False

    async def ensure_ready(self) -> None:
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
        phase: PhaseName,
        timeout_seconds: int,
        events_path: Path | None = None,
        log_path: Path | None = None,
        renderer: ConsoleRenderer | None = None,
    ) -> SessionResult:
        await self.ensure_ready()
        assert self._stream_flags is not None

        args = build_agent_args(
            workspace=workspace,
            prompt=prompt,
            phase=phase,
            model=self.model,
            stream_flags=self._stream_flags,
        )
        renderer = renderer or ConsoleRenderer(no_color=self.no_color, log_path=log_path)
        parser = NdjsonStreamParser(parse_error_threshold=self.parse_error_threshold)
        normalizer = EventNormalizer()
        assistant_parts: list[str] = []
        all_events: list[dict[str, Any]] = []
        stderr_chunks: list[str] = []

        try:
            proc = await asyncio.create_subprocess_exec(
                self.agent_bin,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(workspace),
                start_new_session=True,
            )
        except OSError as exc:
            raise CursorEnvironmentError(f"Failed to start Cursor agent: {exc}") from exc

        timed_out = False

        async def read_stdout() -> None:
            assert proc.stdout is not None
            while True:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    break
                for event in parser.feed(chunk):
                    all_events.append(event)
                    if events_path is not None:
                        append_ndjson(events_path, event)
                    for normalized in normalizer.normalize(event):
                        renderer.render(normalized)
                        if normalized.category == "assistant":
                            assistant_parts.append(normalized.text)
                if parser.threshold_exceeded():
                    raise CursorSessionError(
                        f"Parse error threshold exceeded ({parser.parse_errors})",
                        recoverable=True,
                    )

        async def read_stderr() -> None:
            assert proc.stderr is not None
            while True:
                chunk = await proc.stderr.read(4096)
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="replace")
                stderr_chunks.append(text)
                renderer.warn(text.rstrip())

        try:
            await asyncio.wait_for(
                asyncio.gather(read_stdout(), read_stderr()),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            timed_out = True
            await _terminate_process_tree(proc)
        except CursorSessionError:
            await _terminate_process_tree(proc)
            raise

        for event in parser.finish():
            all_events.append(event)
            if events_path is not None:
                append_ndjson(events_path, event)
            for normalized in normalizer.normalize(event):
                renderer.render(normalized)
                if normalized.category == "assistant":
                    assistant_parts.append(normalized.text)

        exit_code = await proc.wait()
        stderr_text = "".join(stderr_chunks)
        _raise_if_environment_failure(exit_code, stderr_text, timed_out)

        result = SessionResult(
            exit_code=exit_code if not timed_out else 124,
            events=all_events,
            assistant_text="".join(assistant_parts),
            timed_out=timed_out,
            parse_errors=parser.parse_errors,
            malformed=list(parser.malformed),
            stderr_text=stderr_text,
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


async def _terminate_process_tree(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    pid = proc.pid
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
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
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass
    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except TimeoutError:
        pass
