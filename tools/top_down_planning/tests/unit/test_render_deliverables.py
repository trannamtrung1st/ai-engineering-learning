import pytest
from pathlib import Path

from top_down_planning.render_deliverables import (
    ArtifactIgnoreMatcher,
    build_artifact_ignore_matcher,
    canonical_state_prefix,
    is_utf8_text_file,
    collect_deliverable_output,
    compute_deliverable_digest,
    diff_workspace_snapshots,
    filter_deliverable_candidates,
    snapshot_workspace_files,
)

DEFAULT_IGNORE_PATTERNS = [
    "**/__pycache__/",
    "**/.pytest_cache/",
    "*.pyc",
    "**/.DS_Store",
    "**/build/",
]


def _matcher(
    workspace: Path,
    output_dir: Path,
    patterns: list[str] | None = None,
) -> ArtifactIgnoreMatcher:
    return build_artifact_ignore_matcher(
        workspace,
        output_dir,
        patterns if patterns is not None else DEFAULT_IGNORE_PATTERNS,
    )


def test_collect_deliverable_output_and_digest(tmp_path: Path) -> None:
    artifact = tmp_path / "implementation-plan.md"
    artifact.write_text("# Plan\n", encoding="utf-8")
    matcher = _matcher(tmp_path, tmp_path / "out")
    deliverable = collect_deliverable_output(
        tmp_path,
        ["implementation-plan.md"],
        matcher,
    )
    assert deliverable.files["implementation-plan.md"] == "# Plan\n"
    assert deliverable.digest == compute_deliverable_digest(deliverable.files)


def test_snapshot_and_diff_workspace_files(tmp_path: Path) -> None:
    matcher = _matcher(tmp_path, tmp_path / "out")
    before = snapshot_workspace_files(tmp_path, matcher)
    (tmp_path / "implementation-plan.md").write_text("v1", encoding="utf-8")
    after = snapshot_workspace_files(tmp_path, matcher)
    assert diff_workspace_snapshots(before, after) == ["implementation-plan.md"]


def test_artifact_ignore_patterns_filter_configured_paths(tmp_path: Path) -> None:
    matcher = _matcher(tmp_path, tmp_path / "out")
    assert matcher.is_ignored("tests/toolkit/__pycache__/test_runtime_scaffold.cpython-314.pyc")
    assert matcher.is_ignored("temp/.DS_Store")
    assert matcher.is_ignored("independent-agent/build/lib/foo.py")
    assert not matcher.is_ignored("temp/todos/manifest.yaml")


def test_snapshot_ignores_pycache_changes(tmp_path: Path) -> None:
    matcher = _matcher(tmp_path, tmp_path / "out")
    before = snapshot_workspace_files(tmp_path, matcher)
    cache_dir = tmp_path / "tests" / "toolkit" / "__pycache__"
    cache_dir.mkdir(parents=True)
    (cache_dir / "test_runtime_scaffold.cpython-314.pyc").write_bytes(
        b"\x2b\x0e\r\n\x00\x00\x00\x00\xc1\xdb\x68\x6a"
    )
    after = snapshot_workspace_files(tmp_path, matcher)
    assert diff_workspace_snapshots(before, after) == []


def test_collect_deliverable_output_rejects_ignored_paths(tmp_path: Path) -> None:
    matcher = _matcher(tmp_path, tmp_path / "out")
    text = tmp_path / "temp/todos/manifest.yaml"
    text.parent.mkdir(parents=True)
    text.write_text("id: example\n", encoding="utf-8")
    binary = tmp_path / "tests/toolkit/__pycache__/test_runtime_scaffold.cpython-314.pyc"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"\x2b\x0e\r\n\x00\x00\x00\x00\xc1\xdb\x68\x6a")

    with pytest.raises(ValueError, match="ignored workspace path"):
        collect_deliverable_output(
            tmp_path,
            [
                "temp/todos/manifest.yaml",
                "tests/toolkit/__pycache__/test_runtime_scaffold.cpython-314.pyc",
            ],
            matcher,
        )


