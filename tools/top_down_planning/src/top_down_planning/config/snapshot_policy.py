"""Canonical workspace-relative paths and SnapshotPolicy (proposal §§8,10).

Symlink behavior matches the inspected baseline: ``Path.resolve()`` follows
symlinks; identity uses the resolved target; paths that resolve outside the
workspace are rejected. Exclusion matching uses the pathspec adapter (§§4–5).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core_tools.config.errors import ConfigError
from core_tools.persistence.digests import digest_file

from top_down_planning.config.exclude_matching import (
    compile_exclude_matcher,
    effective_exclude_patterns,
    path_is_excluded,
)

SNAPSHOT_POLICY_VERSION = "snapshot-excludes-v1"

_GLOB_METACHARACTERS = frozenset("*?[]")


def _has_glob_metacharacters(value: str) -> bool:
    return any(char in _GLOB_METACHARACTERS for char in value)


class CanonicalPathError(ValueError):
    """Path cannot be represented as a canonical workspace-relative key."""


class CanonicalPathCollisionError(CanonicalPathError):
    """Two distinct filesystem paths share one canonical binding key."""

    def __init__(self, canonical: str, first: Path, second: Path) -> None:
        super().__init__(
            f"canonical path collision for {canonical!r}: {first} and {second}"
        )
        self.canonical = canonical
        self.first = first
        self.second = second


def canonicalize_workspace_path(
    path: str | Path,
    *,
    workspace: Path,
) -> str:
    """Return a canonical workspace-relative POSIX path for binding keys.

    Rules (proposal §8):
    - Persist workspace-relative paths with ``/`` separators.
    - Remove redundant ``.`` components via ``Path`` resolution.
    - Reject unresolved ``..`` segments in relative inputs.
    - Reject paths that escape the workspace after symlink-following resolve.
    - Preserve intentional case behavior of the resolved relative path.
    - Absolute inputs are accepted only when they resolve inside the workspace
      (collection from discovered ``Path`` objects); callers that must reject
      absolute evidence refs should use ``canonicalize_evidence_ref``.
    """

    workspace_resolved = workspace.resolve()
    raw = Path(path)

    if not raw.is_absolute():
        if any(part == ".." for part in raw.parts):
            raise CanonicalPathError(
                f"path rejects unresolved '..' components: {path}"
            )
        lexical = Path(*[part for part in raw.parts if part != "."])
        candidate = (workspace_resolved / lexical).resolve()
    else:
        candidate = raw.resolve()

    try:
        relative = candidate.relative_to(workspace_resolved)
    except ValueError as exc:
        raise CanonicalPathError(
            f"path escapes workspace {workspace_resolved}: {path}"
        ) from exc

    if relative == Path("."):
        raise CanonicalPathError(
            f"path resolves to workspace root, not a bindable file key: {path}"
        )

    return relative.as_posix()


def canonicalize_evidence_ref(ref: str, *, workspace: Path) -> str:
    """Canonicalize a production evidence ``ref`` (proposal §8).

    Evidence refs must already be workspace-relative. Absolute paths, unresolved
    ``..``, workspace escapes, and symlink-resolved escapes are rejected.
    """

    text = str(ref or "").strip()
    if not text:
        raise CanonicalPathError("evidence ref must be a non-empty relative path")
    raw = Path(text)
    if raw.is_absolute() or text.startswith(("/", "\\")) or (len(text) >= 2 and text[1] == ":"):
        raise CanonicalPathError(
            f"evidence ref must be workspace-relative, got absolute: {ref!r}"
        )
    return canonicalize_workspace_path(text, workspace=workspace)

def detect_canonical_collisions(
    paths: Iterable[Path],
    *,
    workspace: Path,
) -> dict[str, Path]:
    """Map canonical keys to paths; dedupe symlink aliases with the same resolve target."""

    mapping: dict[str, Path] = {}
    for path in paths:
        key = canonicalize_workspace_path(path, workspace=workspace)
        prior = mapping.get(key)
        if prior is not None:
            if prior.resolve() != path.resolve():
                raise CanonicalPathCollisionError(key, prior, path)
            continue
        mapping[key] = path.resolve()
    return mapping


@dataclass(frozen=True)
class SnapshotCollection:
    """Result of SnapshotPolicy.collect (included files + diagnostic counters)."""

    included: dict[str, Path]
    digests: dict[str, str]
    excluded_file_count: int = 0
    excluded_directory_count: int = 0
    policy_version: str = SNAPSHOT_POLICY_VERSION


@dataclass(frozen=True)
class SnapshotPolicy:
    """Centralized snapshot path/exclusion policy (proposal §10)."""

    workspace: Path
    default_excludes_enabled: bool = True
    user_patterns: tuple[str, ...] = ()
    effective_patterns: tuple[str, ...] = ()
    policy_version: str = SNAPSHOT_POLICY_VERSION
    _exclude_matcher: Any = None

    def __post_init__(self) -> None:
        matcher = (
            compile_exclude_matcher(self.effective_patterns)
            if self.effective_patterns
            else None
        )
        object.__setattr__(self, "_exclude_matcher", matcher)

    @classmethod
    def from_config(
        cls,
        config: dict[str, Any] | None,
        *,
        workspace: Path,
    ) -> SnapshotPolicy:
        """Build policy from resolved config; omitted section → defaults on."""

        section = (config or {}).get("context_snapshot")
        excludes: dict[str, Any] = {}
        if isinstance(section, dict):
            raw_excludes = section.get("excludes")
            if isinstance(raw_excludes, dict):
                excludes = raw_excludes

        defaults = excludes.get("defaults", True)
        if not isinstance(defaults, bool):
            raise ConfigError(
                "context_snapshot.excludes.defaults must be a boolean",
                path="context_snapshot.excludes.defaults",
            )

        patterns_raw = excludes.get("patterns", [])
        if not isinstance(patterns_raw, list):
            raise ConfigError(
                "context_snapshot.excludes.patterns must be a list",
                path="context_snapshot.excludes.patterns",
            )
        for index, pattern in enumerate(patterns_raw):
            if not isinstance(pattern, str) or not pattern.strip():
                raise ConfigError(
                    "context_snapshot.excludes.patterns entries must be non-empty strings",
                    path=f"context_snapshot.excludes.patterns[{index}]",
                )
        user_patterns = tuple(patterns_raw)
        patterns = effective_exclude_patterns(
            defaults_enabled=defaults,
            user_patterns=user_patterns,
        )

        return cls(
            workspace=workspace.resolve(),
            default_excludes_enabled=defaults,
            user_patterns=user_patterns,
            effective_patterns=patterns,
            policy_version=SNAPSHOT_POLICY_VERSION,
        )

    def canonicalize(self, path: str | Path) -> str:
        return canonicalize_workspace_path(path, workspace=self.workspace)

    def is_included(
        self,
        relative_path: str,
        *,
        is_directory: bool,
        explicitly_declared: bool,
    ) -> bool:
        """Return whether a canonical relative path should enter the snapshot.

        Direct/explicit file declarations always override exclusions (§6).
        """

        if explicitly_declared:
            return True
        if self._exclude_matcher is None:
            return True
        return not path_is_excluded(
            relative_path,
            matcher=self._exclude_matcher,
            is_directory=is_directory,
        )

    def collect(
        self,
        resources: Sequence[str | Path],
        *,
        missing_digest: str | None = None,
    ) -> SnapshotCollection:
        """Expand resources, apply inclusion hooks, canonicalize, hash files.

        ``resources`` entries are workspace-relative path strings (or absolute
        paths under the workspace). Glob patterns (``*``, ``?``, ``[]``) expand
        file-only, non-recursively via ``Path.glob``. Declared directories are
        walked; discovered children are subject to excludes. Declared files always
        bind. Symlink aliases that canonicalize to the same key are deduped when
        they resolve to the same target; distinct paths sharing one key raise.

        Traversal tradeoff (proposal §5): directory expansion uses post-filter
        after ``rglob`` rather than pruning ignored directories. Safe pruning is
        deferred because later negated patterns can re-include descendants;
        correctness of matching semantics takes priority over traversal cost.
        """

        from top_down_planning.config.context import MISSING_RESOURCE_FILE_DIGEST

        sentinel = missing_digest if missing_digest is not None else MISSING_RESOURCE_FILE_DIGEST
        workspace_resolved = self.workspace.resolve()
        included: dict[str, Path] = {}
        digests: dict[str, str] = {}
        excluded_files = 0
        excluded_dirs = 0

        def add_file(path: Path, *, explicitly_declared: bool) -> None:
            nonlocal excluded_files
            key = self.canonicalize(path)
            if not self.is_included(
                key,
                is_directory=False,
                explicitly_declared=explicitly_declared,
            ):
                excluded_files += 1
                return
            prior = included.get(key)
            if prior is not None:
                if prior.resolve() != path.resolve():
                    raise CanonicalPathCollisionError(key, prior, path)
                return
            included[key] = path.resolve()
            digests[key] = digest_file(path) if path.is_file() else sentinel

        for entry in resources:
            configured_text = str(entry).strip()
            if not configured_text:
                continue

            if _has_glob_metacharacters(configured_text):
                for match in sorted(workspace_resolved.glob(configured_text)):
                    if match.is_file():
                        add_file(match.resolve(), explicitly_declared=False)
                continue

            configured = Path(configured_text)
            if configured.is_absolute():
                candidate = configured.resolve()
            else:
                if any(part == ".." for part in configured.parts):
                    raise CanonicalPathError(
                        f"path rejects unresolved '..' components: {entry}"
                    )
                candidate = (workspace_resolved / configured).resolve()

            try:
                candidate.relative_to(workspace_resolved)
            except ValueError as exc:
                raise CanonicalPathError(
                    f"path escapes workspace {workspace_resolved}: {entry}"
                ) from exc

            if candidate.is_file():
                add_file(candidate, explicitly_declared=True)
                continue

            if candidate.is_dir():
                # Declared directories are always walked; children use excludes.
                for file_path in sorted(candidate.rglob("*")):
                    if file_path.is_file():
                        add_file(file_path, explicitly_declared=False)
                continue

            add_file(candidate, explicitly_declared=True)

        ordered_keys = sorted(included)
        return SnapshotCollection(
            included={key: included[key] for key in ordered_keys},
            digests={key: digests[key] for key in ordered_keys},
            excluded_file_count=excluded_files,
            excluded_directory_count=excluded_dirs,
            policy_version=self.policy_version,
        )


__all__ = [
    "SNAPSHOT_POLICY_VERSION",
    "CanonicalPathCollisionError",
    "CanonicalPathError",
    "SnapshotCollection",
    "SnapshotPolicy",
    "canonicalize_workspace_path",
    "canonicalize_evidence_ref",
    "detect_canonical_collisions",
]
