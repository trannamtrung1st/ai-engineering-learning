"""Resume execution-policy allowlist and candidate config comparison (proposal §8)."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from core_tools.config import apply_cli_overrides, collect_leaf_paths

from top_down_planning.config.activities import (
    ALLOWED_AGENT_ACTIVITIES,
    ALLOWED_AGENT_ROLES,
)
from top_down_planning.config.defaults import (
    ALLOWED_OVERRIDE_PATHS,
)
from top_down_planning.config.resolve import resolve_config
from top_down_planning.domain.reviews import find_whole_plan_approval
from top_down_planning.persistence.digests import (
    compute_config_contract_digest,
    compute_config_execution_digest,
)

__all__ = [
    "RESUME_EXECUTION_POLICY_ALLOWLIST",
    "RESUME_PRESENTATION_ALLOWLIST",
    "RESUME_PROVIDER_BLOCKED_PATHS",
    "RESUME_SESSION_STRATEGY_BLOCKED_PATHS",
    "ResumeConfigChange",
    "ResumeConfigComparison",
    "ResumeConfigDriftResult",
    "apply_resume_config_drift_policy",
    "compare_resume_configs",
    "get_config_value",
    "has_mandatory_whole_plan_approval",
    "resolve_resume_candidate_config",
    "resolve_resume_candidate_for_run",
    "set_config_value",
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
    "limits.review.",
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

RESUME_PROVIDER_BLOCKED_PATHS: frozenset[str] = frozenset(
    {
        "provider.name",
        "provider.binary",
        "provider.skip_probe",
    }
)

RESUME_SESSION_STRATEGY_BLOCKED_PATHS: frozenset[str] = frozenset(
    {
        *RESUME_PROVIDER_BLOCKED_PATHS,
        "agent_context.default.model",
        *(
            f"agent_context.roles.{role}.model"
            for role in ALLOWED_AGENT_ROLES
        ),
        *(
            f"agent_context.activities.{activity}.model"
            for activity in ALLOWED_AGENT_ACTIVITIES
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


@dataclass(frozen=True)
class ResumeConfigDriftResult:
    effective_config: dict[str, Any]
    applied_changes: dict[str, dict[str, Any]]
    ignored_changes: dict[str, dict[str, Any]]
    warnings: tuple[str, ...]
    errors: tuple[str, ...]
    comparison: ResumeConfigComparison
    contract_digest_changed: bool
    execution_digest_changed: bool

    @property
    def ok(self) -> bool:
        return not self.errors


def _is_provider_path(path: str) -> bool:
    return path in RESUME_PROVIDER_BLOCKED_PATHS


def _is_model_path(path: str) -> bool:
    return path.startswith("agent_context.") and path.endswith(".model")


def _is_approval_bound_drift_path(path: str, kind: ChangeKind) -> bool:
    return kind == "contract" or _is_model_path(path)


def _has_contract_or_model_applied_changes(
    applied: dict[str, dict[str, Any]],
) -> bool:
    return any(
        _is_model_path(path) or _classify_change(path) == "contract"
        for path in applied
    )


def has_mandatory_whole_plan_approval(
    reviews: list[dict[str, Any]],
    plan_revision: int,
) -> bool:
    """Return True when a completed whole-plan approval exists for the plan revision."""

    return find_whole_plan_approval(reviews, plan_revision) is not None


def get_config_value(config: dict[str, Any], path: str) -> Any:
    """Return the value at a dotted config path, or None when absent."""

    current: Any = config
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def set_config_value(config: dict[str, Any], path: str, value: Any) -> None:
    """Set a dotted config path on a nested dict, creating intermediate dicts."""

    parts = path.split(".")
    current: dict[str, Any] = config
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    leaf = parts[-1]
    if value is None:
        current.pop(leaf, None)
        return
    current[leaf] = copy.deepcopy(value)


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


def _is_numeric_limit_value(value: Any) -> bool:
    """Return True for int/float limit values (bool is excluded)."""

    return type(value) is int or type(value) is float


def _validate_execution_change(
    change: ResumeConfigChange,
    *,
    consumed_limits: dict[str, int] | None,
) -> str | None:
    stored = change.stored_value
    candidate = change.candidate_value
    if not _is_numeric_limit_value(stored) or not _is_numeric_limit_value(candidate):
        return (
            f"resume config change for {change.path!r} requires numeric limits; "
            f"got stored={stored!r}, candidate={candidate!r}"
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
    candidate_config: dict[str, Any] | None = None,
    allow_contract_and_model_changes: bool = False,
    consumed_limit_skip_paths: frozenset[str] | None = None,
) -> ResumeConfigComparison:
    """Apply resume allowlist and limit-consumption rules to a comparison result."""

    errors: list[str] = []
    blocked: list[ResumeConfigChange] = []
    allowed: list[ResumeConfigChange] = []
    changed_paths = {change.path for change in comparison.changes}

    for change in comparison.changes:
        if _is_provider_path(change.path):
            errors.append(
                f"resume blocked session-strategy change: {change.path} "
                f"({change.stored_value!r} -> {change.candidate_value!r})"
            )
            continue
        if change.kind == "session_strategy" and _is_model_path(change.path):
            if allow_contract_and_model_changes:
                allowed.append(change)
                continue
            errors.append(
                f"resume blocked session-strategy change: {change.path} "
                f"({change.stored_value!r} -> {change.candidate_value!r}) "
                f"(pass --allow-config-drift to opt in)"
            )
            continue
        if change.kind == "session_strategy":
            errors.append(
                f"resume blocked session-strategy change: {change.path} "
                f"({change.stored_value!r} -> {change.candidate_value!r})"
            )
            continue
        if change.kind == "contract":
            if allow_contract_and_model_changes:
                allowed.append(change)
                continue
            errors.append(
                f"resume blocked contract change: {change.path} "
                f"({change.stored_value!r} -> {change.candidate_value!r}) "
                f"(pass --allow-config-drift to opt in)"
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

    if consumed_limits and candidate_config is not None:
        skip_paths = consumed_limit_skip_paths or frozenset()
        for path, consumed in sorted(consumed_limits.items()):
            if path in changed_paths or path in skip_paths:
                continue
            candidate_value = get_config_value(candidate_config, path)
            if not _is_numeric_limit_value(candidate_value) or candidate_value <= consumed:
                errors.append(
                    f"resume from limit_exhausted requires {path!r} strictly greater "
                    f"than consumed usage (consumed={consumed}, candidate={candidate_value!r})"
                )

    return ResumeConfigComparison(
        changes=comparison.changes,
        allowed_changes=tuple(allowed),
        blocked_changes=tuple(blocked),
        errors=tuple(errors),
        contract_digest_changed=comparison.contract_digest_changed,
        execution_digest_changed=comparison.execution_digest_changed,
    )


def apply_resume_config_drift_policy(
    stored: dict[str, Any],
    candidate: dict[str, Any],
    *,
    allow_config_drift: bool,
    has_whole_plan_approval: bool,
    consumed_limits: dict[str, int] | None = None,
) -> ResumeConfigDriftResult:
    """Resolve stored/candidate config into an effective resume config."""

    requested = compare_resume_configs(stored, candidate)
    if not allow_config_drift:
        comparison = validate_resume_config_comparison(
            requested,
            consumed_limits=consumed_limits,
            candidate_config=candidate,
        )
        applied = {
            change.path: {
                "from": change.stored_value,
                "to": change.candidate_value,
            }
            for change in comparison.allowed_changes
        }
        return ResumeConfigDriftResult(
            effective_config=copy.deepcopy(candidate),
            applied_changes=applied,
            ignored_changes={},
            warnings=(),
            errors=comparison.errors,
            comparison=comparison,
            contract_digest_changed=comparison.contract_digest_changed,
            execution_digest_changed=comparison.execution_digest_changed,
        )

    effective = copy.deepcopy(candidate)
    errors: list[str] = []
    applied: dict[str, dict[str, Any]] = {}
    ignored: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    limit_validation_failed_paths: set[str] = set()

    for change in requested.changes:
        if _is_provider_path(change.path):
            errors.append(
                f"resume blocked session-strategy change: {change.path} "
                f"({change.stored_value!r} -> {change.candidate_value!r})"
            )
            set_config_value(effective, change.path, change.stored_value)
            continue

        if has_whole_plan_approval and _is_approval_bound_drift_path(
            change.path,
            change.kind,
        ):
            set_config_value(effective, change.path, change.stored_value)
            ignored[change.path] = {
                "from": change.stored_value,
                "to": change.candidate_value,
            }
            continue

        if change.kind == "presentation":
            applied[change.path] = {
                "from": change.stored_value,
                "to": change.candidate_value,
            }
            continue

        if change.kind in {"contract", "session_strategy"}:
            applied[change.path] = {
                "from": change.stored_value,
                "to": change.candidate_value,
            }
            continue

        limit_error = _validate_execution_change(
            change,
            consumed_limits=consumed_limits,
        )
        if limit_error is not None:
            errors.append(limit_error)
            set_config_value(effective, change.path, change.stored_value)
            limit_validation_failed_paths.add(change.path)
            continue
        applied[change.path] = {
            "from": change.stored_value,
            "to": change.candidate_value,
        }

    allow_contract = not has_whole_plan_approval
    comparison = validate_resume_config_comparison(
        compare_resume_configs(stored, effective),
        consumed_limits=consumed_limits,
        candidate_config=effective,
        allow_contract_and_model_changes=allow_contract,
        consumed_limit_skip_paths=frozenset(limit_validation_failed_paths),
    )
    if comparison.errors:
        errors.extend(comparison.errors)

    if ignored:
        warnings.append(
            "approved-plan contract changes were ignored and will not take effect: "
            + ", ".join(sorted(ignored))
        )
    if allow_contract and _has_contract_or_model_applied_changes(applied):
        warnings.append(
            "config drift explicitly accepted; contract and model changes will apply"
        )

    return ResumeConfigDriftResult(
        effective_config=effective,
        applied_changes=applied,
        ignored_changes=ignored,
        warnings=tuple(warnings),
        errors=tuple(errors),
        comparison=comparison,
        contract_digest_changed=compute_config_contract_digest(stored)
        != compute_config_contract_digest(effective),
        execution_digest_changed=compute_config_execution_digest(stored)
        != compute_config_execution_digest(effective),
    )
