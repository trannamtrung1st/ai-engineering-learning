"""Documentation quality checks: links, landing coverage, and known contracts."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_CHECK_DOCS = _PACKAGE_ROOT / "scripts" / "check_docs.py"


def _load_check_docs():
    spec = importlib.util.spec_from_file_location("tdp_check_docs", _CHECK_DOCS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_check_docs_script_exists() -> None:
    assert _CHECK_DOCS.is_file()


def test_markdown_tree_reports_broken_file_and_fragment(tmp_path: Path) -> None:
    check_docs = _load_check_docs()
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "README.md").write_text(
        "[missing](gone.md)\n[bad heading](page.md#no-such-heading)\n",
        encoding="utf-8",
    )
    (docs / "page.md").write_text("# Present\n", encoding="utf-8")

    errors = check_docs.check_markdown_links(docs)
    joined = "\n".join(errors)
    assert "gone.md" in joined
    assert "no-such-heading" in joined


def test_markdown_tree_accepts_relative_file_and_heading(tmp_path: Path) -> None:
    check_docs = _load_check_docs()
    docs = tmp_path / "docs"
    (docs / "concepts").mkdir(parents=True)
    (docs / "README.md").write_text(
        "[terms](concepts/lifecycle-terms.md#run-status)\n",
        encoding="utf-8",
    )
    (docs / "concepts" / "lifecycle-terms.md").write_text(
        "# Lifecycle terms\n\n## Run status\n",
        encoding="utf-8",
    )

    assert check_docs.check_markdown_links(docs) == []


def test_landing_coverage_requires_public_pages_not_authoring(tmp_path: Path) -> None:
    check_docs = _load_check_docs()
    docs = tmp_path / "docs"
    (docs / "authoring").mkdir(parents=True)
    (docs / "concepts").mkdir()
    (docs / "README.md").write_text(
        "[concepts](concepts/overview.md)\n[quality](QUALITY-CHECKS.md)\n",
        encoding="utf-8",
    )
    (docs / "concepts" / "overview.md").write_text("# Overview\n", encoding="utf-8")
    (docs / "QUALITY-CHECKS.md").write_text("# Quality\n", encoding="utf-8")
    (docs / "authoring" / "PAGE-OWNERSHIP.md").write_text("# Authoring\n", encoding="utf-8")
    (docs / "orphan.md").write_text("# Orphan\n", encoding="utf-8")

    errors = check_docs.check_landing_coverage(docs)
    joined = "\n".join(errors)
    assert "orphan.md" in joined
    assert "PAGE-OWNERSHIP.md" not in joined


def test_example_runs_dir_comment_rejects_undifferentiated_fallback() -> None:
    check_docs = _load_check_docs()
    errors = check_docs.check_example_runs_dir_comment(
        "# Precedence: --runs-dir > $TDP_RUNS_DIR > runtime.runs_dir > ./runs\n"
    )
    assert errors


def test_example_runs_dir_comment_accepts_two_command_classes() -> None:
    check_docs = _load_check_docs()
    comment = """
# Creating commands (run, prepare, execute):
#   --runs-dir > $TDP_RUNS_DIR > runtime.runs_dir (no ./runs fallback)
# Lookup/resume-style commands (resume, status, inspect, validate, doctor, sub-tdp attach):
#   --runs-dir > $TDP_RUNS_DIR > runtime.runs_dir > ./runs
"""
    assert check_docs.check_example_runs_dir_comment(comment) == []


def test_continuation_ok_docs_reject_completed_accepted_only(tmp_path: Path) -> None:
    check_docs = _load_check_docs()
    docs = tmp_path / "docs"
    (docs / "concepts").mkdir(parents=True)
    (docs / "workflows").mkdir()
    (docs / "concepts" / "lifecycle-terms.md").write_text(
        "Continuation/resume success is `true` only for `completed` + `accepted`.\n",
        encoding="utf-8",
    )
    (docs / "concepts" / "quality-loop.md").write_text("# Quality\n", encoding="utf-8")
    (docs / "workflows" / "lifecycle.md").write_text("# Lifecycle\n", encoding="utf-8")
    (docs / "workflows" / "operations.md").write_text("# Operations\n", encoding="utf-8")

    errors = check_docs.check_continuation_ok_docs(docs)
    assert errors


def _write_first_run_tree(tmp_path: Path, workspace: str) -> Path:
    package_root = tmp_path / "tools" / "top_down_planning"
    (package_root / "examples" / "first-run").mkdir(parents=True)
    (package_root / "docs" / "workflows").mkdir(parents=True)
    (package_root / "examples" / "first-run" / "config.yaml").write_text(
        f"project:\n  workspace: {workspace}\n",
        encoding="utf-8",
    )
    (package_root / "docs" / "workflows" / "first-run.md").write_text(
        "Use examples/first-run/config.yaml. Artifact greeting.txt.\n",
        encoding="utf-8",
    )
    return package_root


def test_first_run_safety_accepts_workspace_under_tutorial_dir(tmp_path: Path) -> None:
    check_docs = _load_check_docs()
    package_root = _write_first_run_tree(
        tmp_path,
        "tools/top_down_planning/examples/first-run/workspace",
    )
    assert check_docs.check_first_run_safety(package_root) == []


def test_first_run_safety_rejects_workspace_that_escapes_via_parent_segments(
    tmp_path: Path,
) -> None:
    check_docs = _load_check_docs()
    package_root = _write_first_run_tree(
        tmp_path,
        "tools/top_down_planning/examples/first-run/../../../outside",
    )
    errors = check_docs.check_first_run_safety(package_root)
    joined = "\n".join(errors)
    assert "examples/first-run" in joined


def test_package_docs_pass_quality_checks() -> None:
    check_docs = _load_check_docs()
    errors = check_docs.check_all(_PACKAGE_ROOT)
    assert errors == [], "\n".join(errors)
