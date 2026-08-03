"""Resume execution-policy allowlist and candidate config comparison (proposal §8)."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from core_tools.config import apply_cli_overrides, collect_leaf_paths

from top_down_planning.config.defaults import (
    ALLOWED_AGENT_CONTEXT_ROLES,
    ALLOWED_OVERRIDE_PATHS,
)
from top_down_planning.config.resolve import resolve_config
from top_down_planning.persistence.digests import (
    compute_config_contract_digest,
    compute_config_execution_digest,
)

__all__ = [
    "RESUME_EXECUTION_POLICY_ALLOWLIST",
    "RESUME_PRESENTATION_ALLOWLIST",
    "RESUME_SESSION_STRATEGY_BLOCKED_PATHS",
    "ResumeConfigChange",
    "ResumeConfigComparison",
    "compare_resume_configs",
    "get_config_value",
    "resolve_resume_candidate_config",
    "resolve_resume_candidate_for_run",
    "validate_resume_config_comparison",
]

_RESUME_LIMIT_PREFIXES = (
    "limits.planning.",
    "limits.whole_plan_review.",
    "limits.whole_output_review.",
    "limits.focused_plan_review.",
    "limits.focused_output_review.",
    "limits.production.",
    "limits.amendment.",
)

RESUME_EXECUTION_POLICY_ALLOWLIST: frozenset[str] = frozenset(
    path
    for path in ALLOWED_OVERRIDE_PATHS
    if path.startswith(_RESUME_LIMIT_PREFIXES)
    or path == "limits.provider.max_retries_per_call"
    or path == "limits.provider.turn_idle_timeout_seconds"
)

RESUME_PRESENTATION_ALLOWLIST: frozenset[str] = frozenset(
    path
    for path in ALLOWED_OVERRIDE_PATHS
    if path.startswith("observability.")
    or path.startswith("notifications.")
    or path == "runtime.runs_dir"
)

RESUME_SESSION_STRATEGY_BLOCKED_PATHS: frozenset[str] = frozenset(
    {
        "provider.name",
        "provider.binary",
        "provider.skip_probe",
        *(
            f"agent_context.{role}.model"
            for role in ALLOWED_AGENT_CONTEXT_ROLES
        ),
    }
)

ChangeKind = Literal["execution", "presentation", "session_strategy", "contract"]


@dataclass(frozen=True)
class ResumeConfigChange:
    path: str
    stored_value: Any
    candidate_value: Any
    kind: ChangeKind


@dataclass(frozen=True)
class ResumeConfigComparison:
    changes: tuple[ResumeConfigChange, ...]
    allowed_changes: tuple[ResumeConfigChange, ...]
    blocked_changes: tuple[ResumeConfigChange, ...]
    errors: tuple[str, ...]
    contract_digest_changed: bool
    execution_digest_changed: bool

    @property
    def ok(self) -> bool:
        return not self.errors and not self.blocked_changes


def get_config_value(config: dict[str, Any], path: str) -> Any:
    """Return the value at a dotted config path, or None when absent."""

    current: Any = config
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def resolve_resume_candidate_config(
    config_path: Path | None,
    overrides: list[str] | None = None,
    *,
    cwd: Path | None = None,
) -> dict[str, Any]:
    """Resolve a resume candidate configuration from YAML and ``--set`` overrides."""

    return resolve_config(config_path, overrides, cwd=cwd or Path.cwd())


def resolve_resume_candidate_for_run(
    stored_config: dict[str, Any],
    *,
    config_path: Path | None = None,
    overrides: list[str] | None = None,
    cwd: Path | None = None,
) -> dict[str, Any]:
    """Resolve resume candidate config from stored snapshot and/or CLI inputs."""

    if config_path is not None:
        return resolve_resume_candidate_config(config_path, overrides, cwd=cwd)
    candidate = copy.deepcopy(stored_config)
    if overrides:
        candidate = apply_cli_overrides(
            candidate,
            overrides,
            allowed_paths=ALLOWED_OVERRIDE_PATHS,
        )
    return candidate


def _classify_change(path: str) -> ChangeKind:
    if path in RESUME_SESSION_STRATEGY_BLOCKED_PATHS:
        return "session_strategy"
    if path in RESUME_EXECUTION_POLICY_ALLOWLIST:
        return "execution"
    if path in RESUME_PRESENTATION_ALLOWLIST:
        return "presentation"
    return "contract"


def compare_resume_configs(
    stored: dict[str, Any],
    candidate: dict[str, Any],
) -> ResumeConfigComparison:
    """Diff stored and candidate configs and classify each changed path."""

    paths = collect_leaf_paths(stored) | collect_leaf_paths(candidate)
    changes: list[ResumeConfigChange] = []
    for path in sorted(paths):
        stored_value = get_config_value(stored, path)
        candidate_value = get_config_value(candidate, path)
        if stored_value != candidate_value:
            changes.append(
                ResumeConfigChange(
                    path=path,
                    stored_value=stored_value,
                    candidate_value=candidate_value,
                    kind=_classify_change(path),
                )
            )

    allowed = tuple(
        change
        for change in changes
        if change.kind in {"execution", "presentation"}
    )
    blocked = tuple(
        change
        for change in changes
        if change.kind in {"session_strategy", "contract"}
    )
    return ResumeConfigComparison(
        changes=tuple(changes),
        allowed_changes=allowed,
        blocked_changes=blocked,
        errors=(),
        contract_digest_changed=compute_config_contract_digest(stored)
        != compute_config_contract_digest(candidate),
        execution_digest_changed=compute_config_execution_digest(stored)
        != compute_config_execution_digest(candidate),
    )


def _validate_execution_change(
    change: ResumeConfigChange,
    *,
    consumed_limits: dict[str, int] | None,
) -> str | None:
    stored = change.stored_value
    candidate = change.candidate_value
    if not isinstance(stored, (int, float)) or not isinstance(candidate, (int, float)):
        return (
            f"resume config change for {change.path!r} requires numeric limits; "
            f"got stored={stored!r}, candidate={candidate!r}"
        )
    if candidate <= stored:
        return (
            f"resume config change for {change.path!r} must increase the stored limit "
            f"(stored={stored}, candidate={candidate})"
        )
    if consumed_limits is not None and change.path in consumed_limits:
        consumed = consumed_limits[change.path]
        if candidate <= consumed:
            return (
                f"resume config change for {change.path!r} must be strictly greater than "
                f"consumed usage (consumed={consumed}, candidate={candidate})"
            )
    return None


def validate_resume_config_comparison(
    comparison: ResumeConfigComparison,
    *,
    consumed_limits: dict[str, int] | None = None,
) -> ResumeConfigComparison:
    """Apply resume allowlist and limit-increase rules to a comparison result."""

    errors: list[str] = []
    blocked: list[ResumeConfigChange] = list(comparison.blocked_changes)
    allowed: list[ResumeConfigChange] = []

    for change in comparison.changes:
        if change.kind == "session_strategy":
            errors.append(
                f"resume blocked session-strategy change: {change.path} "
                f"({change.stored_value!r} -> {change.candidate_value!r})"
            )
            continue
        if change.kind == "contract":
            errors.append(
                f"resume blocked contract change: {change.path} "
                f"({change.stored_value!r} -> {change.candidate_value!r})"
            )
            continue
        if change.kind == "presentation":
            allowed.append(change)
            continue

        limit_error = _validate_execution_change(
            change,
            consumed_limits=consumed_limits,
        )
        if limit_error is not None:
            errors.append(limit_error)
            blocked.append(change)
        else:
            allowed.append(change)

    return ResumeConfigComparison(
        changes=comparison.changes,
        allowed_changes=tuple(allowed),
        blocked_changes=tuple(blocked),
        errors=tuple(errors),
        contract_digest_changed=comparison.contract_digest_changed,
        execution_digest_changed=comparison.execution_digest_changed,
    )
