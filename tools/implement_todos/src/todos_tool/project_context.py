"""Immutable project context loaded once per run."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ContextFileRef:
    path: str
    required: bool = False


@dataclass(frozen=True)
class ResolvedContextFile:
    path: str
    required: bool
    exists: bool


@dataclass(frozen=True)
class EvidencePolicy:
    required_commands: tuple[str, ...] = ()
    forbidden_command_patterns: tuple[str, ...] = ()


@dataclass(frozen=True)
class AuthorityPolicy:
    forbidden_path_globs: tuple[str, ...] = ()


@dataclass(frozen=True)
class GitPolicy:
    commit_prefix: str = "agent:"


@dataclass(frozen=True)
class ProjectContext:
    schema_version: int
    context_files: tuple[ContextFileRef, ...]
    instructions: tuple[str, ...]
    authority: AuthorityPolicy
    evidence: EvidencePolicy
    git: GitPolicy
    source: str = "defaults"

    @classmethod
    def neutral(cls) -> ProjectContext:
        return cls(
            schema_version=1,
            context_files=(),
            instructions=(),
            authority=AuthorityPolicy(),
            evidence=EvidencePolicy(),
            git=GitPolicy(),
            source="defaults",
        )

    def with_git_prefix(self, prefix: str | None) -> ProjectContext:
        if prefix is None:
            return self
        return ProjectContext(
            schema_version=self.schema_version,
            context_files=self.context_files,
            instructions=self.instructions,
            authority=self.authority,
            evidence=self.evidence,
            git=GitPolicy(commit_prefix=prefix),
            source=self.source,
        )

    def with_extra_context_files(
        self,
        refs: tuple[ContextFileRef, ...],
    ) -> ProjectContext:
        merged = list(self.context_files)
        seen = {ref.path for ref in merged}
        for ref in refs:
            if ref.path not in seen:
                merged.append(ref)
                seen.add(ref.path)
        return ProjectContext(
            schema_version=self.schema_version,
            context_files=tuple(merged),
            instructions=self.instructions,
            authority=self.authority,
            evidence=self.evidence,
            git=self.git,
            source=self.source,
        )
