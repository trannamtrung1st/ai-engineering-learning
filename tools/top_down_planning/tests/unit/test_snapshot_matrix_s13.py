"""§13 snapshot test matrix: gap-fill coverage and coverage map.

Scenarios already covered elsewhere are listed in ``MATRIX_COVERAGE`` with the
owning module::test. New tests below fill remaining gaps. Temporary synthetic
fixtures only — no live repo caches or absolute developer paths.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core_tools.config.errors import ConfigError
from core_tools.persistence.digests import digest_file
from top_down_planning.config import (
    CanonicalPathCollisionError,
    CanonicalPathError,
    InvalidSnapshotBindingError,
    SNAPSHOT_POLICY_VERSION,
    UnauthorizedContextMutationError,
    build_context_snapshot_payload,
    canonicalize_evidence_ref,
    canonicalize_workspace_path,
    compute_context_spec_digest_from_config,
    diff_snapshot_binding_paths,
    recompute_context_snapshot_binding,
    resolve_config,
    validate_context_snapshot_binding,
    validate_production_snapshot_rebase,
)
from top_down_planning.config.context import MISSING_RESOURCE_FILE_DIGEST
from tests.helpers import write_config

# Scenario id -> owning test (this module or elsewhere). Canonical §13 matrix registry.
MATRIX_COVERAGE: dict[str, str] = {
    "1": "test_exclude_matching.py::test_builtin_matcher_semantics",
    "2": "test_exclude_matching.py::test_builtin_matcher_semantics",
    "3": "test_exclude_matching.py::test_builtin_matcher_semantics",
    "4": "test_exclude_matching.py::test_builtin_matcher_semantics",
    "5": "test_exclude_matching.py::test_builtin_matcher_semantics",
    "6": "test_exclude_matching.py::test_snapshot_policy_collect_excludes_discovered_caches",
    "7": "test_snapshot_matrix_s13.py::test_post_snapshot_cache_fixtures_do_not_drift",
    "8": "test_snapshot_matrix_s13.py::test_post_snapshot_cache_fixtures_do_not_drift",
    "9": "test_snapshot_matrix_s13.py::test_disabling_defaults_includes_bytecode",
    "10": "test_exclude_matching.py::test_star_and_double_star_and_root_anchor",
    "11": "test_exclude_matching.py::test_star_and_double_star_and_root_anchor",
    "12": "test_exclude_matching.py::test_star_and_double_star_and_root_anchor",
    "13": "test_exclude_matching.py::test_star_and_double_star_and_root_anchor",
    "14": "test_exclude_matching.py::test_star_and_double_star_and_root_anchor",
    "15": "test_exclude_matching.py::test_star_and_double_star_and_root_anchor",
    "16": "test_exclude_matching.py::test_later_patterns_and_negation_override",
    "17": "test_exclude_matching.py::test_later_patterns_and_negation_override",
    "18": "test_exclude_matching.py::test_user_negation_overrides_builtin",
    "19": "test_exclude_matching.py::test_effective_patterns_order_builtins_then_user",
    "20": "test_exclude_matching.py::test_empty_user_patterns_keep_defaults",
    "21": "test_snapshot_matrix_s13.py::test_invalid_exclude_pattern_errors",
    "22": "test_resource_kinds_and_identity.py::test_direct_file_overrides_exclusion",
    "23": "test_resource_kinds_and_identity.py::test_directory_expansion_applies_excludes",
    "23b": "test_resource_kinds_and_identity.py::test_glob_expansion_filters_matches_without_recursive_dirs",
    "24": "test_resource_kinds_and_identity.py::test_missing_direct_file_keeps_sentinel",
    "24b": "test_snapshot_matrix_s13.py::test_missing_direct_file_create_and_delete_drift",
    "24c": "test_snapshot_matrix_s13.py::test_missing_direct_file_create_and_delete_drift",
    "25": "test_snapshot_matrix_s13.py::test_duplicate_explicit_resources_single_key",
    "26": "test_snapshot_matrix_s13.py::test_canonical_collision_symlink_aliases_deduped_in_snapshot_build",
    "26b": "test_resource_kinds_and_identity.py::test_skills_not_filtered_by_excludes",
    "26c": "test_production_auth_alignment.py::test_cache_noise_does_not_block_authorized_rebase",
    "26d": "test_production_auth_alignment.py::test_canonicalize_evidence_ref_rejects_absolute",
    "26e": "test_production_auth_alignment.py::test_aliasing_evidence_refs_share_canonical_key",
    "27": "test_resource_kinds_and_identity.py::test_exclusion_policy_changes_context_spec_digest",
    "28": "test_resource_kinds_and_identity.py::test_exclusion_policy_changes_context_spec_digest",
    "29": "test_snapshot_matrix_s13.py::test_removing_pattern_changes_context_spec_digest",
    "30": "test_resource_kinds_and_identity.py::test_exclusion_policy_changes_context_spec_digest",
    "31": "test_snapshot_matrix_s13.py::test_policy_version_changes_context_spec_digest",
    "32": "test_compact_binding.py::test_compact_map_binding_shape",
    "33": "test_snapshot_policy.py::test_canonicalize_relative_posix",
    "34": "test_compact_binding.py::test_compact_map_binding_shape",
    "35": "test_snapshot_policy.py::test_canonicalize_strips_dot_segments",
    "36": "test_snapshot_policy.py::test_canonicalize_rejects_unresolved_dotdot",
    "37": "test_snapshot_matrix_s13.py::test_binding_order_independent_of_creation_order",
    "38": "test_snapshot_matrix_s13.py::test_binding_order_independent_of_creation_order",
    "39": "test_snapshot_matrix_s13.py::test_windows_style_evidence_refs_rejected",
    "39b": "test_snapshot_matrix_s13.py::test_windows_style_resource_paths_use_posix_binding_keys",
    "40": "test_snapshot_policy.py::test_detect_canonical_collisions_dedupes_symlink_aliases",
    "41": "test_snapshot_policy.py::test_canonicalize_rejects_workspace_escape",
    "42": "test_snapshot_policy.py::test_canonicalize_symlink_inside_workspace_uses_resolved_target",
    "43": "test_snapshot_matrix_s13.py::test_meaningful_edit_add_delete_create_drift",
    "44": "test_snapshot_matrix_s13.py::test_meaningful_edit_add_delete_create_drift",
    "45": "test_snapshot_matrix_s13.py::test_meaningful_edit_add_delete_create_drift",
    "46": "test_snapshot_matrix_s13.py::test_excluded_add_edit_delete_do_not_drift",
    "47": "test_snapshot_matrix_s13.py::test_excluded_add_edit_delete_do_not_drift",
    "48": "test_snapshot_matrix_s13.py::test_excluded_add_edit_delete_do_not_drift",
    "49": "test_production_auth_alignment.py::test_cache_noise_does_not_block_authorized_rebase",
    "50": "test_production_auth_alignment.py::test_unauthorized_source_edit_blocked_with_relative_path",
    "51": "test_production_completion_cache_regression.py::test_production_completion_succeeds_despite_cache_noise",
    "52": "test_production_completion_cache_regression.py::test_production_completion_succeeds_despite_cache_noise",
    "53": "test_snapshot_diagnostics.py::test_unauthorized_error_message_uses_relative_path_format",
    "54": "test_compact_binding.py::test_create_run_persists_and_reloads_compact_binding",
    "55": "test_compact_binding.py::test_validate_rejects_list_and_absolute_and_workspace_field",
    "56": "test_compact_binding.py::test_validate_rejects_list_and_absolute_and_workspace_field",
    "57": "test_run_schema_version.py::test_missing_schema_version_rejected_with_recreate_message",
    "58": "test_run_schema_version.py::test_unsupported_schema_version_rejected_with_recreate_message",
    "58b": "test_run_schema_version.py::test_schema_version_gate_runs_before_nested_field_errors",
    "59": "test_snapshot_matrix_s13.py::test_unknown_context_snapshot_fields_rejected",
    "60": "test_snapshot_matrix_s13.py::test_no_legacy_binding_conversion",
}

_EXPECTED_SCENARIOS = {
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
    "10",
    "11",
    "12",
    "13",
    "14",
    "15",
    "16",
    "17",
    "18",
    "19",
    "20",
    "21",
    "22",
    "23",
    "23b",
    "24",
    "24b",
    "24c",
    "25",
    "26",
    "26b",
    "26c",
    "26d",
    "26e",
    "27",
    "28",
    "29",
    "30",
    "31",
    "32",
    "33",
    "34",
    "35",
    "36",
    "37",
    "38",
    "39",
    "39b",
    "40",
    "41",
    "42",
    "43",
    "44",
    "45",
    "46",
    "47",
    "48",
    "49",
    "50",
    "51",
    "52",
    "53",
    "54",
    "55",
    "56",
    "57",
    "58",
    "58b",
    "59",
    "60",
}


def test_matrix_coverage_map_is_complete() -> None:
    assert set(MATRIX_COVERAGE) == _EXPECTED_SCENARIOS
    assert SNAPSHOT_POLICY_VERSION == "snapshot-excludes-v1"


def _dir_config(tmp_path: Path, workspace: Path, *, body: str) -> dict:
    return resolve_config(write_config(tmp_path / "cfg.yaml", body), cwd=workspace)


def test_post_snapshot_cache_fixtures_do_not_drift(tmp_path: Path) -> None:
    """§13 #7–#8: synthetic caches after initial snapshot create no drift."""

    workspace = tmp_path / "ws"
    nested = workspace / "pkg" / "sub"
    nested.mkdir(parents=True)
    (workspace / "pkg" / "mod.py").write_text("ok\n", encoding="utf-8")
    (nested / "leaf.py").write_text("leaf\n", encoding="utf-8")
    config = _dir_config(
        tmp_path,
        workspace,
        body="""
run:
  output_goal: Goal.
agent_context:
  roles:
    producer:
      resources:
        - pkg/
""",
    )
    old = build_context_snapshot_payload(config, workspace=workspace)
    assert "pkg/mod.py" in old["resource_digests"]
    assert "pkg/sub/leaf.py" in old["resource_digests"]

    for cache_root in (workspace / "pkg" / "__pycache__", nested / "__pycache__"):
        cache_root.mkdir(parents=True, exist_ok=True)
        (cache_root / "x.cpython-314.pyc").write_bytes(b"\0")
    (workspace / "pkg" / "noise.pyc").write_bytes(b"\0")
    (workspace / "pkg" / ".pytest_cache").mkdir()
    (workspace / "pkg" / ".pytest_cache" / "v").write_text("x\n", encoding="utf-8")
    (nested / ".mypy_cache").mkdir()
    (nested / ".mypy_cache" / "data.json").write_text("{}\n", encoding="utf-8")
    (workspace / "pkg" / ".ruff_cache").mkdir()
    (workspace / "pkg" / ".ruff_cache" / "0").write_text("x\n", encoding="utf-8")

    new, _ = recompute_context_snapshot_binding(config, workspace=workspace)
    assert diff_snapshot_binding_paths(old, new) == []
    assert new["resource_digests"] == old["resource_digests"]


