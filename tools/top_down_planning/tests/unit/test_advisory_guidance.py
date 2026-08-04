"""Unit tests for agent_context guidance overlays (advisory role guidance)."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.config import (
    ALLOWED_OVERRIDE_PATHS,
    DEFAULT_CONFIG,
    ConfigError,
    GuidanceEntry,
    UnauthorizedContextMutationError,
    build_agent_context_manifest_payload,
    build_context_snapshot_payload,
    build_context_spec_payload,
    build_initial_context_snapshot_binding,
    compute_context_snapshot_digest_from_config,
    compute_context_spec_digest_from_config,
    diff_snapshot_binding_paths,
    resolve_config,
    resolve_effective_activity_context,
    validate_production_snapshot_rebase,
)
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs, write_config


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


def test_defaults_include_empty_guidance_and_override_paths() -> None:
    assert DEFAULT_CONFIG["agent_context"]["default"]["guidance"] == []
    assert "agent_context.default.guidance" in ALLOWED_OVERRIDE_PATHS
    for role in ("planner", "producer", "reviewer"):
        assert DEFAULT_CONFIG["agent_context"]["roles"][role]["guidance"] == []
        assert f"agent_context.roles.{role}.guidance" in ALLOWED_OVERRIDE_PATHS


def test_guidance_rejects_both_text_and_file(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    config = resolve_config(
        write_config(
            tmp_path / "both.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  roles:
    producer:
      guidance:
        - text: hello
          file: guidance.md
""",
        ),
        cwd=workspace,
    )
    with pytest.raises(ConfigError, match="exactly one of text or file"):
        resolve_effective_activity_context(config, "producer", "production", workspace=workspace)


