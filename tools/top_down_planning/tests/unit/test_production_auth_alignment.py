"""Production evidence refs, auth alignment, and §11 cache-incident fix."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.agent_tool.artifacts import capture_output_artifact
from top_down_planning.agent_tool.errors import RequestError
from top_down_planning.config import (
    InvalidProductionEvidenceError,
    UnauthorizedContextMutationError,
    authorized_production_workspace_paths,
    build_context_snapshot_payload,
    canonicalize_evidence_ref,
    compute_context_snapshot_digest_from_payload,
    diff_snapshot_binding_paths,
    recompute_context_snapshot_binding,
    resolve_config,
    validate_production_snapshot_rebase,
    validate_run_production_snapshot_drift,
)
from top_down_planning.config.snapshot_policy import CanonicalPathError
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs, minimal_resolved_config, write_config


def test_canonicalize_evidence_ref_valid_relative(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    target = workspace / "src" / "a.py"
    target.parent.mkdir(parents=True)
    target.write_text("ok\n", encoding="utf-8")
    assert canonicalize_evidence_ref("src/./a.py", workspace=workspace) == "src/a.py"


def test_canonicalize_evidence_ref_rejects_dotdot(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    with pytest.raises(CanonicalPathError, match=r"\.\."):
        canonicalize_evidence_ref("../outside.py", workspace=workspace)


def test_canonicalize_evidence_ref_rejects_absolute(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    absolute = str((workspace / "a.py").resolve())
    with pytest.raises(CanonicalPathError, match="absolute"):
        canonicalize_evidence_ref(absolute, workspace=workspace)


def test_canonicalize_evidence_ref_rejects_symlink_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "secret.py"
    outside.write_text("x\n", encoding="utf-8")
    (workspace / "link.py").symlink_to(outside)
    with pytest.raises(CanonicalPathError, match="escapes"):
        canonicalize_evidence_ref("link.py", workspace=workspace)


def test_aliasing_evidence_refs_share_canonical_key(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    real = workspace / "real" / "file.py"
    real.parent.mkdir(parents=True)
    real.write_text("ok\n", encoding="utf-8")
    (workspace / "alias.py").symlink_to(real)
    a = canonicalize_evidence_ref("alias.py", workspace=workspace)
    b = canonicalize_evidence_ref("real/file.py", workspace=workspace)
    assert a == b == "real/file.py"


def test_capture_output_artifact_stores_canonical_ref(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    workspace = tmp_path / "ws"
    target = workspace / "src" / "out.py"
    target.parent.mkdir(parents=True)
    target.write_text("v1\n", encoding="utf-8")
    config = minimal_resolved_config(run={"output_goal": "Goal."})
    store.create_run(
        "run-20260101T000601-000601",
        plan={
            "schema_version": 2,
            "id": "plan-ev",
            "revision": 0,
            "output_goal": "Goal.",
            "risks": [],
            "items": [],
        },
        **create_run_kwargs(workspace, resolved_config=config),
    )
    captured = capture_output_artifact(
        store,
        "run-20260101T000601-000601",
        workspace=workspace,
        ref="src/./out.py",
    )
    assert captured["ref"] == "src/out.py"

    with pytest.raises(RequestError, match="absolute|relative"):
        capture_output_artifact(
            store,
            "run-20260101T000601-000601",
            workspace=workspace,
            ref=str(target.resolve()),
        )


def test_validate_run_production_snapshot_drift_returns_none_without_drift(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "ws"
    src = workspace / "src"
    src.mkdir(parents=True)
    module = src / "feature.py"
    module.write_text("v1\n", encoding="utf-8")
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
    run = {
        "context_snapshot_binding": binding,
        "digests": {"context_snapshot": compute_context_snapshot_digest_from_payload(binding)},
    }
    production = {"output_evidence": [], "batches": []}

    assert (
        validate_run_production_snapshot_drift(
            run,
            config,
            production,
            workspace=workspace,
        )
        is None
    )


def test_validate_run_production_snapshot_drift_authorizes_evidence(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    src = workspace / "src"
    src.mkdir(parents=True)
    module = src / "feature.py"
    module.write_text("v1\n", encoding="utf-8")
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
    old_binding = build_context_snapshot_payload(config, workspace=workspace)
    module.write_text("v2\n", encoding="utf-8")
    run = {
        "context_snapshot_binding": old_binding,
        "digests": {
            "context_snapshot": compute_context_snapshot_digest_from_payload(old_binding)
        },
    }
    production = {
        "output_evidence": [{"id": "o1", "ref": "src/feature.py"}],
        "batches": [],
    }

    changed = validate_run_production_snapshot_drift(
        run,
        config,
        production,
        workspace=workspace,
    )
    assert changed == ["src/feature.py"]


def test_cache_noise_does_not_block_authorized_rebase(tmp_path: Path) -> None:
    """§11: caches under default excludes must not appear in changed_paths."""

    workspace = tmp_path / "ws"
    src = workspace / "src"
    src.mkdir(parents=True)
    module = src / "feature.py"
    module.write_text("v1\n", encoding="utf-8")
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
  reviewer:
    resources:
      - src/
""",
        ),
        cwd=workspace,
    )
    old_binding = build_context_snapshot_payload(config, workspace=workspace)
    assert "src/feature.py" in old_binding["resource_digests"]
    assert not any("__pycache__" in path for path in old_binding["resource_digests"])

    module.write_text("v2\n", encoding="utf-8")
    cache = src / "__pycache__"
    cache.mkdir()
    (cache / "feature.cpython-314.pyc").write_bytes(b"\0\1")
    (src / ".pytest_cache" / "v").mkdir(parents=True)
    (src / ".pytest_cache" / "v" / "cache").write_text("x\n", encoding="utf-8")

    new_binding, _digest = recompute_context_snapshot_binding(config, workspace=workspace)
    changed = diff_snapshot_binding_paths(old_binding, new_binding)
    assert changed == ["src/feature.py"]
    assert not any("__pycache__" in path or ".pytest_cache" in path for path in changed)

    production = {
        "output_evidence": [{"id": "o1", "ref": "src/feature.py"}],
        "batches": [],
    }
    assert validate_production_snapshot_rebase(
        old_binding,
        new_binding,
        production,
        workspace=workspace,
    ) == ["src/feature.py"]


