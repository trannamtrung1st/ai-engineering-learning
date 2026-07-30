"""Invocation and presentation options separate from semantic run configuration."""

from __future__ import annotations

from argparse import Namespace
from dataclasses import dataclass
from typing import Any

from core_tools.cli import ResolvedRunsDir

from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.observability import ObservabilityOptions

_DEFAULT_OBSERVABILITY = dict(DEFAULT_CONFIG["observability"])


def _observability_defaults() -> dict[str, Any]:
    return dict(_DEFAULT_OBSERVABILITY)


def observability_options_from_args_and_config(
    args: Namespace,
    *,
    resolved_config: dict[str, Any] | None = None,
) -> ObservabilityOptions:
    """Merge observability with precedence: defaults < YAML < --set < explicit CLI."""

    config = resolved_config or {}
    observability_cfg = dict(_observability_defaults())
    yaml_obs = config.get("observability")
    if isinstance(yaml_obs, dict):
        observability_cfg.update(yaml_obs)

    if getattr(args, "no_color", False):
        color = "never"
    elif getattr(args, "color", None) is not None:
        color = args.color
    else:
        color = observability_cfg.get("color", "auto")

    log_level = (
        args.log_level
        if getattr(args, "log_level", None) is not None
        else observability_cfg.get("log_level", "normal")
    )
    log_format = (
        args.log_format
        if getattr(args, "log_format", None) is not None
        else observability_cfg.get("log_format", "console")
    )

    timestamps_arg = getattr(args, "timestamps", None)
    if timestamps_arg is not None:
        show_timestamps = timestamps_arg
    else:
        show_timestamps = observability_cfg["show_timestamps"]

    agent_text_arg = getattr(args, "agent_text", None)
    if agent_text_arg is not None:
        no_agent_text = not agent_text_arg
    else:
        show_agent_text = observability_cfg.get("show_agent_text", True)
        no_agent_text = not show_agent_text

    transcript_arg = getattr(args, "agent_transcript", None)
    if transcript_arg is not None:
        agent_transcript = transcript_arg
    else:
        agent_transcript = observability_cfg.get("agent_transcript", False)

    return ObservabilityOptions(
        log_level=log_level,
        log_format=log_format,
        color=color,
        show_timestamps=show_timestamps,
        no_agent_text=no_agent_text,
        agent_transcript=agent_transcript,
    )


@dataclass(frozen=True)
class InvocationOptions:
    """CLI invocation metadata: presentation, store bootstrap, and run targets."""

    observability: ObservabilityOptions
    runs_dir_path: str
    runs_dir_source: str
    stream_json: bool = False
    until: str | None = None
    command: str | None = None


def invocation_options_from_args(
    args: Namespace,
    *,
    resolved_config: dict[str, Any] | None = None,
    resolved_runs: ResolvedRunsDir | None = None,
) -> InvocationOptions:
    observability = observability_options_from_args_and_config(
        args,
        resolved_config=resolved_config,
    )
    runs_path = ""
    runs_source = ""
    if resolved_runs is not None:
        runs_path = str(resolved_runs.path)
        runs_source = resolved_runs.source

    until = getattr(args, "until", None)
    if until is not None and not str(until).strip():
        until = None

    return InvocationOptions(
        observability=observability,
        runs_dir_path=runs_path,
        runs_dir_source=runs_source,
        stream_json=bool(getattr(args, "stream_json", False)),
        until=until,
        command=getattr(args, "command", None),
    )


def invocation_to_dict(invocation: InvocationOptions) -> dict[str, Any]:
    """Serialize invocation metadata for persistence (not included in config digests)."""

    obs = invocation.observability
    return {
        "observability": {
            "log_level": obs.log_level,
            "log_format": obs.log_format,
            "color": obs.color,
            "show_agent_text": not obs.no_agent_text,
            "show_timestamps": obs.show_timestamps,
            "agent_transcript": obs.agent_transcript,
        },
        "runs_dir": {
            "path": invocation.runs_dir_path,
            "source": invocation.runs_dir_source,
        },
        "stream_json": invocation.stream_json,
        "until": invocation.until,
        "command": invocation.command,
    }
