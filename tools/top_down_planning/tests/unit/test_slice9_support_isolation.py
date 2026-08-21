"""Slice 9: repo-wide test-support isolation and Darwin CLI-cancel CI coverage."""

from __future__ import annotations

from pathlib import Path

from tests.support.isolation import sibling_test_import_modules

_REPO_ROOT = Path(__file__).resolve().parents[4]
_TESTS_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "tdp.yml"

# Historical modules that still import sibling test_*.py helpers. Shrink when migrated.
_SIBLING_IMPORT_ALLOWLIST = frozenset(
    {
        "integration/test_resume_cross_phase_e2e.py",
        "unit/test_agent_process_cleanup.py",
        "unit/test_apply_resume_crash.py",
        "unit/test_cursor_reviewer_session_binding.py",
        "unit/test_focused_review_families.py",
        "unit/test_mandatory_in_process_transitions.py",
        "unit/test_mandatory_review_acceptance.py",
        "unit/test_mandatory_review_orchestration.py",
        "unit/test_orchestration_lifecycle_atomicity.py",
        "unit/test_packaging_suite_contract.py",
        "unit/test_payload_cutover_contracts.py",
        "unit/test_persistence_review_fixes.py",
        "unit/test_persistence_round15_fixes.py",
        "unit/test_persistence_round16_fixes.py",
        "unit/test_persistence_round17_fixes.py",
        "unit/test_persistence_round3_fixes.py",
        "unit/test_persistence_round4_fixes.py",
        "unit/test_persistence_round5_fixes.py",
        "unit/test_production_apply_snapshot_evidence.py",
        "unit/test_provider_turns.py",
        "unit/test_review_revision_cas.py",
        "unit/test_reviewer_session_release.py",
        "unit/test_run_lifecycle_reconciliation.py",
        "unit/test_slice5_rereview_065f8a22_fixes.py",
        "unit/test_slice5_rereview_27eaa0b_fixes.py",
        "unit/test_slice5_rereview_2af6712b_fixes.py",
        "unit/test_slice5_rereview_41a27ee_fixes.py",
        "unit/test_slice5_rereview_4dae4f6_fixes.py",
        "unit/test_slice5_rereview_568f97b_fixes.py",
        "unit/test_slice5_rereview_6481aeb_fixes.py",
        "unit/test_slice5_rereview_992f5a0_fixes.py",
        "unit/test_slice5_rereview_c67af97_fixes.py",
        "unit/test_slice5_rereview_c947561_fixes.py",
        "unit/test_slice5_rereview_eb572b0_fixes.py",
        "unit/test_slice5_rereview_ff20bb4_fixes.py",
        "unit/test_slice6_rereview_0cd5abc8_fixes.py",
        "unit/test_slice6_rereview_1f93dab4_fixes.py",
        "unit/test_slice7_rereview_739_750.py",
        "unit/test_slice7_rereview_759_761.py",
        "unit/test_slice7_rereview_760_764.py",
        "unit/test_slice7_rereview_760_767.py",
        "unit/test_slice7_rereview_768_774.py",
        "unit/test_slice7_rereview_775_783.py",
        "unit/test_slice7_rereview_784_790.py",
        "unit/test_slice7_rereview_791_796.py",
        "unit/test_slice7_rereview_797_784.py",
        "unit/test_slice7_rereview_798_801.py",
        "unit/test_slice7_rereview_802_803.py",
        "unit/test_slice7_rereview_804_789.py",
        "unit/test_slice7_rereview_805_789.py",
        "unit/test_slice7_rereview_806.py",
        "unit/test_sub_tdp_cutover_defects.py",
        "unit/test_sub_tdp_defect_rescan.py",
        "unit/test_sub_tdp_review_continued.py",
        "unit/test_sub_tdp_review_fixes.py",
        "unit/test_whole_plan_review.py",
    }
)


def _rel_test_path(path: Path) -> str:
    return path.relative_to(_TESTS_ROOT).as_posix()


def _modules_with_sibling_test_imports() -> set[str]:
    found: set[str] = set()
    for path in _TESTS_ROOT.rglob("test_*.py"):
        if sibling_test_import_modules(path.read_text(encoding="utf-8")):
            found.add(_rel_test_path(path))
    return found


def _workflow_job_source(workflow: str, job_id: str) -> str:
    """Return only the named top-level job block (not later jobs)."""

    lines = workflow.splitlines()
    header = f"  {job_id}:"
    start = next((index for index, line in enumerate(lines) if line == header), None)
    if start is None:
        raise AssertionError(f"workflow job {job_id!r} not found")
    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.startswith("  ") and not line.startswith("   ") and line.endswith(":"):
            end = index
            break
    return "\n".join(lines[start:end])


def test_sibling_import_detector_covers_relative_integration_and_package_imports() -> None:
    source = """
from tests.integration.test_packaging_smoke import helper
from .test_prepared_runs import _built_package
from tests.unit import test_commit_crash_recovery
import tests.unit.test_foo as foo
from tests.support.run_builders import _built_package as ok
from tests.helpers import write_config
"""
    found = sibling_test_import_modules(source)
    assert "tests.integration.test_packaging_smoke" in found
    assert "test_prepared_runs" in found
    assert "tests.unit.test_commit_crash_recovery" in found
    assert "tests.unit.test_foo" in found
    assert not any("run_builders" in name or "helpers" in name for name in found)


def test_test_modules_do_not_import_sibling_test_modules_except_allowlist() -> None:
    offenders = _modules_with_sibling_test_imports()
    unexpected = offenders - _SIBLING_IMPORT_ALLOWLIST
    stale = _SIBLING_IMPORT_ALLOWLIST - offenders
    assert not unexpected, (
        "new sibling test-module imports; move helpers to tests.support "
        f"or tests.helpers: {sorted(unexpected)}"
    )
    assert not stale, (
        "allowlist entries no longer import sibling tests; remove them: "
        f"{sorted(stale)}"
    )


def test_workflow_job_source_excludes_later_jobs() -> None:
    workflow = """
jobs:
  darwin-janitor:
    steps:
      - run: echo orphan-only
  later-job:
    steps:
      - run: |
          python -m pytest -p no:xdist -o addopts='' \\
            tests/unit/test_cli_os_process_cancel.py
"""
    darwin = _workflow_job_source(workflow, "darwin-janitor")
    assert "test_cli_os_process_cancel.py" not in darwin
    assert "orphan-only" in darwin
    later = _workflow_job_source(workflow, "later-job")
    assert "test_cli_os_process_cancel.py" in later


def test_darwin_ci_runs_cli_os_process_cancel_serially() -> None:
    workflow = _WORKFLOW.read_text(encoding="utf-8")
    darwin = _workflow_job_source(workflow, "darwin-janitor")
    assert "runs-on: macos-latest" in darwin
    assert 'python-version: ["3.11", "3.13"]' in darwin
    cancel_steps = [
        block
        for block in darwin.split("- name:")
        if "test_cli_os_process_cancel.py" in block
    ]
    assert len(cancel_steps) == 1, darwin
    command = cancel_steps[0]
    assert "-p no:xdist" in command
    assert "-o addopts=''" in command
    assert "tests/unit/test_cli_os_process_cancel.py" in command
