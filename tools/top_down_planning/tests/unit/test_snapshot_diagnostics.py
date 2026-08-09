"""Snapshot collection diagnostics (proposal §14)."""

from __future__ import annotations

from pathlib import Path

import pytest

from core_tools.persistence.digests import digest_file
from top_down_planning.config import (
    UnauthorizedContextMutationError,
    build_context_snapshot_payload_with_diagnostics,
    format_unauthorized_mutation_message,
    recompute_context_snapshot_binding,
    resolve_config,
    validate_production_snapshot_rebase,
)
from top_down_planning.config.snapshot_diagnostics import SnapshotDiagnostics
from tests.helpers import write_config


def test_diagnostics_counts_excluded_caches_without_second_pass(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    src = workspace / "src"
    src.mkdir(parents=True)
    (src / "feature.py").write_text("v1\n", encoding="utf-8")
    cache = src / "__pycache__"
    cache.mkdir()
    (cache / "feature.cpython-314.pyc").write_bytes(b"\0\1")
    (src / "orphan.pyc").write_bytes(b"\0\2")
    pytest_cache = src / ".pytest_cache"
    pytest_cache.mkdir()
    (pytest_cache / "v").write_text("x\n", encoding="utf-8")

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
    binding, diagnostics = build_context_snapshot_payload_with_diagnostics(
        config,
        workspace=workspace,
    )
    assert isinstance(diagnostics, SnapshotDiagnostics)
    assert binding["resource_digests"] == {"src/feature.py": binding["resource_digests"]["src/feature.py"]}
    assert diagnostics.included_files == 1
    assert diagnostics.excluded_files >= 2
    assert diagnostics.pruned_directories == 0
    assert diagnostics.policy_version == "snapshot-excludes-v1"
    assert diagnostics.binding_size_bytes > 0
    summary = diagnostics.format_summary()
    assert "Snapshot: 1 included files" in summary
    assert "Policy: snapshot-excludes-v1" in summary
    assert "Binding size:" in summary
    fields = diagnostics.to_event_fields()
    assert fields["included_files"] == 1
    assert "summary" in fields


def test_unauthorized_message_lists_relative_paths() -> None:
    message = format_unauthorized_mutation_message(
        ["src/a.py", "src/b.py"],
    )
    assert message.startswith("production completion cannot rebase context snapshot:")
    assert "- src/a.py" in message
    assert "- src/b.py" in message
    assert "/" + "Users" not in message


def test_unauthorized_error_message_uses_relative_path_format(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    src = workspace / "src"
    src.mkdir(parents=True)
    module = src / "feature.py"
    other = src / "other.py"
    module.write_text("v1\n", encoding="utf-8")
    other.write_text("keep\n", encoding="utf-8")
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
    old_binding, _ = build_context_snapshot_payload_with_diagnostics(
        config,
        workspace=workspace,
    )
    module.write_text("v2\n", encoding="utf-8")
    other.write_text("drift\n", encoding="utf-8")
    cache = src / "__pycache__"
    cache.mkdir()
    (cache / "feature.cpython-314.pyc").write_bytes(b"\0")
    new_binding, _ = recompute_context_snapshot_binding(config, workspace=workspace)

    with pytest.raises(UnauthorizedContextMutationError) as exc_info:
        validate_production_snapshot_rebase(
            old_binding,
            new_binding,
            {
                "batches": [
                    {
                        "id": "batch-1",
                        "status": "completed",
                        "plan_items": ["item-work"],
                        "result": {
                            "outputs": [
                                {
                                    "id": "o1",
                                    "ref": "src/feature.py",
                                    "sha256": digest_file(module),
                                    "batch_id": "batch-1",
                                    "snapshot_ref": "artifacts/test/capture.bin",
                                }
                            ],
                            "dispositions": {
                                "item-work": {
                                    "disposition": "completed",
                                    "evidence": "authorized",
                                }
                            },
                        },
                    }
                ],
                "output_evidence": [
                    {
                        "id": "o1",
                        "ref": "src/feature.py",
                        "sha256": digest_file(module),
                        "batch_id": "batch-1",
                        "snapshot_ref": "artifacts/test/capture.bin",
                    }
                ],
                "dispositions": {"item-work": "completed"},
            },
            workspace=workspace,
        )
    message = str(exc_info.value)
    assert "- src/other.py" in message
    assert "src/feature.py" not in message.split("unauthorized snapshot-bound changes detected:")[-1]
    assert "__pycache__" not in message
    assert ".pyc" not in message
