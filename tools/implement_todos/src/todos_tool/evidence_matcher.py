"""Exact command matching for completion evidence (captured mode)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

MatchKind = Literal["exact", "missing", "near_miss", "failed_run"]


def normalize_command(command: str) -> str:
    """Whitespace-only, case-sensitive normalization."""
    return " ".join(command.strip().split())


def normalize_cwd(cwd: str | None) -> str:
    if cwd is None or not str(cwd).strip():
        return "."
    text = str(cwd).replace("\\", "/").strip().rstrip("/")
    return text or "."


_CD_PREFIX_RE = re.compile(r"^cd\s+(\S+)\s*&&\s*(.+)$", re.IGNORECASE | re.DOTALL)


def _resolve_cd_target(base_cwd: str, cd_target: str, workspace_root: Path | None) -> str:
    target = cd_target.strip().replace("\\", "/")
    if workspace_root is not None:
        root = workspace_root.resolve()
        if target.startswith("/"):
            resolved = Path(target).resolve()
        else:
            base = normalize_cwd(base_cwd)
            base_path = root if base == "." else (root / base).resolve()
            resolved = (base_path / target).resolve()
        try:
            relative = resolved.relative_to(root)
            if not relative.parts:
                return "."
            return relative.as_posix()
        except ValueError:
            pass

    if target.startswith("/"):
        return resolve_evidence_cwd(target, workspace_root)

    base = normalize_cwd(base_cwd)
    if base == ".":
        return normalize_cwd(target)

    if workspace_root is not None and not Path(base).is_absolute():
        absolute_base = (workspace_root / base).resolve()
        return (absolute_base / target).resolve().relative_to(
            workspace_root.resolve()
        ).as_posix()
    return normalize_cwd(f"{base}/{target}")


def expand_observed_shell_runs(
    runs: list[ObservedShellRun],
    *,
    workspace_root: Path | None = None,
) -> list[ObservedShellRun]:
    """Add normalized variants for common `cd … && command` capture shapes."""
    expanded: list[ObservedShellRun] = []
    seen: set[tuple[str, str, bool, int | None]] = set()

    def add(run: ObservedShellRun) -> None:
        key = (
            normalize_command(run.command),
            normalize_cwd(run.cwd),
            run.completed,
            run.exit_code,
        )
        if key in seen:
            return
        seen.add(key)
        expanded.append(run)

    for run in runs:
        add(run)
        match = _CD_PREFIX_RE.match(run.command.strip())
        if not match:
            continue
        inner_command = match.group(2).strip()
        if not inner_command:
            continue
        add(
            ObservedShellRun(
                command=inner_command,
                cwd=_resolve_cd_target(run.cwd, match.group(1), workspace_root),
                completed=run.completed,
                exit_code=run.exit_code,
                source=run.source,
            )
        )
    return expanded


def resolve_evidence_cwd(cwd: str | None, workspace_root: Path | None = None) -> str:
    """Map an observed shell cwd to the same relative form used by evidence specs."""
    normalized = normalize_cwd(cwd)
    if workspace_root is None:
        return normalized

    root = workspace_root.resolve()
    candidate = Path(normalized)
    if not candidate.is_absolute():
        return normalized

    try:
        relative = candidate.resolve().relative_to(root)
    except ValueError:
        return normalized

    if not relative.parts:
        return "."
    return relative.as_posix()


def cwd_matches_spec(
    spec_cwd: str,
    observed_cwd: str,
    workspace_root: Path | None = None,
) -> bool:
    """Return True when observed cwd satisfies a declared relative evidence cwd."""
    return resolve_evidence_cwd(spec_cwd, workspace_root=None) == resolve_evidence_cwd(
        observed_cwd,
        workspace_root=workspace_root,
    )


@dataclass
class NearMiss:
    reason: str
    observed_command: str
    observed_cwd: str = "."
    detail: str = ""


@dataclass
class ObservedShellRun:
    command: str
    cwd: str = "."
    completed: bool = False
    exit_code: int | None = None
    source: str = "captured"

    @classmethod
    def from_dict(cls, data: dict) -> ObservedShellRun:
        return cls(
            command=str(data["command"]),
            cwd=normalize_cwd(data.get("cwd")),
            completed=bool(data.get("completed", False)),
            exit_code=data.get("exit_code", data.get("exitCode")),
            source=str(data.get("source", "captured")),
        )

    def to_dict(self) -> dict:
        payload = {
            "command": self.command,
            "cwd": self.cwd,
            "completed": self.completed,
            "source": self.source,
        }
        if self.exit_code is not None:
            payload["exit_code"] = self.exit_code
        return payload


@dataclass
class EvidenceMatchResult:
    spec_command: str
    spec_cwd: str
    match_kind: MatchKind
    passed: bool
    observed_command: str | None = None
    observed_cwd: str | None = None
    source: str | None = None
    exit_code: int | None = None
    near_misses: list[NearMiss] = field(default_factory=list)
    detail: str = ""


_CHAIN_SPLIT_RE = re.compile(r"\s*&&\s*")
_PIPE_RE = re.compile(r"[|]|>>|>|<<|<")
_WRAPPER_RE = re.compile(r"^(bash|sh|zsh)\s+-[c]\s+", re.IGNORECASE)


def _classify_near_miss(
    spec_command: str,
    spec_cwd: str,
    observed: ObservedShellRun,
    *,
    workspace_root: Path | None = None,
) -> NearMiss | None:
    obs_cmd = observed.command
    obs_cwd = normalize_cwd(observed.cwd)
    norm_spec = normalize_command(spec_command)
    norm_obs = normalize_command(obs_cmd)

    if norm_spec == norm_obs and not cwd_matches_spec(
        spec_cwd,
        observed.cwd,
        workspace_root=workspace_root,
    ):
        expected = resolve_evidence_cwd(spec_cwd, workspace_root=None)
        observed_resolved = resolve_evidence_cwd(observed.cwd, workspace_root=workspace_root)
        return NearMiss(
            reason="wrong_cwd",
            observed_command=obs_cmd,
            observed_cwd=obs_cwd,
            detail=(
                f"expected cwd {expected!r}, observed {obs_cwd!r} "
                f"(resolved {observed_resolved!r})"
            ),
        )

    if norm_spec.lower() == norm_obs.lower() and norm_spec != norm_obs:
        return NearMiss(
            reason="case_drift",
            observed_command=obs_cmd,
            observed_cwd=obs_cwd,
            detail="command differs only by case; evidence matching is case-sensitive",
        )

    if _PIPE_RE.search(obs_cmd):
        return NearMiss(
            reason="piped_variant",
            observed_command=obs_cmd,
            observed_cwd=obs_cwd,
            detail="pipelines and redirections are not accepted as evidence",
        )

    if _WRAPPER_RE.match(obs_cmd.strip()):
        return NearMiss(
            reason="shell_wrapper",
            observed_command=obs_cmd,
            observed_cwd=obs_cwd,
            detail="shell wrappers such as bash -c are not accepted",
        )

    lowered = obs_cmd.strip()
    if lowered.startswith("cd ") and "&&" in lowered:
        tail = _CHAIN_SPLIT_RE.split(lowered, maxsplit=1)
        if len(tail) == 2 and normalize_command(tail[1]) == norm_spec:
            return NearMiss(
                reason="cd_prefix_wrapper",
                observed_command=obs_cmd,
                observed_cwd=obs_cwd,
                detail="use the shell tool working-directory field instead of cd … &&",
            )

    if "&&" in obs_cmd or ";" in obs_cmd:
        parts = re.split(r"\s*(?:&&|;)\s*", obs_cmd)
        if any(normalize_command(part) == norm_spec for part in parts if part.strip()):
            if normalize_command(obs_cmd) != norm_spec:
                return NearMiss(
                    reason="extra_chained_command",
                    observed_command=obs_cmd,
                    observed_cwd=obs_cwd,
                    detail="extra chained commands are not accepted; run only the declared command",
                )

    if norm_obs != norm_spec and (
        norm_spec in norm_obs or norm_obs in norm_spec
    ):
        return NearMiss(
            reason="command_variant",
            observed_command=obs_cmd,
            observed_cwd=obs_cwd,
            detail="observed command is not an exact normalized match",
        )

    return None


def match_spec_to_observed(
    spec_command: str,
    spec_cwd: str,
    observed_runs: list[ObservedShellRun],
    *,
    workspace_root: Path | None = None,
) -> EvidenceMatchResult:
    """Match one declared evidence command against captured shell runs."""
    norm_spec = normalize_command(spec_command)
    norm_cwd = normalize_cwd(spec_cwd)
    near_misses: list[NearMiss] = []
    observed_runs = expand_observed_shell_runs(
        observed_runs,
        workspace_root=workspace_root,
    )

    last_exact_match: EvidenceMatchResult | None = None
    last_successful_match: EvidenceMatchResult | None = None

    for observed in observed_runs:
        if observed.source != "captured":
            continue
        if not observed.completed:
            continue
        norm_obs = normalize_command(observed.command)
        obs_cwd = normalize_cwd(observed.cwd)
        if norm_obs == norm_spec and cwd_matches_spec(
            spec_cwd,
            observed.cwd,
            workspace_root=workspace_root,
        ):
            passed = observed.exit_code == 0
            kind: MatchKind = "exact" if passed else "failed_run"
            exact_match = EvidenceMatchResult(
                spec_command=spec_command,
                spec_cwd=norm_cwd,
                match_kind=kind,
                passed=passed,
                observed_command=observed.command,
                observed_cwd=obs_cwd,
                source=observed.source,
                exit_code=observed.exit_code,
                detail="" if passed else f"exit_code={observed.exit_code}",
            )
            last_exact_match = exact_match
            if passed:
                last_successful_match = exact_match
            continue
        miss = _classify_near_miss(
            spec_command,
            spec_cwd,
            observed,
            workspace_root=workspace_root,
        )
        if miss is not None:
            near_misses.append(miss)

    if last_successful_match is not None:
        return last_successful_match
    if last_exact_match is not None:
        return last_exact_match

    bounded = near_misses[:5]
    detail = bounded[0].detail if bounded else "no matching shell execution observed"
    return EvidenceMatchResult(
        spec_command=spec_command,
        spec_cwd=norm_cwd,
        match_kind="missing" if not bounded else "near_miss",
        passed=False,
        near_misses=bounded,
        detail=detail,
    )


def match_all_specs(
    specs: list[tuple[str, str]],
    observed_runs: list[ObservedShellRun],
    *,
    workspace_root: Path | None = None,
) -> list[EvidenceMatchResult]:
    normalized_runs = expand_observed_shell_runs(
        observed_runs,
        workspace_root=workspace_root,
    )
    return [
        match_spec_to_observed(
            command,
            cwd,
            normalized_runs,
            workspace_root=workspace_root,
        )
        for command, cwd in specs
    ]
