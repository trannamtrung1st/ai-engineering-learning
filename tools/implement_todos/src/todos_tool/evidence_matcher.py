"""Exact command matching for completion evidence (captured mode)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
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
            exit_code=data.get("exit_code"),
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
) -> NearMiss | None:
    obs_cmd = observed.command
    obs_cwd = normalize_cwd(observed.cwd)
    norm_spec = normalize_command(spec_command)
    norm_obs = normalize_command(obs_cmd)

    if norm_spec == norm_obs and obs_cwd != normalize_cwd(spec_cwd):
        return NearMiss(
            reason="wrong_cwd",
            observed_command=obs_cmd,
            observed_cwd=obs_cwd,
            detail=f"expected cwd {normalize_cwd(spec_cwd)!r}, observed {obs_cwd!r}",
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
) -> EvidenceMatchResult:
    """Match one declared evidence command against captured shell runs."""
    norm_spec = normalize_command(spec_command)
    norm_cwd = normalize_cwd(spec_cwd)
    near_misses: list[NearMiss] = []

    for observed in observed_runs:
        if observed.source != "captured":
            continue
        if not observed.completed:
            continue
        norm_obs = normalize_command(observed.command)
        obs_cwd = normalize_cwd(observed.cwd)
        if norm_obs == norm_spec and obs_cwd == norm_cwd:
            passed = observed.exit_code == 0
            kind: MatchKind = "exact" if passed else "failed_run"
            return EvidenceMatchResult(
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
        miss = _classify_near_miss(spec_command, spec_cwd, observed)
        if miss is not None:
            near_misses.append(miss)

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
) -> list[EvidenceMatchResult]:
    return [
        match_spec_to_observed(command, cwd, observed_runs)
        for command, cwd in specs
    ]
