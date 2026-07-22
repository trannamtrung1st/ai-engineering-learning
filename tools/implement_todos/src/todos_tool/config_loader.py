"""Load optional YAML run configuration for the todos CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from todos_tool.errors import TodosToolError
from todos_tool.run_config import DEFAULT_COMMIT_HINT, RunConfig

ALLOWED_CONFIG_KEYS = frozenset(
    {
        "workspace",
        "todos_dir",
        "no_color",
        "model",
        "stop_on_failure",
        "auto_commit",
        "agent_bin",
        "skip_probe",
        "project_config",
        "context_files",
        "skip_commit",
        "no_auto_repair_yaml",
        "max_yaml_repair_attempts",
        "dry_run",
        "dry_run_prompts",
        "commit_hint",
        "commit_hint_file",
        "evidence_mode",
        "max_identical_evidence_failures",
        "evidence_batch_timeout_seconds",
        "force_reset",
        "notify",
        "notify_per_item",
    }
)


@dataclass(frozen=True)
class LoadedRunConfigFile:
    workspace: Path | None = None
    todos_dir: str | None = None
    no_color: bool | None = None
    model: str | None = None
    stop_on_failure: bool | None = None
    auto_commit: bool | None = None
    agent_bin: str | None = None
    skip_probe: bool | None = None
    project_config: Path | None = None
    context_files: tuple[str, ...] | None = None
    skip_commit: bool | None = None
    no_auto_repair_yaml: bool | None = None
    max_yaml_repair_attempts: int | None = None
    dry_run: bool | None = None
    dry_run_prompts: bool | None = None
    commit_hint: str | None = None
    commit_hint_file: Path | None = None
    evidence_mode: str | None = None
    max_identical_evidence_failures: int | None = None
    evidence_batch_timeout_seconds: int | None = None
    force_reset: bool | None = None
    notify: bool | None = None
    notify_per_item: bool | None = None


def load_run_config_file(path: Path) -> LoadedRunConfigFile:
    resolved = path.resolve()
    if not resolved.is_file():
        raise TodosToolError(f"Config file not found: {path}")
    try:
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise TodosToolError(f"Failed to read config file {path}: {exc}") from exc
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise TodosToolError(f"Config file must contain a YAML mapping: {path}")

    unknown = set(raw) - ALLOWED_CONFIG_KEYS
    if unknown:
        raise TodosToolError(
            f"Unknown config keys in {path}: {', '.join(sorted(unknown))}"
        )

    if raw.get("commit_hint") is not None and raw.get("commit_hint_file") is not None:
        raise TodosToolError(
            f"Use either commit_hint or commit_hint_file in {path}, not both"
        )

    context_files_raw = raw.get("context_files")
    context_files: tuple[str, ...] | None = None
    if context_files_raw is not None:
        if not isinstance(context_files_raw, list):
            raise TodosToolError(f"context_files must be a list in {path}")
        context_files = tuple(str(item).strip() for item in context_files_raw if str(item).strip())

    return LoadedRunConfigFile(
        workspace=_optional_path(raw.get("workspace")),
        todos_dir=_optional_str(raw.get("todos_dir")),
        no_color=_optional_bool(raw.get("no_color")),
        model=_optional_str(raw.get("model")),
        stop_on_failure=_optional_bool(raw.get("stop_on_failure")),
        auto_commit=_optional_bool(raw.get("auto_commit")),
        agent_bin=_optional_str(raw.get("agent_bin")),
        skip_probe=_optional_bool(raw.get("skip_probe")),
        project_config=_optional_path(raw.get("project_config")),
        context_files=context_files,
        skip_commit=_optional_bool(raw.get("skip_commit")),
        no_auto_repair_yaml=_optional_bool(raw.get("no_auto_repair_yaml")),
        max_yaml_repair_attempts=_optional_int(raw.get("max_yaml_repair_attempts")),
        dry_run=_optional_bool(raw.get("dry_run")),
        dry_run_prompts=_optional_bool(raw.get("dry_run_prompts")),
        commit_hint=_optional_str(raw.get("commit_hint")),
        commit_hint_file=_optional_path(raw.get("commit_hint_file")),
        evidence_mode=_optional_str(raw.get("evidence_mode")),
        max_identical_evidence_failures=_optional_int(
            raw.get("max_identical_evidence_failures")
        ),
        evidence_batch_timeout_seconds=_optional_int(
            raw.get("evidence_batch_timeout_seconds")
        ),
        force_reset=_optional_bool(raw.get("force_reset")),
        notify=_optional_bool(raw.get("notify")),
        notify_per_item=_optional_bool(raw.get("notify_per_item")),
    )


def build_run_config(
    *,
    config_path: Path | None = None,
    workspace: Path | None = None,
    todos_dir: str | None = None,
    no_color: bool = False,
    model: str | None = None,
    stop_on_failure: bool | None = None,
    auto_commit: bool | None = None,
    agent_bin: str | None = None,
    skip_probe: bool = False,
    project_config: Path | None = None,
    context_files: tuple[str, ...] = (),
    skip_commit: bool = False,
    no_auto_repair_yaml: bool = False,
    max_yaml_repair_attempts: int | None = None,
    dry_run: bool = False,
    dry_run_prompts: bool = False,
    commit_hint: str | None = None,
    commit_hint_file: Path | None = None,
    evidence_mode: str | None = None,
    max_identical_evidence_failures: int | None = None,
    evidence_batch_timeout_seconds: int | None = None,
    force_reset: bool = False,
    notify: bool | None = None,
    notify_per_item: bool | None = None,
) -> RunConfig:
    file_cfg = load_run_config_file(config_path) if config_path is not None else None
    config_dir = config_path.resolve().parent if config_path is not None else Path.cwd()

    resolved_workspace = _pick_path(
        cli_value=workspace,
        file_value=file_cfg.workspace if file_cfg else None,
        base_dir=config_dir,
        default=Path("."),
    )
    path_base = resolved_workspace or config_dir

    resolved_project_config = _pick_path(
        cli_value=project_config,
        file_value=file_cfg.project_config if file_cfg else None,
        base_dir=path_base,
    )
    resolved_commit_hint_file = _pick_path(
        cli_value=commit_hint_file,
        file_value=file_cfg.commit_hint_file if file_cfg else None,
        base_dir=path_base,
    )
    resolved_commit_hint = _pick_optional_str(
        commit_hint,
        file_cfg.commit_hint if file_cfg else None,
    )
    if resolved_commit_hint is None and resolved_commit_hint_file is not None:
        resolved_commit_hint = _read_text_file(resolved_commit_hint_file)
    if resolved_commit_hint is None:
        resolved_commit_hint = DEFAULT_COMMIT_HINT

    if commit_hint is not None and commit_hint_file is not None:
        raise TodosToolError("Use either --commit-hint or --commit-hint-file, not both")

    merged_context_files = _merge_context_files(
        context_files,
        file_cfg.context_files if file_cfg else None,
    )

    return RunConfig(
        workspace_root=resolved_workspace or Path("."),
        todos_dir=_pick_str(
            todos_dir,
            file_cfg.todos_dir if file_cfg else None,
            default="todos",
        ),
        no_color=_pick_bool(no_color, file_cfg.no_color if file_cfg else None, default=False),
        model=_pick_optional_str(model, file_cfg.model if file_cfg else None),
        stop_on_failure=_pick_optional_bool(
            stop_on_failure,
            file_cfg.stop_on_failure if file_cfg else None,
        ),
        auto_commit=_pick_optional_bool(
            auto_commit,
            file_cfg.auto_commit if file_cfg else None,
        ),
        agent_bin=_pick_optional_str(agent_bin, file_cfg.agent_bin if file_cfg else None),
        skip_probe=_pick_bool(
            skip_probe,
            file_cfg.skip_probe if file_cfg else None,
            default=False,
        ),
        project_config=resolved_project_config,
        context_files=merged_context_files,
        skip_commit=_pick_bool(
            skip_commit,
            file_cfg.skip_commit if file_cfg else None,
            default=False,
        ),
        no_auto_repair_yaml=_pick_bool(
            no_auto_repair_yaml,
            file_cfg.no_auto_repair_yaml if file_cfg else None,
            default=False,
        ),
        max_yaml_repair_attempts=_pick_int(
            max_yaml_repair_attempts,
            file_cfg.max_yaml_repair_attempts if file_cfg else None,
            default=2,
        ),
        dry_run=_pick_bool(dry_run, file_cfg.dry_run if file_cfg else None, default=False),
        dry_run_prompts=_pick_bool(
            dry_run_prompts,
            file_cfg.dry_run_prompts if file_cfg else None,
            default=False,
        ),
        commit_hint=resolved_commit_hint,
        evidence_mode=_pick_optional_str(
            evidence_mode,
            file_cfg.evidence_mode if file_cfg else None,
        ),
        max_identical_evidence_failures=_pick_int(
            max_identical_evidence_failures,
            file_cfg.max_identical_evidence_failures if file_cfg else None,
            default=3,
        ),
        evidence_batch_timeout_seconds=_pick_optional_int(
            evidence_batch_timeout_seconds,
            file_cfg.evidence_batch_timeout_seconds if file_cfg else None,
        ),
        force_reset=_pick_bool(
            force_reset,
            file_cfg.force_reset if file_cfg else None,
            default=False,
        ),
        notify=_pick_notify(
            notify,
            file_cfg.notify if file_cfg else None,
        ),
        notify_per_item=_pick_notify(
            notify_per_item,
            file_cfg.notify_per_item if file_cfg else None,
            default=False,
        ),
    )


def _merge_context_files(
    cli_values: tuple[str, ...],
    file_values: tuple[str, ...] | None,
) -> tuple[str, ...]:
    merged: list[str] = []
    seen: set[str] = set()
    for value in (file_values or ()) + cli_values:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            merged.append(text)
    return tuple(merged)


def _read_text_file(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise TodosToolError(f"Failed to read commit hint file {path}: {exc}") from exc
    if not text:
        raise TodosToolError(f"Commit hint file is empty: {path}")
    return text


def _optional_path(value: Any) -> Path | None:
    if value is None:
        return None
    return Path(str(value))


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise TodosToolError(f"Expected boolean, got {value!r}")
    return value


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int):
        raise TodosToolError(f"Expected integer, got {value!r}")
    return value


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


def _pick_str(cli_value: str | None, file_value: str | None, *, default: str) -> str:
    if cli_value is not None:
        return cli_value
    if file_value is not None:
        return file_value
    return default


def _pick_int(cli_value: int | None, file_value: int | None, *, default: int) -> int:
    if cli_value is not None:
        return cli_value
    if file_value is not None:
        return file_value
    return default


def _pick_bool(cli_flag: bool, file_value: bool | None, *, default: bool) -> bool:
    if cli_flag != default:
        return cli_flag
    if file_value is not None:
        return file_value
    return default


def _pick_optional_bool(
    cli_value: bool | None,
    file_value: bool | None,
) -> bool | None:
    if cli_value is not None:
        return cli_value
    return file_value


def _pick_optional_int(
    cli_value: int | None,
    file_value: int | None,
) -> int | None:
    if cli_value is not None:
        return cli_value
    return file_value


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