def test_unauthorized_source_edit_blocked_with_relative_path(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    src = workspace / "src"
    src.mkdir(parents=True)
    module = src / "feature.py"
    module.write_text("v1\n", encoding="utf-8")
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
    old_binding = build_context_snapshot_payload(config, workspace=workspace)
    module.write_text("v2-unauthorized\n", encoding="utf-8")
    new_binding, _ = recompute_context_snapshot_binding(config, workspace=workspace)

    with pytest.raises(UnauthorizedContextMutationError, match="src/feature.py") as exc_info:
        validate_production_snapshot_rebase(
            old_binding,
            new_binding,
            {"output_evidence": [], "batches": []},
            workspace=workspace,
        )
    assert exc_info.value.unauthorized_paths == ("src/feature.py",)
    assert not any(path.startswith("/") for path in exc_info.value.unauthorized_paths)


def test_authorized_paths_alias_to_same_canonical_key(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    real = workspace / "real" / "file.py"
    real.parent.mkdir(parents=True)
    real.write_text("ok\n", encoding="utf-8")
    (workspace / "alias.py").symlink_to(real)
    production = {
        "output_evidence": [
            {"ref": "alias.py"},
            {"ref": "real/file.py"},
        ],
        "batches": [],
    }
    authorized = authorized_production_workspace_paths(production, workspace=workspace)
    assert authorized == {"real/file.py"}


def test_invalid_production_evidence_refs_fail_rebase_validation(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    src = workspace / "src"
    src.mkdir(parents=True)
    module = src / "feature.py"
    module.write_text("v1\n", encoding="utf-8")
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
    old_binding = build_context_snapshot_payload(config, workspace=workspace)
    module.write_text("v2\n", encoding="utf-8")
    new_binding, _ = recompute_context_snapshot_binding(config, workspace=workspace)
    production = {
        "output_evidence": [{"ref": "../outside.py"}],
        "batches": [],
    }
    with pytest.raises(InvalidProductionEvidenceError, match="invalid evidence refs"):
        validate_production_snapshot_rebase(
            old_binding,
            new_binding,
            production,
            workspace=workspace,
        )
