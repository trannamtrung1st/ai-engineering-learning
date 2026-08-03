"""Resource-kind exclusion wiring and context-spec identity (proposal §§6–7)."""

from __future__ import annotations

from pathlib import Path

from core_tools.persistence.digests import digest_file
from top_down_planning.config import (
    SNAPSHOT_POLICY_VERSION,
    build_context_snapshot_payload,
    build_context_spec_payload,
    compute_context_spec_digest_from_config,
    resolve_config,
)
from top_down_planning.config.context import MISSING_RESOURCE_FILE_DIGEST
from tests.helpers import write_config


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    return workspace


def test_direct_file_overrides_exclusion(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    target = workspace / "generated" / "schema.json"
    target.parent.mkdir()
    target.write_text("{}\n", encoding="utf-8")
    config = resolve_config(
        write_config(
            tmp_path / "cfg.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  producer:
    resources:
      - generated/schema.json
context_snapshot:
  excludes:
    defaults: false
    patterns:
      - "generated/"
""",
        ),
        cwd=workspace,
    )
    binding = build_context_snapshot_payload(config, workspace=workspace)
    assert binding["resource_digests"]["generated/schema.json"] == digest_file(target)


def test_directory_expansion_applies_excludes(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    pkg = workspace / "pkg"
    cache = pkg / "__pycache__"
    cache.mkdir(parents=True)
    (pkg / "mod.py").write_text("ok\n", encoding="utf-8")
    (cache / "mod.cpython-314.pyc").write_bytes(b"\0")
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
    binding = build_context_snapshot_payload(config, workspace=workspace)
    assert "pkg/mod.py" in binding["resource_digests"]
    assert "pkg/__pycache__/mod.cpython-314.pyc" not in binding["resource_digests"]


def test_glob_expansion_filters_matches_without_recursive_dirs(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    nested = workspace / "tools" / "pkg"
    nested.mkdir(parents=True)
    (workspace / "tools" / "a.py").write_text("a\n", encoding="utf-8")
    (nested / "b.py").write_text("b\n", encoding="utf-8")
    (workspace / "tools" / "skip.pyc").write_bytes(b"\0")
    config = resolve_config(
        write_config(
            tmp_path / "cfg.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  producer:
    resources:
      - "tools/*.py"
context_snapshot:
  excludes:
    defaults: true
    patterns: []
""",
        ),
        cwd=workspace,
    )
    binding = build_context_snapshot_payload(config, workspace=workspace)
    assert "tools/a.py" in binding["resource_digests"]
    assert "tools/pkg/b.py" not in binding["resource_digests"]

    config_pyc = resolve_config(
        write_config(
            tmp_path / "cfg2.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  producer:
    resources:
      - "tools/*"
""",
        ),
        cwd=workspace,
    )
    binding_pyc = build_context_snapshot_payload(config_pyc, workspace=workspace)
    assert "tools/skip.pyc" not in binding_pyc["resource_digests"]
    assert "tools/a.py" in binding_pyc["resource_digests"]


def test_missing_direct_file_keeps_sentinel(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    config = resolve_config(
        write_config(
            tmp_path / "cfg.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  producer:
    resources:
      - missing.py
""",
        ),
        cwd=workspace,
    )
    binding = build_context_snapshot_payload(config, workspace=workspace)
    assert binding["resource_digests"]["missing.py"] == MISSING_RESOURCE_FILE_DIGEST


def test_skills_not_filtered_by_excludes(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    skill_dir = workspace / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# demo\n\nbody\n", encoding="utf-8")
    config = resolve_config(
        write_config(
            tmp_path / "cfg.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  bundled_skills: false
  producer:
    skills:
      - skills/demo
context_snapshot:
  excludes:
    defaults: false
    patterns:
      - "skills/**"
""",
        ),
        cwd=workspace,
    )
    binding = build_context_snapshot_payload(config, workspace=workspace)
    assert "skills/demo/SKILL.md" in binding["skill_digests"]
    assert binding["resource_digests"] == {}


def test_context_spec_includes_exclusion_policy(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    config = resolve_config(
        write_config(
            tmp_path / "cfg.yaml",
            """
run:
  output_goal: Goal.
context_snapshot:
  excludes:
    defaults: true
    patterns:
      - "build/"
""",
        ),
        cwd=workspace,
    )
    spec = build_context_spec_payload(config, workspace=workspace)
    assert spec["context_snapshot"] == {
        "excludes": {"defaults": True, "patterns": ["build/"]},
        "policy_version": SNAPSHOT_POLICY_VERSION,
    }
    assert SNAPSHOT_POLICY_VERSION == "snapshot-excludes-v1"


def test_exclusion_policy_changes_context_spec_digest(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)

    def digest_for(name: str, body: str) -> str:
        return compute_context_spec_digest_from_config(
            resolve_config(write_config(tmp_path / name, body), cwd=workspace),
            workspace=workspace,
        )

    base = digest_for(
        "base.yaml",
        """
run:
  output_goal: Goal.
context_snapshot:
  excludes:
    defaults: true
    patterns:
      - "generated/"
""",
    )
    disabled = digest_for(
        "disabled.yaml",
        """
run:
  output_goal: Goal.
context_snapshot:
  excludes:
    defaults: false
    patterns:
      - "generated/"
""",
    )
    added = digest_for(
        "added.yaml",
        """
run:
  output_goal: Goal.
context_snapshot:
  excludes:
    defaults: true
    patterns:
      - "generated/"
      - "schemas/"
""",
    )
    reordered = digest_for(
        "reordered.yaml",
        """
run:
  output_goal: Goal.
context_snapshot:
  excludes:
    defaults: true
    patterns:
      - "schemas/"
      - "generated/"
""",
    )
    assert base != disabled
    assert base != added
    assert added != reordered
