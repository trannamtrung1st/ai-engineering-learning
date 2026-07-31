"""Exclude matching via pathspec adapter (proposal §§4–5, §13 items 1–21)."""

from __future__ import annotations

from pathlib import Path

import pytest

from core_tools.config.errors import ConfigError
from top_down_planning.config import (
    BUILT_IN_EXCLUDE_PATTERNS,
    SnapshotPolicy,
    compile_exclude_matcher,
    effective_exclude_patterns,
    path_is_excluded,
    resolve_config,
)
from tests.helpers import write_config


def test_built_in_patterns_cover_caches() -> None:
    assert "**/__pycache__/" in BUILT_IN_EXCLUDE_PATTERNS
    assert "**/*.py[cod]" in BUILT_IN_EXCLUDE_PATTERNS
    assert "**/.pytest_cache/" in BUILT_IN_EXCLUDE_PATTERNS
    assert "**/.mypy_cache/" in BUILT_IN_EXCLUDE_PATTERNS
    assert "**/.ruff_cache/" in BUILT_IN_EXCLUDE_PATTERNS


def test_effective_patterns_order_builtins_then_user() -> None:
    patterns = effective_exclude_patterns(
        defaults_enabled=True,
        user_patterns=["build/", "!build/keep.txt"],
    )
    assert patterns[: len(BUILT_IN_EXCLUDE_PATTERNS)] == BUILT_IN_EXCLUDE_PATTERNS
    assert patterns[-2:] == ("build/", "!build/keep.txt")


def test_empty_user_patterns_keep_defaults() -> None:
    patterns = effective_exclude_patterns(defaults_enabled=True, user_patterns=[])
    assert patterns == BUILT_IN_EXCLUDE_PATTERNS


def test_defaults_disabled_uses_only_user_patterns() -> None:
    patterns = effective_exclude_patterns(
        defaults_enabled=False,
        user_patterns=["*.tmp"],
    )
    assert patterns == ("*.tmp",)


@pytest.mark.parametrize(
    ("path", "is_directory", "expected"),
    [
        ("pkg/__pycache__/x.pyc", False, True),
        ("pkg/mod.py", False, False),
        ("pkg/mod.pyc", False, True),
        ("pkg/mod.pyo", False, True),
        ("pkg/.pytest_cache/v/cache", False, True),
        ("pkg/.mypy_cache/3.14/foo.data.json", False, True),
        ("pkg/.ruff_cache/0.1/foo", False, True),
        ("pkg/__pycache__", True, True),
    ],
)
def test_builtin_matcher_semantics(path: str, is_directory: bool, expected: bool) -> None:
    matcher = compile_exclude_matcher(BUILT_IN_EXCLUDE_PATTERNS)
    assert path_is_excluded(path, matcher=matcher, is_directory=is_directory) is expected


def test_star_and_double_star_and_root_anchor() -> None:
    matcher = compile_exclude_matcher(("*.log", "**/nested.txt", "/rooted.txt", "dir/"))
    assert path_is_excluded("a.log", matcher=matcher)
    assert path_is_excluded("sub/a.log", matcher=matcher)
    assert path_is_excluded("a/b/nested.txt", matcher=matcher)
    assert path_is_excluded("rooted.txt", matcher=matcher)
    assert not path_is_excluded("sub/rooted.txt", matcher=matcher)
    assert path_is_excluded("dir/file", matcher=matcher)
    assert path_is_excluded("dir", matcher=matcher, is_directory=True)


def test_later_patterns_and_negation_override() -> None:
    matcher = compile_exclude_matcher(("generated/**", "!generated/schema.json"))
    assert path_is_excluded("generated/a.py", matcher=matcher)
    assert not path_is_excluded("generated/schema.json", matcher=matcher)


def test_user_negation_overrides_builtin() -> None:
    patterns = effective_exclude_patterns(
        defaults_enabled=True,
        user_patterns=["!keep.pyc"],
    )
    matcher = compile_exclude_matcher(patterns)
    assert not path_is_excluded("keep.pyc", matcher=matcher)
    assert path_is_excluded("other.pyc", matcher=matcher)


def test_matcher_rejects_absolute_paths() -> None:
    matcher = compile_exclude_matcher(("*.pyc",))
    with pytest.raises(ValueError, match="canonical relative"):
        path_is_excluded("/abs/x.pyc", matcher=matcher)


def test_snapshot_policy_is_included_respects_excludes(tmp_path: Path) -> None:
    policy = SnapshotPolicy.from_config(
        {"context_snapshot": {"excludes": {"defaults": True, "patterns": []}}},
        workspace=tmp_path,
    )
    assert policy.is_included(
        "pkg/__pycache__/x.pyc",
        is_directory=False,
        explicitly_declared=False,
    ) is False
    assert policy.is_included(
        "pkg/__pycache__/x.pyc",
        is_directory=False,
        explicitly_declared=True,
    ) is True
    assert policy.is_included(
        "pkg/mod.py",
        is_directory=False,
        explicitly_declared=False,
    ) is True


def test_snapshot_policy_collect_excludes_discovered_caches(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    src = workspace / "pkg"
    cache = src / "__pycache__"
    cache.mkdir(parents=True)
    (src / "mod.py").write_text("ok\n", encoding="utf-8")
    (cache / "mod.cpython-314.pyc").write_bytes(b"\0")

    policy = SnapshotPolicy.from_config(None, workspace=workspace)
    collection = policy.collect(["pkg"])
    assert "pkg/mod.py" in collection.included
    assert "pkg/__pycache__/mod.cpython-314.pyc" not in collection.included
    assert collection.excluded_file_count >= 1


def test_context_snapshot_config_validation(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    with pytest.raises(ConfigError, match="defaults must be a boolean"):
        resolve_config(
            write_config(
                tmp_path / "bad.yaml",
                """
run:
  output_goal: Goal.
context_snapshot:
  excludes:
    defaults: yes
""",
            ),
            cwd=workspace,
        )


def test_omitted_context_snapshot_defaults_enabled(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config = resolve_config(
        write_config(
            tmp_path / "ok.yaml",
            """
run:
  output_goal: Goal.
""",
        ),
        cwd=workspace,
    )
    assert config["context_snapshot"]["excludes"]["defaults"] is True
    assert config["context_snapshot"]["excludes"]["patterns"] == []
    policy = SnapshotPolicy.from_config(config, workspace=workspace)
    assert policy.default_excludes_enabled is True
    assert policy.effective_patterns == BUILT_IN_EXCLUDE_PATTERNS
