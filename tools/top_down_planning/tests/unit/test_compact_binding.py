"""Compact map snapshot binding schema (proposal §9)."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.config import (
    InvalidSnapshotBindingError,
    build_context_snapshot_payload,
    diff_snapshot_binding_paths,
    resolve_config,
    validate_context_snapshot_binding,
)
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs, write_config


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    return workspace


def test_compact_map_binding_shape(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "src").mkdir()
    (workspace / "src" / "a.py").write_text("a\n", encoding="utf-8")
    config = resolve_config(
        write_config(
            tmp_path / "cfg.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  producer:
    resources:
      - src/
""",
        ),
        cwd=workspace,
    )
    binding = build_context_snapshot_payload(config, workspace=workspace)
    assert "workspace" not in binding
    assert isinstance(binding["resource_digests"], dict)
    assert isinstance(binding["skill_digests"], dict)
    assert isinstance(binding["guidance_digests"], list)
    assert "src/a.py" in binding["resource_digests"]
    assert "/" not in binding["resource_digests"]["src/a.py"][:1]
    assert not str(next(iter(binding["resource_digests"]))).startswith("/")
    digest = binding["resource_digests"]["src/a.py"]
    assert len(digest) == 64 and digest.islower()


def test_validate_rejects_list_and_absolute_and_workspace_field() -> None:
    with pytest.raises(InvalidSnapshotBindingError, match="Recreate"):
        validate_context_snapshot_binding(
            {
                "workspace": "/tmp/ws",
                "resource_digests": {},
                "skill_digests": {},
                "guidance_digests": [],
            }
        )
    with pytest.raises(InvalidSnapshotBindingError, match="Recreate"):
        validate_context_snapshot_binding(
            {
                "resource_digests": [{"path": "a.py", "digest": "a" * 64}],
                "skill_digests": {},
                "guidance_digests": [],
            }
        )
    with pytest.raises(InvalidSnapshotBindingError, match="absolute"):
        validate_context_snapshot_binding(
            {
                "resource_digests": {"/abs/a.py": "a" * 64},
                "skill_digests": {},
                "guidance_digests": [],
            }
        )


def test_diff_uses_map_comparison() -> None:
    old_binding = {
        "resource_digests": {"src/a.py": "a" * 64},
        "skill_digests": {},
        "guidance_digests": [],
    }
    new_binding = {
        "resource_digests": {"src/a.py": "b" * 64, "src/b.py": "c" * 64},
        "skill_digests": {},
        "guidance_digests": [],
    }
    assert diff_snapshot_binding_paths(old_binding, new_binding) == [
        "src/a.py",
        "src/b.py",
    ]


def test_diff_rejects_legacy_list_shape_with_binding_error() -> None:
    legacy = {
        "resource_digests": [{"path": "a.py", "digest": "a" * 64}],
        "skill_digests": {},
        "guidance_digests": [],
    }
    compact = {
        "resource_digests": {},
        "skill_digests": {},
        "guidance_digests": [],
    }
    with pytest.raises(InvalidSnapshotBindingError, match="Recreate"):
        diff_snapshot_binding_paths(legacy, compact)


def test_create_run_persists_and_reloads_compact_binding(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "guide.md").write_text("g\n", encoding="utf-8")
    config = resolve_config(
        write_config(
            tmp_path / "cfg.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  default:
    resources:
      - guide.md
""",
        ),
        cwd=workspace,
    )
    store = FileRunStore(tmp_path / "runs")
    store.create_run(
        "run-20260101T000501-000501",
        plan={
            "schema_version": 1,
            "id": "plan-compact",
            "revision": 0,
            "output_goal": "Goal.",
            "items": [],
        },
        **create_run_kwargs(workspace, resolved_config=config),
    )
    loaded = store.load_run("run-20260101T000501-000501")
    binding = loaded["context_snapshot_binding"]
    assert isinstance(binding["resource_digests"], dict)
    assert "guide.md" in binding["resource_digests"]
    assert "workspace" not in binding


def test_save_run_validates_context_snapshot_binding(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    config = resolve_config(
        write_config(
            tmp_path / "cfg.yaml",
            """
run:
  output_goal: Goal.
""",
        ),
        cwd=workspace,
    )
    store = FileRunStore(tmp_path / "runs")
    store.create_run(
        "run-20260101T000502-000502",
        plan={
            "schema_version": 1,
            "id": "plan-save-run",
            "revision": 0,
            "output_goal": "Goal.",
            "items": [],
        },
        **create_run_kwargs(workspace, resolved_config=config),
    )
    run = store.load_run("run-20260101T000502-000502")
    expected = int(run["revision"])
    run["revision"] = expected + 1
    run["context_snapshot_binding"] = {
        "resource_digests": [{"path": "a.py", "digest": "a" * 64}],
        "skill_digests": {},
        "guidance_digests": [],
    }
    with pytest.raises(InvalidSnapshotBindingError, match="Recreate"):
        store.save_run("run-20260101T000502-000502", run, expected)
