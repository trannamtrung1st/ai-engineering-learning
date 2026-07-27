"""Load optional YAML run configuration for the planning CLI."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from top_down_planning.agent_context import AgentContextConfig
from top_down_planning.errors import PlanningToolError
from top_down_planning.models import GenerationConfig, PlanningLimits, RenderConfig, ReviewConfig


class RunConfigFile(BaseModel):
    """Optional fields for a planning run YAML config file."""

    model_config = ConfigDict(extra="forbid")

    input: Path | None = None
    output: Path | None = None
    output_goal: str | None = None
    output_goal_file: Path | None = None
    stop_hint: str | None = None
    stop_hint_file: Path | None = None
    workspace: Path | None = None
    max_iterations: int | None = Field(default=None, ge=1)
    max_depth: int | None = Field(default=None, ge=1)
    max_items: int | None = Field(default=None, ge=1)
    max_retries: int | None = Field(default=None, ge=1)
    max_children_per_expansion: int | None = Field(default=None, ge=1)
    session_timeout_seconds: int | None = Field(default=None, ge=1)
    parse_error_threshold: int | None = Field(default=None, ge=1)
    resume: bool | None = None
    stream_json: bool | None = None
    no_color: bool | None = None
    notify: bool | None = None
    model: str | None = None
    agent_bin: str | None = None
    skip_probe: bool | None = None
    embed_threshold: int | None = Field(default=None, ge=0)
    agent_context: dict[str, Any] | None = None
    limits: PlanningLimits | None = None
    generation: GenerationConfig | None = None
    render: RenderConfig | None = None
    review: ReviewConfig | None = None
    render_only: bool | None = None
    force_rerender: bool | None = None

    @model_validator(mode="after")
    def _validate_goal_sources(self) -> RunConfigFile:
        if self.output_goal is not None and self.output_goal_file is not None:
            raise ValueError("Use either output_goal or output_goal_file, not both")
        if self.stop_hint is not None and self.stop_hint_file is not None:
            raise ValueError("Use either stop_hint or stop_hint_file, not both")
        return self


@dataclass(frozen=True)
class ResolvedRunOptions:
    input_path: Path
    output_dir: Path
    output_goal: str | None
    output_goal_file: Path | None
    stop_hint: str | None
    stop_hint_file: Path | None
    workspace: Path
    max_iterations: int
    max_depth: int
    max_items: int
    max_retries: int
    max_children_per_expansion: int
    session_timeout_seconds: int
    parse_error_threshold: int
    resume: bool
    stream_json: bool
    no_color: bool
    notify: bool
    model: str | None
    agent_bin: str | None
    skip_probe: bool
    embed_threshold: int | None
    agent_context: AgentContextConfig | None = None
    review: ReviewConfig = field(default_factory=ReviewConfig)
    generation: GenerationConfig = field(default_factory=GenerationConfig)
    render: RenderConfig = field(default_factory=RenderConfig)
    render_only: bool = False
    force_rerender: bool = False


def load_run_config_file(path: Path) -> RunConfigFile:
    resolved = path.resolve()
    if not resolved.is_file():
        raise PlanningToolError(f"Config file not found: {path}")
    try:
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PlanningToolError(f"Failed to read config file {path}: {exc}") from exc
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise PlanningToolError(f"Config file must contain a YAML mapping: {path}")
    try:
        return RunConfigFile.model_validate(_normalize_config_mapping(raw))
    except ValidationError as exc:
        raise PlanningToolError(f"Invalid config file {path}: {exc}") from exc


def merge_run_options(
    *,
    config_path: Path | None,
    input_path: Path | None = None,
    output_dir: Path | None = None,
    output_goal: str | None = None,
    output_goal_file: Path | None = None,
    stop_hint: str | None = None,
    stop_hint_file: Path | None = None,
    workspace: Path | None = None,
    max_iterations: int | None = None,
    max_depth: int | None = None,
    max_items: int | None = None,
    batch_size: int | None = None,
    concurrent_batches: int | None = None,
    render_concurrent_batches: int | None = None,
    max_retries: int | None = None,
    max_children_per_expansion: int | None = None,
    session_timeout_seconds: int | None = None,
    parse_error_threshold: int | None = None,
    resume: bool = False,
    render_only: bool = False,
    force_rerender: bool = False,
    stream_json: bool = False,
    no_color: bool = False,
    notify: bool | None = None,
    model: str | None = None,
    agent_bin: str | None = None,
    skip_probe: bool = False,
    embed_threshold: int | None = None,
) -> ResolvedRunOptions:
    file_cfg = load_run_config_file(config_path) if config_path is not None else None
    config_dir = config_path.resolve().parent if config_path is not None else Path.cwd()
    defaults = PlanningLimits()
    generation_defaults = GenerationConfig()

    resolved_workspace = _pick_path(
        cli_value=workspace,
        file_value=file_cfg.workspace if file_cfg else None,
        base_dir=config_dir,
        default=Path("."),
    )
    path_base = resolved_workspace or config_dir

    resolved_input = _pick_path(
        cli_value=input_path,
        file_value=file_cfg.input if file_cfg else None,
        base_dir=path_base,
    )
    resolved_output = _pick_path(
        cli_value=output_dir,
        file_value=file_cfg.output if file_cfg else None,
        base_dir=path_base,
    )
    resolved_goal_file = _pick_path(
        cli_value=output_goal_file,
        file_value=file_cfg.output_goal_file if file_cfg else None,
        base_dir=path_base,
    )
    resolved_goal = _pick_optional_str(output_goal, file_cfg.output_goal if file_cfg else None)
    resolved_stop_hint = _pick_optional_str(stop_hint, file_cfg.stop_hint if file_cfg else None)
    resolved_stop_hint_file = _pick_path(
        cli_value=stop_hint_file,
        file_value=file_cfg.stop_hint_file if file_cfg else None,
        base_dir=path_base,
    )

    if resolved_input is None and not _pick_bool(
        render_only, file_cfg.render_only if file_cfg else None, default=False
    ):
        raise PlanningToolError("Missing required option: input (CLI --input or config input)")
    if resolved_output is None:
        raise PlanningToolError("Missing required option: output (CLI --output or config output)")

    resolved_render_only = _pick_bool(
        render_only, file_cfg.render_only if file_cfg else None, default=False
    )
    if resolved_render_only:
        if resolved_goal is None and resolved_goal_file is None:
            resolved_goal = _pick_optional_str(None, file_cfg.output_goal if file_cfg else None)
            resolved_goal_file = _pick_path(
                cli_value=None,
                file_value=file_cfg.output_goal_file if file_cfg else None,
                base_dir=path_base,
            )
    elif resolved_goal is None and resolved_goal_file is None:
        raise PlanningToolError(
            "Provide an output goal via --output-goal, --output-goal-file, "
            "or config output_goal / output_goal_file"
        )
    if resolved_goal is not None and resolved_goal_file is not None:
        raise PlanningToolError("Use either output_goal or output_goal_file, not both")
    if resolved_stop_hint is not None and resolved_stop_hint_file is not None:
        raise PlanningToolError("Use either stop_hint or stop_hint_file, not both")

    file_limits = file_cfg.limits if file_cfg else None
    file_generation = file_cfg.generation if file_cfg else None
    file_render = file_cfg.render if file_cfg else None
    agent_context = _parse_agent_context(file_cfg.agent_context if file_cfg else None)
    review = file_cfg.review if file_cfg and file_cfg.review is not None else ReviewConfig()
    generation = _resolve_generation_config(
        file_generation=file_generation,
        cli_batch_size=batch_size,
        cli_concurrent_batches=concurrent_batches,
        defaults=generation_defaults,
    )
    render = _resolve_render_config(
        file_render=file_render,
        cli_concurrent_batches=render_concurrent_batches,
        defaults=RenderConfig(),
    )

    return ResolvedRunOptions(
        input_path=resolved_input or Path("."),
        output_dir=resolved_output,
        output_goal=resolved_goal,
        output_goal_file=resolved_goal_file,
        stop_hint=resolved_stop_hint,
        stop_hint_file=resolved_stop_hint_file,
        workspace=resolved_workspace or Path("."),
        max_iterations=_pick_int(
            max_iterations,
            file_cfg.max_iterations if file_cfg else None,
            file_limits.max_iterations if file_limits else None,
            defaults.max_iterations,
        ),
        max_depth=_pick_int(
            max_depth,
            file_cfg.max_depth if file_cfg else None,
            file_limits.max_depth if file_limits else None,
            defaults.max_depth,
        ),
        max_items=_pick_int(
            max_items,
            file_cfg.max_items if file_cfg else None,
            file_limits.max_items if file_limits else None,
            defaults.max_items,
        ),
        max_retries=_pick_int(
            max_retries,
            file_cfg.max_retries if file_cfg else None,
            file_limits.max_retries if file_limits else None,
            defaults.max_retries,
        ),
        max_children_per_expansion=_pick_int(
            max_children_per_expansion,
            file_cfg.max_children_per_expansion if file_cfg else None,
            file_limits.max_children_per_expansion if file_limits else None,
            defaults.max_children_per_expansion,
        ),
        session_timeout_seconds=_pick_int(
            session_timeout_seconds,
            file_cfg.session_timeout_seconds if file_cfg else None,
            file_limits.session_timeout_seconds if file_limits else None,
            defaults.session_timeout_seconds,
        ),
        parse_error_threshold=_pick_int(
            parse_error_threshold,
            file_cfg.parse_error_threshold if file_cfg else None,
            file_limits.parse_error_threshold if file_limits else None,
            defaults.parse_error_threshold,
        ),
        resume=_pick_bool(resume, file_cfg.resume if file_cfg else None, default=False),
        stream_json=_pick_bool(stream_json, file_cfg.stream_json if file_cfg else None, default=False),
        no_color=_pick_bool(no_color, file_cfg.no_color if file_cfg else None, default=False),
        notify=_pick_notify(notify, file_cfg.notify if file_cfg else None),
        model=_pick_optional_str(model, file_cfg.model if file_cfg else None),
        agent_bin=_pick_optional_str(agent_bin, file_cfg.agent_bin if file_cfg else None),
        skip_probe=_pick_bool(skip_probe, file_cfg.skip_probe if file_cfg else None, default=False),
        embed_threshold=_pick_optional_int(
            embed_threshold,
            file_cfg.embed_threshold if file_cfg else None,
        ),
        agent_context=agent_context,
        review=review,
        generation=generation,
        render=render,
        render_only=resolved_render_only,
        force_rerender=_pick_bool(
            force_rerender, file_cfg.force_rerender if file_cfg else None, default=False
        ),
    )


def options_to_planning_limits(options: ResolvedRunOptions) -> PlanningLimits:
    return PlanningLimits(
        max_iterations=options.max_iterations,
        max_depth=options.max_depth,
        max_items=options.max_items,
        max_retries=options.max_retries,
        max_children_per_expansion=options.max_children_per_expansion,
        session_timeout_seconds=options.session_timeout_seconds,
        parse_error_threshold=options.parse_error_threshold,
    )


def options_to_generation_config(options: ResolvedRunOptions) -> GenerationConfig:
    return options.generation


def options_to_render_config(options: ResolvedRunOptions) -> RenderConfig:
    return options.render


def _resolve_render_config(
    *,
    file_render: RenderConfig | None,
    cli_concurrent_batches: int | None,
    defaults: RenderConfig,
) -> RenderConfig:
    base = file_render.model_copy() if file_render is not None else RenderConfig()
    base.concurrent_batches = _pick_int(
        cli_concurrent_batches,
        file_render.concurrent_batches if file_render else None,
        None,
        defaults.concurrent_batches,
    )
    return base


def _resolve_generation_config(
    *,
    file_generation: GenerationConfig | None,
    cli_batch_size: int | None,
    cli_concurrent_batches: int | None,
    defaults: GenerationConfig,
) -> GenerationConfig:
    """Resolve generation settings: CLI → generation.* → defaults."""
    base = file_generation.model_copy() if file_generation is not None else GenerationConfig()
    base.batch_size = _pick_int(
        cli_batch_size,
        file_generation.batch_size if file_generation else None,
        None,
        defaults.batch_size,
    )
    base.concurrent_batches = _pick_int(
        cli_concurrent_batches,
        file_generation.concurrent_batches if file_generation else None,
        None,
        defaults.concurrent_batches,
    )
    return base


def _parse_agent_context(raw: dict[str, Any] | None) -> AgentContextConfig | None:
    if raw is None:
        return None
    try:
        config = AgentContextConfig.from_dict(raw)
    except ValueError as exc:
        raise PlanningToolError(f"Invalid agent_context: {exc}") from exc
    return None if config.is_empty() else config


def _normalize_config_mapping(raw: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(raw)
    limits = normalized.pop("limits", None)
    if isinstance(limits, dict):
        for key in ("batch_size", "concurrent_batches"):
            if key in limits:
                raise PlanningToolError(
                    f"limits.{key} is no longer supported; "
                    f"use generation.{key} instead"
                )
        for key, value in limits.items():
            if key not in normalized or normalized[key] is None:
                normalized[key] = value
    return normalized


def _pick_path(
    *,
    cli_value: Path | None,
    file_value: Path | None,
    base_dir: Path,
    default: Path | None = None,
) -> Path | None:
    if cli_value is not None:
        path = Path(cli_value).expanduser()
        if not path.is_absolute():
            path = base_dir / path
        return path.resolve()
    if file_value is not None:
        path = Path(file_value).expanduser()
        if not path.is_absolute():
            path = base_dir / path
        return path.resolve()
    if default is not None:
        path = Path(default).expanduser()
        if not path.is_absolute():
            path = base_dir / path
        return path.resolve()
    return None


def _pick_optional_str(cli_value: str | None, file_value: str | None) -> str | None:
    if cli_value is not None:
        text = cli_value.strip()
        return text or None
    if file_value is not None:
        text = str(file_value).strip()
        return text or None
    return None


def _pick_optional_int(cli_value: int | None, file_value: int | None) -> int | None:
    if cli_value is not None:
        return cli_value
    return file_value


def _pick_int(
    cli_value: int | None,
    file_value: int | None,
    nested_value: int | None,
    default: int,
) -> int:
    if cli_value is not None:
        return cli_value
    if file_value is not None:
        return file_value
    if nested_value is not None:
        return nested_value
    return default


def _pick_bool(cli_flag: bool, file_value: bool | None, *, default: bool) -> bool:
    if cli_flag:
        return True
    if file_value is not None:
        return file_value
    return default


def _pick_notify(
    cli_value: bool | None,
    file_value: bool | None,
    *,
    default: bool = True,
) -> bool:
    if cli_value is not None:
        return cli_value
    if file_value is not None:
        return file_value
    return default