def test_disabling_defaults_includes_bytecode(tmp_path: Path) -> None:
    """§13 #9."""

    workspace = tmp_path / "ws"
    pkg = workspace / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "mod.py").write_text("ok\n", encoding="utf-8")
    (pkg / "mod.pyc").write_bytes(b"\0")
    config = _dir_config(
        tmp_path,
        workspace,
        body="""
run:
  output_goal: Goal.
agent_context:
  roles:
    producer:
      resources:
        - pkg/
context_snapshot:
  excludes:
    defaults: false
    patterns: []
""",
    )
    binding = build_context_snapshot_payload(config, workspace=workspace)
    assert "pkg/mod.py" in binding["resource_digests"]
    assert "pkg/mod.pyc" in binding["resource_digests"]


def test_invalid_exclude_pattern_errors(tmp_path: Path) -> None:
    """§13 #21."""

    workspace = tmp_path / "ws"
    workspace.mkdir()
    with pytest.raises(ConfigError, match="invalid context_snapshot.excludes pattern"):
        resolve_config(
            write_config(
                tmp_path / "bad.yaml",
                """
run:
  output_goal: Goal.
context_snapshot:
  excludes:
    defaults: true
    patterns:
      - "!"
""",
            ),
            cwd=workspace,
        )


def test_missing_direct_file_create_and_delete_drift(tmp_path: Path) -> None:
    """§13 #24b–#24c."""

    workspace = tmp_path / "ws"
    workspace.mkdir()
    config = _dir_config(
        tmp_path,
        workspace,
        body="""
run:
  output_goal: Goal.
agent_context:
  roles:
    producer:
      resources:
        - missing.py
""",
    )
    old = build_context_snapshot_payload(config, workspace=workspace)
    assert old["resource_digests"]["missing.py"] == MISSING_RESOURCE_FILE_DIGEST

    target = workspace / "missing.py"
    target.write_text("now-present\n", encoding="utf-8")
    created, _ = recompute_context_snapshot_binding(config, workspace=workspace)
    assert diff_snapshot_binding_paths(old, created) == ["missing.py"]
    assert created["resource_digests"]["missing.py"] == digest_file(target)

    target.unlink()
    deleted, _ = recompute_context_snapshot_binding(config, workspace=workspace)
    assert diff_snapshot_binding_paths(created, deleted) == ["missing.py"]
    assert deleted["resource_digests"]["missing.py"] == MISSING_RESOURCE_FILE_DIGEST