def test_guidance_rejects_neither_text_nor_file(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    config = resolve_config(
        write_config(
            tmp_path / "neither.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  roles:
    producer:
      guidance:
        - {}
""",
        ),
        cwd=workspace,
    )
    with pytest.raises(ConfigError, match="exactly one of text or file"):
        resolve_effective_activity_context(config, "producer", "production", workspace=workspace)


def test_guidance_rejects_extra_keys(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    config = resolve_config(
        write_config(
            tmp_path / "extra-keys.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  roles:
    producer:
      guidance:
        - text: hello
          id: extra
""",
        ),
        cwd=workspace,
    )
    with pytest.raises(ConfigError, match="unsupported properties: id"):
        resolve_effective_activity_context(config, "producer", "production", workspace=workspace)


def test_guidance_rejects_empty_text(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    config = resolve_config(
        write_config(
            tmp_path / "empty-text.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  roles:
    producer:
      guidance:
        - text: "   "
""",
        ),
        cwd=workspace,
    )
    with pytest.raises(ConfigError, match=r"\.text must not be empty"):
        resolve_effective_activity_context(config, "producer", "production", workspace=workspace)


def test_guidance_rejects_missing_file(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    config = resolve_config(
        write_config(
            tmp_path / "missing-file.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  roles:
    producer:
      guidance:
        - file: missing-guidance.md
""",
        ),
        cwd=workspace,
    )
    with pytest.raises(ConfigError, match=r"\.file does not exist"):
        resolve_effective_activity_context(config, "producer", "production", workspace=workspace)


def test_guidance_rejects_whitespace_only_file(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    guidance_file = workspace / "blank.md"
    guidance_file.write_text("   \n\t  \n", encoding="utf-8")
    config = resolve_config(
        write_config(
            tmp_path / "blank-file.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  roles:
    producer:
      guidance:
        - file: blank.md
""",
        ),
        cwd=workspace,
    )
    with pytest.raises(ConfigError, match=r"\.file must not be empty after trimming"):
        resolve_effective_activity_context(config, "producer", "production", workspace=workspace)


def test_guidance_rejects_non_utf8_file(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    guidance_file = workspace / "binary.md"
    guidance_file.write_bytes(b"\xff\xfe")
    config = resolve_config(
        write_config(
            tmp_path / "binary-file.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  roles:
    producer:
      guidance:
        - file: binary.md
""",
        ),
        cwd=workspace,
    )
    with pytest.raises(ConfigError, match=r"must be UTF-8 text"):
        resolve_effective_activity_context(config, "producer", "production", workspace=workspace)


def test_guidance_additive_default_then_role_order(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    guidance_file = workspace / "role-guidance.md"
    guidance_file.write_text("Role file guidance.\n", encoding="utf-8")
    config = resolve_config(
        write_config(
            tmp_path / "order.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  default:
    guidance:
      - text: Default first.
  roles:
    producer:
      guidance:
        - file: role-guidance.md
        - text: Role inline last.
""",
        ),
        cwd=workspace,
    )
    context = resolve_effective_activity_context(config, "producer", "production", workspace=workspace)
    assert context.guidance == (
        "Default first.",
        "Role file guidance.",
        "Role inline last.",
    )
    planner = resolve_effective_activity_context(config, "planner", "initial_plan", workspace=workspace)
    assert planner.guidance == ("Default first.",)


def test_manifest_includes_resolved_guidance_strings(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    config = resolve_config(
        write_config(
            tmp_path / "manifest.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  roles:
    producer:
      guidance:
        - text: Be coherent.
""",
        ),
        cwd=workspace,
    )
    context = resolve_effective_activity_context(config, "producer", "production", workspace=workspace)
    payload = build_agent_context_manifest_payload(context)
    assert payload["agent_context"]["guidance"] == ["Be coherent."]
    assert payload["agent_context"]["role"] == "producer"

    empty = resolve_effective_activity_context(config, "planner", "initial_plan", workspace=workspace)
    empty_payload = build_agent_context_manifest_payload(empty)
    assert empty_payload["agent_context"]["guidance"] == []


def test_guidance_in_context_spec_and_snapshot_digests(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    guidance_file = workspace / "wf.md"
    guidance_file.write_text("file guidance v1", encoding="utf-8")
    config = resolve_config(
        write_config(
            tmp_path / "digests.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  roles:
    producer:
      guidance:
        - text: inline v1
        - file: wf.md
""",
        ),
        cwd=workspace,
    )
    spec = build_context_spec_payload(config, workspace=workspace)
    assert spec["roles"]["producer"]["guidance"] == [
        {"text": "inline v1"},
        {"file": str(guidance_file.resolve())},
    ]
    snapshot = build_context_snapshot_payload(config, workspace=workspace)
    assert any(entry.get("text") == "inline v1" for entry in snapshot["guidance_digests"])
    assert any(
        entry.get("path") == "wf.md"
        for entry in snapshot["guidance_digests"]
    )

    before_spec = compute_context_spec_digest_from_config(config, workspace=workspace)
    before_snap = compute_context_snapshot_digest_from_config(config, workspace=workspace)

    guidance_file.write_text("file guidance v2", encoding="utf-8")
    after_snap = compute_context_snapshot_digest_from_config(config, workspace=workspace)
    assert before_snap != after_snap

    config_changed = resolve_config(
        write_config(
            tmp_path / "digests-changed.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  roles:
    producer:
      guidance:
        - text: inline v2
        - file: wf.md
""",
        ),
        cwd=workspace,
    )
    after_spec = compute_context_spec_digest_from_config(
        config_changed, workspace=workspace
    )
    assert before_spec != after_spec


def test_set_override_accepts_producer_guidance(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    guidance_file = workspace / "producer-guidance.md"
    guidance_file.write_text("From file.", encoding="utf-8")
    config = resolve_config(
        write_config(
            tmp_path / "base.yaml",
            """
run:
  output_goal: Goal.
""",
        ),
        overrides=[
            "agent_context.roles.producer.guidance="
            '[{"file": "producer-guidance.md"}, {"text": "Inline preference."}]',
        ],
        cwd=workspace,
    )
    context = resolve_effective_activity_context(config, "producer", "production", workspace=workspace)
    assert context.guidance == ("From file.", "Inline preference.")


def test_empty_guidance_always_present_in_spec_and_snapshot(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    config = resolve_config(
        write_config(
            tmp_path / "no-guidance.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  default:
    resources:
      - README.md
""",
        ),
        cwd=workspace,
    )
    (workspace / "README.md").write_text("readme", encoding="utf-8")
    spec = build_context_spec_payload(config, workspace=workspace)
    for role_payload in spec["roles"].values():
        assert role_payload["guidance"] == []

    snapshot = build_context_snapshot_payload(config, workspace=workspace)
    assert snapshot["guidance_digests"] == []


@pytest.mark.parametrize(
    ("file_setup", "match"),
    [
        ("missing", r"\.file does not exist"),
        ("whitespace", r"\.file must not be empty after trimming"),
        ("non_utf8", r"must be UTF-8 text"),
    ],
)
def test_initial_binding_rejects_invalid_guidance_files(
    tmp_path: Path,
    file_setup: str,
    match: str,
) -> None:
    from top_down_planning.config import build_initial_context_snapshot_binding

    workspace = _workspace(tmp_path)
    if file_setup == "missing":
        file_ref = "missing-guidance.md"
    else:
        guidance_file = workspace / "bad.md"
        if file_setup == "whitespace":
            guidance_file.write_text("   \n", encoding="utf-8")
        else:
            guidance_file.write_bytes(b"\xff\xfe")
        file_ref = "bad.md"

    config = resolve_config(
        write_config(
            tmp_path / f"invalid-{file_setup}.yaml",
            f"""
run:
  output_goal: Goal.
agent_context:
  roles:
    producer:
      guidance:
        - file: {file_ref}
""",
        ),
        cwd=workspace,
    )
    with pytest.raises(ConfigError, match=match):
        build_initial_context_snapshot_binding(config, workspace=workspace)


def test_context_spec_digest_stable_when_guidance_file_deleted(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    guidance_file = workspace / "wf.md"
    guidance_file.write_text("file guidance", encoding="utf-8")
    config = resolve_config(
        write_config(
            tmp_path / "spec-stable.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  roles:
    producer:
      guidance:
        - file: wf.md
""",
        ),
        cwd=workspace,
    )
    before = compute_context_spec_digest_from_config(config, workspace=workspace)
    guidance_file.unlink()
    after = compute_context_spec_digest_from_config(config, workspace=workspace)
    assert before == after


def test_recompute_binding_tolerates_corrupt_guidance_files(tmp_path: Path) -> None:
    from top_down_planning.config import recompute_context_snapshot_binding

    workspace = _workspace(tmp_path)
    guidance_file = workspace / "wf.md"
    guidance_file.write_text("guidance-a", encoding="utf-8")
    config = resolve_config(
        write_config(
            tmp_path / "recompute-corrupt.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  roles:
    producer:
      guidance:
        - file: wf.md
""",
        ),
        cwd=workspace,
    )
    build_initial_context_snapshot_binding(config, workspace=workspace)
    guidance_file.write_bytes(b"\xff\xfe")

    binding, digest = recompute_context_snapshot_binding(config, workspace=workspace)
    assert digest
    corrupt = next(
        entry for entry in binding["guidance_digests"] if entry.get("path") == "wf.md"
    )
    assert corrupt["text"] == ""
    assert corrupt["digest"]


def test_folded_scalar_guidance_loads_from_config(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    config = resolve_config(
        write_config(
            tmp_path / "folded.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  roles:
    producer:
      guidance:
        - text: >
            Work in coherent batches. Skip a commit when that is better judgment.
""",
        ),
        cwd=workspace,
    )
    context = resolve_effective_activity_context(config, "producer", "production", workspace=workspace)
    assert context.guidance == (
        "Work in coherent batches. Skip a commit when that is better judgment.",
    )


def test_production_rebase_reports_inline_guidance_drift_clearly(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    old_binding = {
        "resource_digests": {},
        "skill_digests": {},
        "guidance_digests": [
            {"text": "alpha", "digest": "a" * 64},
        ],
    }
    new_binding = {
        "resource_digests": {},
        "skill_digests": {},
        "guidance_digests": [
            {"text": "beta", "digest": "b" * 64},
        ],
    }
    changed = diff_snapshot_binding_paths(old_binding, new_binding)
    assert any(path.startswith("guidance:inline:") for path in changed)

    with pytest.raises(UnauthorizedContextMutationError, match="inline guidance"):
        validate_production_snapshot_rebase(
            old_binding,
            new_binding,
            {},
            workspace=workspace,
        )


def test_guidance_entry_exported_from_config_package() -> None:
    assert GuidanceEntry is not None
