"""Canonical paths and SnapshotPolicy shell (proposal §§8,10)."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.config import (
    SNAPSHOT_POLICY_VERSION,
    CanonicalPathCollisionError,
    CanonicalPathError,
    SnapshotPolicy,
    canonicalize_workspace_path,
    detect_canonical_collisions,
)
from top_down_planning.config.context import MISSING_RESOURCE_FILE_DIGEST
from core_tools.persistence.digests import digest_file


def test_canonicalize_relative_posix(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    target = workspace / "tools" / "pkg" / "mod.py"
    target.parent.mkdir(parents=True)
    target.write_text("x\n", encoding="utf-8")

    assert (
        canonicalize_workspace_path("tools/pkg/mod.py", workspace=workspace)
        == "tools/pkg/mod.py"
    )
    assert (
        canonicalize_workspace_path(target, workspace=workspace) == "tools/pkg/mod.py"
    )


def test_canonicalize_strips_dot_segments(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    target = workspace / "a" / "b.py"
    target.parent.mkdir(parents=True)
    target.write_text("x\n", encoding="utf-8")

    assert (
        canonicalize_workspace_path("a/./b.py", workspace=workspace) == "a/b.py"
    )


def test_canonicalize_rejects_unresolved_dotdot(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    with pytest.raises(CanonicalPathError, match=r"\.\."):
        canonicalize_workspace_path("../outside.py", workspace=workspace)
    with pytest.raises(CanonicalPathError, match=r"\.\."):
        canonicalize_workspace_path("sub/../outside.py", workspace=workspace)


def test_canonicalize_rejects_workspace_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("x\n", encoding="utf-8")

    with pytest.raises(CanonicalPathError, match="escapes"):
        canonicalize_workspace_path(outside, workspace=workspace)


def test_canonicalize_symlink_escape_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "secret.py"
    outside.write_text("secret\n", encoding="utf-8")
    link = workspace / "link.py"
    link.symlink_to(outside)

    with pytest.raises(CanonicalPathError, match="escapes"):
        canonicalize_workspace_path(link, workspace=workspace)


def test_canonicalize_symlink_inside_workspace_uses_resolved_target(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    real = workspace / "real" / "file.py"
    real.parent.mkdir(parents=True)
    real.write_text("ok\n", encoding="utf-8")
    link = workspace / "alias.py"
    link.symlink_to(real)

    assert canonicalize_workspace_path(link, workspace=workspace) == "real/file.py"


def test_detect_canonical_collisions(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    real = workspace / "real" / "file.py"
    real.parent.mkdir(parents=True)
    real.write_text("ok\n", encoding="utf-8")
    link = workspace / "alias.py"
    link.symlink_to(real)

    with pytest.raises(CanonicalPathCollisionError, match="collision"):
        detect_canonical_collisions([real, link], workspace=workspace)


def test_snapshot_policy_from_config_defaults(tmp_path: Path) -> None:
    policy = SnapshotPolicy.from_config({}, workspace=tmp_path)
    assert policy.default_excludes_enabled is True
    assert policy.user_patterns == ()
    assert policy.policy_version == SNAPSHOT_POLICY_VERSION
    assert policy.effective_patterns  # builtins present

    policy2 = SnapshotPolicy.from_config(
        {
            "context_snapshot": {
                "excludes": {"defaults": False, "patterns": ["build/", "!keep"]},
            }
        },
        workspace=tmp_path,
    )
    assert policy2.default_excludes_enabled is False
    assert policy2.user_patterns == ("build/", "!keep")
    assert policy2.effective_patterns == ("build/", "!keep")


def test_snapshot_policy_collect_hashes_and_orders(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    a = workspace / "pkg" / "a.py"
    b = workspace / "pkg" / "b.py"
    a.parent.mkdir(parents=True)
    a.write_text("a\n", encoding="utf-8")
    b.write_text("b\n", encoding="utf-8")

    policy = SnapshotPolicy.from_config(None, workspace=workspace)
    collection = policy.collect(["pkg"])

    assert list(collection.included) == ["pkg/a.py", "pkg/b.py"]
    assert collection.digests["pkg/a.py"] == digest_file(a)
    assert collection.digests["pkg/b.py"] == digest_file(b)
    assert collection.excluded_file_count == 0


def test_snapshot_policy_collect_missing_direct_file_sentinel(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    policy = SnapshotPolicy.from_config(None, workspace=workspace)
    collection = policy.collect(["missing.py"])
    assert collection.digests["missing.py"] == MISSING_RESOURCE_FILE_DIGEST
