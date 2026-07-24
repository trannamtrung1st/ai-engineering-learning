"""Pre-review completion-evidence mechanical gate."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from todos_tool.evidence_matcher import (
    EvidenceMatchResult,
    ObservedShellRun,
    match_all_specs,
    normalize_command,
    normalize_cwd,
)
from todos_tool.evidence_runner import format_evidence_results
from todos_tool.models import EvidenceCommandResult, EvidenceCommandSpec, EvidenceMode


@dataclass
class EvidenceGateAssessment:
    passed: bool
    stale: bool = False
    stalled: bool = False
    results: list[EvidenceCommandResult] = field(default_factory=list)
    match_results: list[EvidenceMatchResult] = field(default_factory=list)
    feedback: str = ""
    remediation: str = ""
    failure_signature: str | None = None
    identical_failure_count: int = 0
    worktree_fingerprint: str = ""
    command_spec_fingerprint: str = ""


def command_spec_fingerprint(specs: list[EvidenceCommandSpec]) -> str:
    payload = [
        {
            "command": normalize_command(spec.command),
            "cwd": normalize_cwd(spec.cwd),
            "timeout_seconds": spec.timeout_seconds,
        }
        for spec in specs
    ]
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def failure_signature(
    *,
    worktree_fingerprint: str,
    command_spec_fingerprint: str,
    results: list[EvidenceCommandResult],
    match_results: list[EvidenceMatchResult] | None = None,
) -> str:
    failure_lines: list[str] = []
    for result in results:
        if result.passed:
            continue
        failure_lines.append(
            f"{normalize_command(result.command)}@{normalize_cwd(result.cwd)}:"
            f"{result.exit_code}:{result.match_kind}"
        )
    if match_results:
        for match in match_results:
            if match.passed:
                continue
            failure_lines.append(
                f"{normalize_command(match.spec_command)}@{normalize_cwd(match.spec_cwd)}:"
                f"{match.match_kind}:{match.detail[:120]}"
            )
    body = {
        "worktree": worktree_fingerprint,
        "command_spec": command_spec_fingerprint,
        "failures": sorted(failure_lines),
    }
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _match_results_to_evidence(
    match_results: list[EvidenceMatchResult],
) -> list[EvidenceCommandResult]:
    results: list[EvidenceCommandResult] = []
    for match in match_results:
        results.append(
            EvidenceCommandResult(
                command=match.spec_command,
                cwd=match.spec_cwd,
                passed=match.passed,
                source=match.source or "captured",
                exit_code=match.exit_code,
                summary=match.detail,
                match_kind=match.match_kind,
            )
        )
    return results


def _format_gate_feedback(
    *,
    stale: bool,
    results: list[EvidenceCommandResult],
    match_results: list[EvidenceMatchResult],
) -> str:
    parts: list[str] = []
    if stale:
        parts.append(
            "Completion evidence is stale relative to the current worktree or "
            "evidence.commands spec. Re-run the declared commands in a fresh "
            "implement session."
        )
    parts.append(format_evidence_results(results))
    near_lines: list[str] = []
    for match in match_results:
        for miss in match.near_misses:
            near_lines.append(
                f"- near miss ({miss.reason}): observed {miss.observed_command!r} "
                f"cwd={miss.observed_cwd!r}; {miss.detail}"
            )
    if near_lines:
        parts.extend(["", "Near-miss diagnostics:", *near_lines[:8]])
    return "\n".join(parts).strip()


def assess_evidence_gate(
    *,
    specs: list[EvidenceCommandSpec],
    mode: EvidenceMode,
    worktree_fingerprint: str,
    stored_worktree_fingerprint: str | None,
    stored_command_spec_fingerprint: str | None,
    captured_runs: list[ObservedShellRun] | None = None,
    driver_results: list[EvidenceCommandResult] | None = None,
    prior_failure_signature: str | None = None,
    identical_failure_count: int = 0,
    max_identical_failures: int = 3,
    workspace_root: Path | None = None,
) -> EvidenceGateAssessment:
    if not specs:
        return EvidenceGateAssessment(
            passed=True,
            worktree_fingerprint=worktree_fingerprint,
            command_spec_fingerprint=command_spec_fingerprint(specs),
        )

    spec_fp = command_spec_fingerprint(specs)
    spec_stale = bool(
        stored_command_spec_fingerprint
        and stored_command_spec_fingerprint != spec_fp
    )

    spec_pairs = [(spec.command, normalize_cwd(spec.cwd)) for spec in specs]
    match_results: list[EvidenceMatchResult] = []

    if mode == EvidenceMode.CAPTURED:
        observed = captured_runs or []
        match_results = match_all_specs(
            spec_pairs,
            observed,
            workspace_root=workspace_root,
        )
        results = _match_results_to_evidence(match_results)
    else:
        results = list(driver_results or [])
        for spec in specs:
            norm_cmd = normalize_command(spec.command)
            norm_cwd = normalize_cwd(spec.cwd)
            found = next(
                (
                    result
                    for result in results
                    if normalize_command(result.command) == norm_cmd
                    and normalize_cwd(result.cwd) == norm_cwd
                ),
                None,
            )
            if found is None:
                match_results.append(
                    EvidenceMatchResult(
                        spec_command=spec.command,
                        spec_cwd=norm_cwd,
                        match_kind="missing",
                        passed=False,
                        detail="driver did not produce a result for this command",
                    )
                )
            elif not found.passed:
                match_results.append(
                    EvidenceMatchResult(
                        spec_command=spec.command,
                        spec_cwd=norm_cwd,
                        match_kind="failed_run",
                        passed=False,
                        source="driver",
                        exit_code=found.exit_code,
                        detail=found.summary or "driver execution failed",
                    )
                )

    commands_pass = all(result.passed for result in results)
    worktree_stale = bool(
        stored_worktree_fingerprint
        and stored_worktree_fingerprint != worktree_fingerprint
        and not commands_pass
    )
    stale = spec_stale or worktree_stale
    passed = not stale and commands_pass
    signature: str | None = None
    next_count = 0
    stalled = False
    remediation = ""

    if not passed:
        signature = failure_signature(
            worktree_fingerprint=worktree_fingerprint,
            command_spec_fingerprint=spec_fp,
            results=results,
            match_results=match_results,
        )
        if signature == prior_failure_signature:
            next_count = identical_failure_count + 1
        else:
            next_count = 1
        if next_count >= max_identical_failures:
            stalled = True
            remediation = (
                "Identical completion-evidence failure repeated "
                f"{next_count} times. Fix the declared evidence commands or "
                "implementation before retrying."
            )
    else:
        next_count = 0
        signature = None

    feedback = ""
    if not passed:
        feedback = _format_gate_feedback(
            stale=stale,
            results=results,
            match_results=match_results,
        )

    return EvidenceGateAssessment(
        passed=passed,
        stale=stale,
        stalled=stalled,
        results=results,
        match_results=match_results,
        feedback=feedback,
        remediation=remediation,
        failure_signature=signature,
        identical_failure_count=next_count,
        worktree_fingerprint=worktree_fingerprint,
        command_spec_fingerprint=spec_fp,
    )
