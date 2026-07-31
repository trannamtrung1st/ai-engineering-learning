"""Gitignore-style snapshot exclusion matching via pathspec (proposal §§4–5,15).

All matching uses canonical workspace-relative POSIX paths. Direct ``pathspec``
usage stays inside this adapter; orchestration and policy code call these helpers
only.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Sequence

from pathspec import PathSpec
from pathspec.patterns.gitwildmatch import GitWildMatchPatternError

from core_tools.config.errors import ConfigError

# Built-in generated-artifact excludes (proposal §4). Order is semantic.
BUILT_IN_EXCLUDE_PATTERNS: tuple[str, ...] = (
    "**/__pycache__/",
    "**/*.py[cod]",
    "**/.pytest_cache/",
    "**/.mypy_cache/",
    "**/.ruff_cache/",
)


def effective_exclude_patterns(
    *,
    defaults_enabled: bool,
    user_patterns: Sequence[str],
) -> tuple[str, ...]:
    """Built-ins (when enabled) followed by user patterns in declared order."""

    patterns: list[str] = []
    if defaults_enabled:
        patterns.extend(BUILT_IN_EXCLUDE_PATTERNS)
    patterns.extend(str(item) for item in user_patterns)
    return tuple(patterns)


@lru_cache(maxsize=64)
def _compile_gitwildmatch(patterns: tuple[str, ...]) -> PathSpec:
    # pathspec's ``gitignore`` dialect is the supported gitwildmatch successor.
    try:
        return PathSpec.from_lines("gitignore", patterns)
    except GitWildMatchPatternError as exc:
        raise ConfigError(
            f"invalid context_snapshot.excludes pattern: {exc}",
            path="context_snapshot.excludes.patterns",
        ) from exc
    except ValueError as exc:
        raise ConfigError(
            f"invalid context_snapshot.excludes pattern: {exc}",
            path="context_snapshot.excludes.patterns",
        ) from exc


def compile_exclude_matcher(patterns: Sequence[str]) -> PathSpec:
    """Compile ordered gitignore/gitwildmatch patterns; empty excludes nothing."""

    compiled = tuple(str(item) for item in patterns)
    if not compiled:
        return PathSpec.from_lines("gitignore", [])
    return _compile_gitwildmatch(compiled)


def path_is_excluded(
    relative_path: str,
    *,
    matcher: PathSpec,
    is_directory: bool = False,
) -> bool:
    """Return True when ``relative_path`` matches the exclusion matcher.

    ``relative_path`` must already be a canonical workspace-relative POSIX path.
    Directory candidates are probed with a trailing ``/`` so directory-only
    patterns (``dir/``) apply.
    """

    if not relative_path or relative_path.startswith("/"):
        raise ValueError(
            f"exclude matching requires canonical relative POSIX path, got {relative_path!r}"
        )
    candidate = relative_path
    if is_directory and not candidate.endswith("/"):
        candidate = f"{candidate}/"
    return bool(matcher.match_file(candidate))


__all__ = [
    "BUILT_IN_EXCLUDE_PATTERNS",
    "compile_exclude_matcher",
    "effective_exclude_patterns",
    "path_is_excluded",
]
