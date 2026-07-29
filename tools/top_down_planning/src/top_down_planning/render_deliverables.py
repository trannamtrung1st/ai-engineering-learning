"""Workspace deliverable discovery and digest computation.

Render deliverables are UTF-8 text files at workspace-relative paths declared by
render sessions. Configurable gitignore-style patterns exclude paths from discovery.
Canonical planning state under the run output directory is always excluded.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pathspec

from top_down_planning.digest import digest_file, digest_text
from top_down_planning.persistence import state_dir


@dataclass(frozen=True)
class DeliverableOutput:
    files: dict[str, str]
    digest: str


@dataclass(frozen=True)
class ArtifactIgnoreMatcher:
    """Gitignore-style workspace path filter with canonical-state protection."""

    _spec: pathspec.PathSpec | None
    _protected_prefixes: tuple[str, ...]

    def is_ignored(self, relative_path: str) -> bool:
        normalized = relative_path.replace("\\", "/").strip()
        if not normalized:
            return True
        for prefix in self._protected_prefixes:
            if normalized == prefix or normalized.startswith(prefix + "/"):
                return True
        if self._spec is None:
            return False
        return self._spec.match_file(normalized)


def canonical_state_prefix(workspace: Path, output_dir: Path) -> str | None:
    workspace = workspace.resolve()
    state_path = state_dir(output_dir).resolve()
    try:
        return state_path.relative_to(workspace).as_posix()
    except ValueError:
        return None


def is_utf8_text_file(path: Path) -> bool:
    try:
        path.read_bytes().decode("utf-8")
    except (UnicodeDecodeError, OSError):
        return False
    return True


def build_artifact_ignore_matcher(
    workspace: Path,
    output_dir: Path,
    patterns: list[str],
) -> ArtifactIgnoreMatcher:
    normalized_patterns = [pattern.strip() for pattern in patterns if pattern.strip()]
    spec = (
        pathspec.PathSpec.from_lines("gitignore", normalized_patterns)
        if normalized_patterns
        else None
    )
    prefix = canonical_state_prefix(workspace, output_dir)
    protected_prefixes = (prefix,) if prefix is not None else ()
    return ArtifactIgnoreMatcher(
        _spec=spec,
        _protected_prefixes=protected_prefixes,
    )


def filter_deliverable_candidates(
    paths: Iterable[str],
    matcher: ArtifactIgnoreMatcher,
) -> list[str]:
    """Drop ignored workspace paths from candidate artifact paths."""
    return [path for path in paths if not matcher.is_ignored(path)]


def compute_deliverable_digest(files: dict[str, str]) -> str:
    payload = {path: files[path] for path in sorted(files)}
    return digest_text(
        "\n".join(f"{path}\n{payload[path]}" for path in payload)
    )


def collect_deliverable_output(
    workspace: Path,
    artifact_paths: list[str],
    matcher: ArtifactIgnoreMatcher,
) -> DeliverableOutput:
    workspace = workspace.resolve()
    files: dict[str, str] = {}
    for relative_path in sorted(artifact_paths):
        if matcher.is_ignored(relative_path):
            raise ValueError(f"ignored workspace path at {relative_path!r}")
        destination = workspace / relative_path
        if not destination.is_file():
            raise ValueError(f"missing deliverable at {relative_path!r}")
        files[relative_path] = destination.read_text(encoding="utf-8")
    return DeliverableOutput(files=files, digest=compute_deliverable_digest(files))


def discover_workspace_artifacts(
    workspace: Path,
    matcher: ArtifactIgnoreMatcher,
) -> list[str]:
    workspace = workspace.resolve()
    artifacts: list[str] = []
    for path in sorted(workspace.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(workspace).as_posix()
        if matcher.is_ignored(relative):
            continue
        artifacts.append(relative)
    return artifacts


def snapshot_workspace_files(
    workspace: Path,
    matcher: ArtifactIgnoreMatcher,
) -> dict[str, str]:
    """Return relative path -> content digest for tracked workspace files."""
    workspace = workspace.resolve()
    snapshots: dict[str, str] = {}
    for relative in discover_workspace_artifacts(workspace, matcher):
        snapshots[relative] = digest_file(workspace / relative)
    return snapshots


def diff_workspace_snapshots(
    before: dict[str, str],
    after: dict[str, str],
) -> list[str]:
    changed = {
        path
        for path in set(before) | set(after)
        if before.get(path) != after.get(path)
    }
    return sorted(changed)
