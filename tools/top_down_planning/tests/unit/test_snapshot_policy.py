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


def test_detect_canonical_collisions_dedupes_symlink_aliases(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    real = workspace / "real" / "file.py"
    real.parent.mkdir(parents=True)
    real.write_text("ok\n", encoding="utf-8")
    link = workspace / "alias.py"
    link.symlink_to(real)

    from top_down_planning.config.snapshot_policy import detect_canonical_collisions

    mapping = detect_canonical_collisions([real, link], workspace=workspace)
    assert list(mapping) == ["real/file.py"]
    assert mapping["real/file.py"] == real.resolve()


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


def test_snapshot_policy_collect_symlink_aliases_deduped(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    real = workspace / "real" / "file.py"
    real.parent.mkdir(parents=True)
    real.write_text("ok\n", encoding="utf-8")
    link = workspace / "alias.py"
    link.symlink_to(real)

    policy = SnapshotPolicy.from_config(None, workspace=workspace)
    collection = policy.collect(["alias.py", "real/file.py"])
    assert list(collection.included) == ["real/file.py"]


def test_snapshot_policy_from_config_rejects_invalid_defaults(tmp_path: Path) -> None:
    from core_tools.config import ConfigError

    with pytest.raises(ConfigError, match="defaults must be a boolean"):
        SnapshotPolicy.from_config(
            {"context_snapshot": {"excludes": {"defaults": "yes"}}},
            workspace=tmp_path,
        )


def test_snapshot_policy_from_config_rejects_invalid_patterns(tmp_path: Path) -> None:
    from core_tools.config import ConfigError

    with pytest.raises(ConfigError, match="patterns must be a list"):
        SnapshotPolicy.from_config(
            {"context_snapshot": {"excludes": {"patterns": "generated/"}}},
            workspace=tmp_path,
        )
    with pytest.raises(ConfigError, match="non-empty strings"):
        SnapshotPolicy.from_config(
            {"context_snapshot": {"excludes": {"patterns": ["", "ok/"]}}},
            workspace=tmp_path,
        )


def test_snapshot_policy_collect_missing_direct_file_sentinel(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    policy = SnapshotPolicy.from_config(None, workspace=workspace)
    collection = policy.collect(["missing.py"])
    assert collection.digests["missing.py"] == MISSING_RESOURCE_FILE_DIGEST


def test_directory_walk_rejects_escape_symlink(tmp_path: Path) -> None:
    """§8 / §13 #41: escape symlinks discovered during directory walks fail snapshot build."""

    from top_down_planning.config import build_context_snapshot_payload, resolve_config
    from tests.helpers import write_config

    workspace = tmp_path / "ws"
    workspace.mkdir()
    pkg = workspace / "pkg"
    pkg.mkdir()
    (pkg / "ok.py").write_text("ok\n", encoding="utf-8")
    outside = tmp_path / "outside.py"
    outside.write_text("secret\n", encoding="utf-8")
    (pkg / "escape.py").symlink_to(outside)

    config = resolve_config(
        write_config(
            tmp_path / "cfg.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  producer:
    resources:
      - pkg/
""",
        ),
        cwd=workspace,
    )
    with pytest.raises(CanonicalPathError, match="escapes"):
        build_context_snapshot_payload(config, workspace=workspace)