def test_duplicate_explicit_resources_single_key(tmp_path: Path) -> None:
    """§13 #25."""

    workspace = tmp_path / "ws"
    target = workspace / "shared.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("shared\n", encoding="utf-8")
    config = _dir_config(
        tmp_path,
        workspace,
        body="""
run:
  output_goal: Goal.
agent_context:
  roles:
    producer:
      resources:
        - shared.py
        - shared.py
    reviewer:
      resources:
        - ./shared.py
""",
    )
    binding = build_context_snapshot_payload(config, workspace=workspace)
    assert list(binding["resource_digests"]) == ["shared.py"]


def test_canonical_collision_symlink_aliases_deduped_in_snapshot_build(tmp_path: Path) -> None:
    """§13 #26: symlink alias resource declarations dedupe to one binding key."""

    from top_down_planning.config import build_context_snapshot_payload, resolve_config
    from tests.helpers import write_config

    workspace = tmp_path / "ws"
    real = workspace / "real" / "file.py"
    real.parent.mkdir(parents=True)
    real.write_text("ok\n", encoding="utf-8")
    (workspace / "alias.py").symlink_to(real)
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
        - alias.py
        - real/file.py
""",
        ),
        cwd=workspace,
    )
    binding = build_context_snapshot_payload(config, workspace=workspace)
    assert list(binding["resource_digests"]) == ["real/file.py"]


def test_removing_pattern_changes_context_spec_digest(tmp_path: Path) -> None:
    """§13 #29."""

    workspace = tmp_path / "ws"
    workspace.mkdir()

    def digest(name: str, body: str) -> str:
        return compute_context_spec_digest_from_config(
            resolve_config(write_config(tmp_path / name, body), cwd=workspace),
            workspace=workspace,
        )

    with_pattern = digest(
        "with.yaml",
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
    without = digest(
        "without.yaml",
        """
run:
  output_goal: Goal.
context_snapshot:
  excludes:
    defaults: true
    patterns: []
""",
    )
    assert with_pattern != without


def test_policy_version_changes_context_spec_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§13 #31."""

    workspace = tmp_path / "ws"
    workspace.mkdir()
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
    before = compute_context_spec_digest_from_config(config, workspace=workspace)
    monkeypatch.setattr(
        "top_down_planning.config.snapshot_policy.SNAPSHOT_POLICY_VERSION",
        "snapshot-excludes-v-test",
    )
    after = compute_context_spec_digest_from_config(config, workspace=workspace)
    assert before != after


def test_binding_order_independent_of_creation_order(tmp_path: Path) -> None:
    """§13 #37–#38."""

    workspace = tmp_path / "ws"
    pkg = workspace / "pkg"
    pkg.mkdir(parents=True)
    # Create in reverse lexical order; binding keys must still sort ascending.
    (pkg / "z.py").write_text("z\n", encoding="utf-8")
    (pkg / "a.py").write_text("a\n", encoding="utf-8")
    (pkg / "m.py").write_text("m\n", encoding="utf-8")
    config = _dir_config(
        tmp_path,
        workspace,
        body="""
run:
  output_goal: Goal.
agent_context:
  roles:
    producer:
      resources:
        - pkg/
""",
    )
    first = build_context_snapshot_payload(config, workspace=workspace)
    second = build_context_snapshot_payload(config, workspace=workspace)
    assert list(first["resource_digests"]) == ["pkg/a.py", "pkg/m.py", "pkg/z.py"]
    assert first == second


def test_windows_style_evidence_refs_rejected(tmp_path: Path) -> None:
    """§13 #39: drive/backslash-style evidence refs rejected; POSIX keys use ``/``."""

    workspace = tmp_path / "ws"
    target = workspace / "src" / "a.py"
    target.parent.mkdir(parents=True)
    target.write_text("ok\n", encoding="utf-8")
    assert canonicalize_workspace_path("src/a.py", workspace=workspace) == "src/a.py"
    with pytest.raises(CanonicalPathError, match="absolute|relative"):
        canonicalize_evidence_ref(r"C:\src\a.py", workspace=workspace)
    with pytest.raises(CanonicalPathError, match="absolute|relative"):
        canonicalize_evidence_ref(r"\src\a.py", workspace=workspace)


def test_windows_style_resource_paths_use_posix_binding_keys(tmp_path: Path) -> None:
    """§13 #39: resource materialization emits POSIX binding keys without backslashes."""

    workspace = tmp_path / "ws"
    target = workspace / "src" / "a.py"
    target.parent.mkdir(parents=True)
    target.write_text("ok\n", encoding="utf-8")
    config = _dir_config(
        tmp_path,
        workspace,
        body="""
run:
  output_goal: Goal.
agent_context:
  roles:
    producer:
      resources:
        - src/a.py
""",
    )
    binding = build_context_snapshot_payload(config, workspace=workspace)
    keys = list(binding["resource_digests"])
    assert keys == ["src/a.py"]
    assert all("\\" not in key for key in keys)
    validate_context_snapshot_binding(binding)


def test_meaningful_edit_add_delete_create_drift(tmp_path: Path) -> None:
    """§13 #43–#45."""

    workspace = tmp_path / "ws"
    src = workspace / "src"
    src.mkdir(parents=True)
    feature = src / "feature.py"
    feature.write_text("v1\n", encoding="utf-8")
    config = _dir_config(
        tmp_path,
        workspace,
        body="""
run:
  output_goal: Goal.
agent_context:
  roles:
    producer:
      resources:
        - src/
""",
    )
    base = build_context_snapshot_payload(config, workspace=workspace)

    feature.write_text("v2\n", encoding="utf-8")
    edited, _ = recompute_context_snapshot_binding(config, workspace=workspace)
    assert diff_snapshot_binding_paths(base, edited) == ["src/feature.py"]

    (src / "extra.py").write_text("new\n", encoding="utf-8")
    added, _ = recompute_context_snapshot_binding(config, workspace=workspace)
    assert "src/extra.py" in diff_snapshot_binding_paths(edited, added)

    (src / "extra.py").unlink()
    deleted, _ = recompute_context_snapshot_binding(config, workspace=workspace)
    assert "src/extra.py" in diff_snapshot_binding_paths(added, deleted)


def test_excluded_add_edit_delete_do_not_drift(tmp_path: Path) -> None:
    """§13 #46–#48."""

    workspace = tmp_path / "ws"
    src = workspace / "src"
    src.mkdir(parents=True)
    (src / "feature.py").write_text("ok\n", encoding="utf-8")
    cache = src / "__pycache__"
    cache.mkdir()
    pyc = cache / "feature.cpython-314.pyc"
    pyc.write_bytes(b"\0v1")
    config = _dir_config(
        tmp_path,
        workspace,
        body="""
run:
  output_goal: Goal.
agent_context:
  roles:
    producer:
      resources:
        - src/
""",
    )
    # Seed binding while an excluded file already exists — then mutate only excludes.
    old = build_context_snapshot_payload(config, workspace=workspace)
    pyc.write_bytes(b"\0v2")
    (cache / "other.cpython-314.pyc").write_bytes(b"\0new")
    pyc.unlink()
    new, _ = recompute_context_snapshot_binding(config, workspace=workspace)
    assert diff_snapshot_binding_paths(old, new) == []


def test_unknown_context_snapshot_fields_rejected(tmp_path: Path) -> None:
    """§13 #59."""

    workspace = tmp_path / "ws"
    workspace.mkdir()
    with pytest.raises(ConfigError, match="unknown context_snapshot field"):
        resolve_config(
            write_config(
                tmp_path / "legacy.yaml",
                """
run:
  output_goal: Goal.
context_snapshot:
  ignore_globs:
    - "*.pyc"
""",
            ),
            cwd=workspace,
        )
    with pytest.raises(ConfigError, match="unknown context_snapshot.excludes field"):
        resolve_config(
            write_config(
                tmp_path / "legacy2.yaml",
                """
run:
  output_goal: Goal.
context_snapshot:
  excludes:
    defaults: true
    globs:
      - "*.pyc"
""",
            ),
            cwd=workspace,
        )


def test_no_legacy_binding_conversion() -> None:
    """§13 #60: legacy shapes fail validation; they are not rewritten."""

    legacy = {
        "workspace": "/tmp/ws",
        "resource_digests": [{"path": "/tmp/ws/a.py", "digest": "a" * 64}],
        "skill_digests": [],
    }
    with pytest.raises(InvalidSnapshotBindingError, match="Recreate|legacy|absolute"):
        validate_context_snapshot_binding(legacy)
    # Input object must remain untouched (no in-place conversion).
    assert legacy["resource_digests"][0]["path"].startswith("/")
    assert "workspace" in legacy


def test_unauthorized_paths_remain_relative_tuple(tmp_path: Path) -> None:
    """§13 #53 invariant on exception payload."""

    workspace = tmp_path / "ws"
    src = workspace / "src"
    src.mkdir(parents=True)
    module = src / "feature.py"
    module.write_text("v1\n", encoding="utf-8")
    config = _dir_config(
        tmp_path,
        workspace,
        body="""
run:
  output_goal: Goal.
agent_context:
  roles:
    producer:
      resources:
        - src/
""",
    )
    old = build_context_snapshot_payload(config, workspace=workspace)
    module.write_text("v2\n", encoding="utf-8")
    new, _ = recompute_context_snapshot_binding(config, workspace=workspace)
    with pytest.raises(UnauthorizedContextMutationError) as exc_info:
        validate_production_snapshot_rebase(
            old,
            new,
            {"output_evidence": [], "batches": []},
            workspace=workspace,
        )
    assert exc_info.value.unauthorized_paths == ("src/feature.py",)
