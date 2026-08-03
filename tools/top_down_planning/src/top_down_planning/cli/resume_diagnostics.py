"""Structured resume plan diagnostics for ``tdp resume --check`` (proposal §16)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from top_down_planning.config.resume_policy import (
    compare_resume_configs,
    get_config_value,
    validate_resume_config_comparison,
)
from top_down_planning.domain.resume_limits import consumed_limits_from_run
from top_down_planning.domain.resume_plan import ResumePlan
from top_down_planning.orchestrator.resume import RunResumeSnapshot


@dataclass(frozen=True)
class ResumeLimitDiagnostic:
    path: str
    consumed: int | None
    stored_limit: Any
    candidate_limit: Any
    remaining_budget: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "consumed": self.consumed,
            "stored_limit": self.stored_limit,
            "candidate_limit": self.candidate_limit,
            "remaining_budget": self.remaining_budget,
        }


def build_limit_diagnostics(
    run: dict[str, Any],
    stored_config: dict[str, Any],
    candidate_config: dict[str, Any],
    *,
    config_changes: dict[str, dict[str, Any]],
) -> list[ResumeLimitDiagnostic]:
    consumed_limits = consumed_limits_from_run(run) or {}
    diagnostics: list[ResumeLimitDiagnostic] = []

    stop = run.get("stop") if isinstance(run.get("stop"), dict) else {}
    stop_limit_path = str((stop.get("details") or {}).get("limit") or "").strip()
    candidate_paths = set(config_changes)
    if stop_limit_path:
        candidate_paths.add(stop_limit_path)

    for path in sorted(candidate_paths):
        if not path.startswith("limits."):
            continue
        stored_limit = get_config_value(stored_config, path)
        candidate_limit = get_config_value(candidate_config, path)
        consumed = consumed_limits.get(path)
        remaining: int | None = None
        if isinstance(candidate_limit, int) and isinstance(consumed, int):
            remaining = candidate_limit - consumed
        diagnostics.append(
            ResumeLimitDiagnostic(
                path=path,
                consumed=consumed,
                stored_limit=stored_limit,
                candidate_limit=candidate_limit,
                remaining_budget=remaining,
            )
        )
    return diagnostics


def format_session_policy_text(session_policy: dict[str, Any]) -> str:
    bindings = dict(session_policy.get("bindings") or {})
    if not bindings:
        return "no session corrections required"

    lines: list[str] = []
    for key in sorted(bindings):
        entry = bindings[key]
        action = str(entry.get("action") or "")
        role = str(entry.get("role") or key)
        provider_session_id = entry.get("provider_session_id")
        if action == "clear_stale_starting":
            lines.append(f"clear stale starting binding for {role}")
            continue
        if action == "resume_then_replace_if_missing" and provider_session_id:
            lines.append(f"resume {role} session {provider_session_id}")
            lines.append("replace once if Cursor reports session not found")
            continue
        if action:
            lines.append(f"{role}: {action}")
    return "\n  ".join(lines) if lines else "no session corrections required"


def _format_stop_summary(stop: dict[str, Any] | None) -> str | None:
    if not isinstance(stop, dict):
        return None
    code = str(stop.get("code") or "unknown")
    message = str(stop.get("message") or "").strip()
    details = stop.get("details") or {}
    if code == "limit_exhausted" and isinstance(details, dict):
        limit = details.get("limit")
        consumed = details.get("consumed")
        configured = details.get("configured")
        if limit is not None:
            return (
                f"{code}: {limit} exhausted at {consumed}/{configured}"
                if consumed is not None and configured is not None
                else f"{code}: {message or limit}"
            )
    if message:
        return f"{code}: {message}"
    return code


def build_resume_plan_summary(
    resume_plan: ResumePlan,
    *,
    run: dict[str, Any],
    snapshot: RunResumeSnapshot,
    stored_config: dict[str, Any],
    candidate_config: dict[str, Any],
    invocation: dict[str, Any] | None = None,
    config_path: str | None = None,
    config_overrides: list[str] | None = None,
) -> dict[str, Any]:
    consumed_limits = consumed_limits_from_run(run)
    comparison = validate_resume_config_comparison(
        compare_resume_configs(stored_config, candidate_config),
        consumed_limits=consumed_limits,
        candidate_config=candidate_config,
    )
    limit_diagnostics = build_limit_diagnostics(
        run,
        stored_config,
        candidate_config,
        config_changes=resume_plan.config_changes,
    )
    stop_summary = _format_stop_summary(
        snapshot.stop if snapshot.status == "paused" else None
    )
    session_policy = dict(resume_plan.session_policy)
    session_policy_text = format_session_policy_text(session_policy)

    transition = None
    if resume_plan.state_transition is not None:
        transition = resume_plan.state_transition.to_dict()

    return {
        "ok": not resume_plan.already_completed,
        "run_id": resume_plan.run_id,
        "check_only": True,
        "already_completed": resume_plan.already_completed,
        "message": resume_plan.message,
        "phase": str(run.get("phase") or ""),
        "status": snapshot.status,
        "expected_run_revision": resume_plan.expected_run_revision,
        "stop": snapshot.stop,
        "stop_summary": stop_summary,
        "config_path": config_path,
        "config_overrides": list(config_overrides or []),
        "config_changes": dict(resume_plan.config_changes),
        "comparison_ok": comparison.ok,
        "comparison_errors": list(comparison.errors),
        "limit_diagnostics": [item.to_dict() for item in limit_diagnostics],
        "state_transition": transition,
        "session_policy": session_policy,
        "session_policy_text": session_policy_text,
        "validation": resume_plan.validation.to_dict(),
        "invocation": dict(invocation or {}),
    }


def format_resume_plan_summary_text(summary: dict[str, Any]) -> str:
    if summary.get("already_completed"):
        return str(summary.get("message") or "run already completed")

    lines: list[str] = []
    if summary.get("comparison_ok", True) and not summary.get("already_completed"):
        lines.append("Run is resumable.")
    else:
        lines.append("Run is not resumable.")
        for error in summary.get("comparison_errors") or []:
            lines.append(f"  blocked: {error}")

    stop_summary = summary.get("stop_summary")
    if stop_summary:
        lines.append("")
        lines.append("Stop:")
        lines.append(f"  {stop_summary}")

    limit_rows = summary.get("limit_diagnostics") or []
    execution_changes = [
        change
        for path, change in (summary.get("config_changes") or {}).items()
        if path.startswith("limits.")
    ]
    if limit_rows or execution_changes:
        lines.append("")
        lines.append("Execution-policy changes:")
        for row in limit_rows:
            lines.append(
                f"  {row['path']}: stored={row['stored_limit']!r} "
                f"candidate={row['candidate_limit']!r} "
                f"consumed={row['consumed']!r} "
                f"remaining={row['remaining_budget']!r}"
            )
        for path, change in (summary.get("config_changes") or {}).items():
            if path.startswith("limits."):
                continue
            lines.append(f"  {path}: {change.get('from')!r} -> {change.get('to')!r}")

    presentation_changes = {
        path: change
        for path, change in (summary.get("config_changes") or {}).items()
        if not str(path).startswith("limits.")
    }
    if presentation_changes:
        lines.append("")
        lines.append("Presentation changes:")
        for path, change in sorted(presentation_changes.items()):
            lines.append(f"  {path}: {change.get('from')!r} -> {change.get('to')!r}")

    transition = summary.get("state_transition")
    if transition:
        lines.append("")
        lines.append("State transition:")
        prior = transition.get("prior_stop_code")
        if prior:
            lines.append(
                f"  {transition.get('from')} -> {transition.get('to')} "
                f"(prior_stop={prior})"
            )
        else:
            lines.append(f"  {transition.get('from')} -> {transition.get('to')}")

    lines.append("")
    lines.append("Session policy:")
    for line in str(summary.get("session_policy_text") or "").splitlines():
        lines.append(f"  {line}")

    config_path = summary.get("config_path")
    overrides = summary.get("config_overrides") or []
    if config_path or overrides:
        lines.append("")
        lines.append("Candidate config:")
        if config_path:
            lines.append(f"  config: {config_path}")
        for override in overrides:
            lines.append(f"  set: {override}")

    return "\n".join(lines)


__all__ = [
    "ResumeLimitDiagnostic",
    "build_limit_diagnostics",
    "build_resume_plan_summary",
    "consumed_limits_from_run",
    "format_resume_plan_summary_text",
    "format_session_policy_text",
]
