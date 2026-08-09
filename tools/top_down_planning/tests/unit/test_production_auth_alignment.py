"""Production evidence refs, auth alignment, and §11 cache-incident fix."""

from __future__ import annotations

from pathlib import Path

import pytest

from core_tools.persistence.digests import digest_file
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


def _evidence_for_path(workspace: Path, ref: str, *, evidence_id: str = "o1") -> dict[str, object]:
    target = workspace / ref
    return {
        "id": evidence_id,
        "ref": ref,
        "sha256": digest_file(target),
        "size": target.stat().st_size,
        "type": "artifact",
        "media_type": "text/plain",
        "captured_at": "2026-01-01T00:00:00Z",
        "snapshot_ref": f"artifacts/{evidence_id}/capture.bin",
    }


def _production_with_live_evidence(
    entries: list[dict[str, object]],
    *,
    batch_id: str = "batch-1",
    item_id: str = "item-work",
) -> dict[str, object]:
    """Production snapshot with evidence rows tied to a live completed batch."""

    live_entries: list[dict[str, object]] = []
    nested_outputs: list[dict[str, object]] = []
    for entry in entries:
        ev = dict(entry)
        ev.setdefault("batch_id", batch_id)
        ev.setdefault("type", "artifact")
        ev.setdefault("media_type", "text/plain")
        ev.setdefault("captured_at", "2026-01-01T00:00:00Z")
        ev.setdefault("snapshot_ref", f"artifacts/{ev.get('id')}/capture.bin")
        live_entries.append(ev)
        nested_outputs.append({key: value for key, value in ev.items() if key != "batch_id"})
    return {
        "batches": [
            {
                "id": batch_id,
                "status": "completed",
                "plan_items": [item_id],
                "result": {
                    "outputs": nested_outputs,
                    "contributions": [],
                    "dispositions": {
                        item_id: {"disposition": "completed", "evidence": "done"},
                    },
                },
            }
        ],
        "output_evidence": live_entries,
        "dispositions": {item_id: "completed"},
    }


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
  roles:
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
  roles:
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
    production = _production_with_live_evidence(
        [_evidence_for_path(workspace, "src/feature.py")]
    )

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
  roles:
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

    production = _production_with_live_evidence(
        [_evidence_for_path(workspace, "src/feature.py")]
    )
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
  roles:
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
    production = _production_with_live_evidence(
        [
            _evidence_for_path(workspace, "alias.py", evidence_id="a1"),
            _evidence_for_path(workspace, "real/file.py", evidence_id="a2"),
        ]
    )
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
  roles:
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


def test_production_completion_blocks_post_capture_file_mutation(tmp_path: Path) -> None:
    """Paths captured at X cannot authorize workspace bytes Y at completion."""

    workspace = tmp_path / "ws"
    src = workspace / "src"
    src.mkdir(parents=True)
    module = src / "feature.py"
    module.write_text("v1\n", encoding="utf-8")
    evidence = _evidence_for_path(workspace, "src/feature.py")
    config = resolve_config(
        write_config(
            tmp_path / "cfg.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  roles:
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
    production = _production_with_live_evidence([evidence])

    with pytest.raises(UnauthorizedContextMutationError, match="src/feature.py"):
        validate_production_snapshot_rebase(
            old_binding,
            new_binding,
            production,
            workspace=workspace,
        )


def test_latest_evidence_per_path_authorizes_final_bytes(tmp_path: Path) -> None:
    """Iterative production keeps audit history but only latest hash authorizes."""

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
  roles:
    producer:
      resources:
        - src/
""",
        ),
        cwd=workspace,
    )
    old_binding = build_context_snapshot_payload(config, workspace=workspace)
    first = _evidence_for_path(workspace, "src/feature.py", evidence_id="o1")
    module.write_text("v2\n", encoding="utf-8")
    second = _evidence_for_path(workspace, "src/feature.py", evidence_id="o2")
    new_binding, _ = recompute_context_snapshot_binding(config, workspace=workspace)
    production = _production_with_live_evidence([first, second])

    assert validate_production_snapshot_rebase(
        old_binding,
        new_binding,
        production,
        workspace=workspace,
    ) == ["src/feature.py"]


def test_stale_invalidated_evidence_does_not_authorize_rebase(tmp_path: Path) -> None:
    """Orphan output_evidence from invalidated batches must not authorize drift."""

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
  roles:
    producer:
      resources:
        - src/
""",
        ),
        cwd=workspace,
    )
    old_binding = build_context_snapshot_payload(config, workspace=workspace)
    module.write_text("v2-stale\n", encoding="utf-8")
    new_binding, _ = recompute_context_snapshot_binding(config, workspace=workspace)
    stale_sha = digest_file(workspace / "src" / "feature.py")
    module.write_text("v1\n", encoding="utf-8")
    production = {
        "batches": [
            {
                "id": "batch-1",
                "evidence_status": "invalidated_by_reconciliation",
                "result": {"outputs": [{"ref": "src/feature.py"}]},
            }
        ],
        "output_evidence": [
            {
                "id": "stale",
                "ref": "src/feature.py",
                "sha256": stale_sha,
                "batch_id": "batch-1",
            }
        ],
    }
    with pytest.raises(UnauthorizedContextMutationError, match="src/feature.py"):
        validate_production_snapshot_rebase(
            old_binding,
            new_binding,
            production,
            workspace=workspace,
        )


def test_delete_after_capture_does_not_authorize_snapshot_rebase(tmp_path: Path) -> None:
    """Deleting a captured file removes hash authorization for that path."""

    workspace = tmp_path / "ws"
    src = workspace / "src"
    src.mkdir(parents=True)
    module = src / "feature.py"
    obsolete = src / "obsolete.py"
    module.write_text("v1\n", encoding="utf-8")
    obsolete.write_text("gone\n", encoding="utf-8")
    config = resolve_config(
        write_config(
            tmp_path / "cfg.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  roles:
    producer:
      resources:
        - src/
""",
        ),
        cwd=workspace,
    )
    old_binding = build_context_snapshot_payload(config, workspace=workspace)
    production = _production_with_live_evidence(
        [
            _evidence_for_path(workspace, "src/feature.py", evidence_id="o1"),
            _evidence_for_path(workspace, "src/obsolete.py", evidence_id="o2"),
        ]
    )
    obsolete.unlink()
    new_binding, _ = recompute_context_snapshot_binding(config, workspace=workspace)
    with pytest.raises(UnauthorizedContextMutationError, match="obsolete.py"):
        validate_production_snapshot_rebase(
            old_binding,
            new_binding,
            production,
            workspace=workspace,
        )