def test_collect_deliverable_output_requires_utf8_text(tmp_path: Path) -> None:
    matcher = _matcher(tmp_path, tmp_path / "out")
    binary = tmp_path / "temp/todos/binary-deliverable.yaml"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"\xc1\xdb\x68\x6a")

    with pytest.raises(UnicodeDecodeError):
        collect_deliverable_output(tmp_path, ["temp/todos/binary-deliverable.yaml"], matcher)


def test_filter_deliverable_candidates_preserves_real_paths(tmp_path: Path) -> None:
    matcher = _matcher(tmp_path, tmp_path / "out")
    paths = [
        "temp/todos/01-freeze.yaml",
        "tests/toolkit/__pycache__/module.cpython-314.pyc",
        "temp/tools/planning-summary.md",
    ]
    assert filter_deliverable_candidates(paths, matcher) == [
        "temp/todos/01-freeze.yaml",
        "temp/tools/planning-summary.md",
    ]


def test_empty_patterns_only_exclude_canonical_state(tmp_path: Path) -> None:
    workspace = tmp_path
    output_dir = workspace / "planning-output"
    output_dir.mkdir()
    matcher = build_artifact_ignore_matcher(workspace, output_dir, [])
    state_root = output_dir / ".planning-output"
    plan_yaml = state_root / "plan.yaml"
    plan_yaml.parent.mkdir(parents=True)
    plan_yaml.write_text("plan: []\n", encoding="utf-8")
    deliverable = workspace / "plan.md"
    deliverable.write_text("# Plan\n", encoding="utf-8")
    cache_dir = workspace / "__pycache__"
    cache_dir.mkdir()
    (cache_dir / "module.cpython-314.pyc").write_bytes(b"\x00")

    assert matcher.is_ignored("planning-output/.planning-output/plan.yaml")
    assert not matcher.is_ignored("plan.md")
    assert not matcher.is_ignored("__pycache__/module.cpython-314.pyc")

    snapshots = snapshot_workspace_files(workspace, matcher)
    assert "plan.md" in snapshots
    assert "__pycache__/module.cpython-314.pyc" in snapshots
    assert "planning-output/.planning-output/plan.yaml" not in snapshots


def test_negation_pattern_reincludes_ignored_path(tmp_path: Path) -> None:
    workspace = tmp_path
    output_dir = workspace / "out"
    output_dir.mkdir()
    matcher = build_artifact_ignore_matcher(
        workspace,
        output_dir,
        ["build/**", "!build/keep.md"],
    )
    assert matcher.is_ignored("build/lib/foo.py")
    assert not matcher.is_ignored("build/keep.md")


def test_dotfile_paths_are_not_ignored_by_default(tmp_path: Path) -> None:
    workspace = tmp_path
    output_dir = workspace / "out"
    output_dir.mkdir()
    matcher = build_artifact_ignore_matcher(workspace, output_dir, DEFAULT_IGNORE_PATTERNS)
    assert not matcher.is_ignored(".github/workflows/ci.yml")
    assert not matcher.is_ignored("src/.env.example")


def test_legacy_state_dirname_is_not_auto_excluded(tmp_path: Path) -> None:
    workspace = tmp_path
    output_dir = workspace / "planning-output"
    output_dir.mkdir()
    legacy_plan = output_dir / ".top-down-planning" / "plan.yaml"
    legacy_plan.parent.mkdir(parents=True)
    legacy_plan.write_text("plan: []\n", encoding="utf-8")
    matcher = build_artifact_ignore_matcher(workspace, output_dir, [])

    assert not matcher.is_ignored("planning-output/.top-down-planning/plan.yaml")
    snapshots = snapshot_workspace_files(workspace, matcher)
    assert "planning-output/.top-down-planning/plan.yaml" in snapshots


def test_is_utf8_text_file(tmp_path: Path) -> None:
    text = tmp_path / "plan.md"
    text.write_text("# Plan\n", encoding="utf-8")
    binary = tmp_path / "blob.bin"
    binary.write_bytes(b"\xc1\xdb")

    assert is_utf8_text_file(text)
    assert not is_utf8_text_file(binary)


def test_canonical_state_prefix_requires_output_inside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside_output = tmp_path / "outside-output"
    outside_output.mkdir()

    assert canonical_state_prefix(workspace, workspace / "planning-output") is not None
    assert canonical_state_prefix(workspace, outside_output) is None
