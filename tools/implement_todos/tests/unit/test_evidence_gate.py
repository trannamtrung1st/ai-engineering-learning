"""Evidence gate assessment and stall detection."""

from __future__ import annotations

from todos_tool.evidence_gate import assess_evidence_gate, failure_signature
from todos_tool.evidence_matcher import ObservedShellRun
from todos_tool.models import EvidenceCommandResult, EvidenceCommandSpec, EvidenceMode


def _spec(command: str = "pytest", cwd: str = ".") -> EvidenceCommandSpec:
    return EvidenceCommandSpec(command=command, cwd=cwd)


def test_stale_worktree_fingerprint_fails_gate() -> None:
    assessment = assess_evidence_gate(
        specs=[_spec()],
        mode=EvidenceMode.CAPTURED,
        worktree_fingerprint="new-fp",
        stored_worktree_fingerprint="old-fp",
        stored_command_spec_fingerprint=None,
        captured_runs=[],
        prior_failure_signature=None,
        identical_failure_count=0,
        max_identical_failures=3,
    )
    assert assessment.passed is False
    assert assessment.stale is True


def test_identical_failure_signature_increments_and_stalls() -> None:
    specs = [_spec()]
    captured: list[ObservedShellRun] = []
    first = assess_evidence_gate(
        specs=specs,
        mode=EvidenceMode.CAPTURED,
        worktree_fingerprint="fp",
        stored_worktree_fingerprint=None,
        stored_command_spec_fingerprint=None,
        captured_runs=captured,
        prior_failure_signature=None,
        identical_failure_count=0,
        max_identical_failures=3,
    )
    assert first.passed is False
    assert first.identical_failure_count == 1

    second = assess_evidence_gate(
        specs=specs,
        mode=EvidenceMode.CAPTURED,
        worktree_fingerprint="fp",
        stored_worktree_fingerprint=first.worktree_fingerprint,
        stored_command_spec_fingerprint=first.command_spec_fingerprint,
        captured_runs=captured,
        prior_failure_signature=first.failure_signature,
        identical_failure_count=first.identical_failure_count,
        max_identical_failures=3,
    )
    third = assess_evidence_gate(
        specs=specs,
        mode=EvidenceMode.CAPTURED,
        worktree_fingerprint="fp",
        stored_worktree_fingerprint=second.worktree_fingerprint,
        stored_command_spec_fingerprint=second.command_spec_fingerprint,
        captured_runs=captured,
        prior_failure_signature=second.failure_signature,
        identical_failure_count=second.identical_failure_count,
        max_identical_failures=3,
    )
    assert third.stalled is True
    assert third.identical_failure_count == 3


def test_counter_resets_after_progress() -> None:
    specs = [_spec()]
    failed = assess_evidence_gate(
        specs=specs,
        mode=EvidenceMode.CAPTURED,
        worktree_fingerprint="fp1",
        stored_worktree_fingerprint=None,
        stored_command_spec_fingerprint=None,
        captured_runs=[],
        prior_failure_signature=None,
        identical_failure_count=2,
        max_identical_failures=3,
    )
    passed = assess_evidence_gate(
        specs=specs,
        mode=EvidenceMode.CAPTURED,
        worktree_fingerprint="fp2",
        stored_worktree_fingerprint=failed.worktree_fingerprint,
        stored_command_spec_fingerprint=failed.command_spec_fingerprint,
        captured_runs=[
            ObservedShellRun(
                command="pytest",
                cwd=".",
                completed=True,
                exit_code=0,
            )
        ],
        prior_failure_signature=failed.failure_signature,
        identical_failure_count=failed.identical_failure_count,
        max_identical_failures=3,
    )
    assert passed.passed is True
    assert passed.identical_failure_count == 0


def test_driver_mode_tags_results() -> None:
    assessment = assess_evidence_gate(
        specs=[_spec("echo ok")],
        mode=EvidenceMode.DRIVER,
        worktree_fingerprint="fp",
        stored_worktree_fingerprint=None,
        stored_command_spec_fingerprint=None,
        driver_results=[
            EvidenceCommandResult(
                command="echo ok",
                cwd=".",
                passed=True,
                source="driver",
                exit_code=0,
            )
        ],
        prior_failure_signature=None,
        identical_failure_count=0,
        max_identical_failures=3,
    )
    assert assessment.passed is True
    assert assessment.results[0].source == "driver"


def test_failure_signature_changes_with_worktree() -> None:
    results = [
        EvidenceCommandResult(
            command="pytest",
            cwd=".",
            passed=False,
            source="captured",
            exit_code=1,
            match_kind="failed_run",
        )
    ]
    sig1 = failure_signature(
        worktree_fingerprint="a",
        command_spec_fingerprint="spec",
        results=results,
    )
    sig2 = failure_signature(
        worktree_fingerprint="b",
        command_spec_fingerprint="spec",
        results=results,
    )
    assert sig1 != sig2


def test_gate_passes_absolute_workspace_cwd(tmp_path) -> None:
    workspace = tmp_path / "apps" / "frontend"
    workspace.mkdir(parents=True)
    assessment = assess_evidence_gate(
        specs=[_spec("pnpm run test -- tests/")],
        mode=EvidenceMode.CAPTURED,
        worktree_fingerprint="fp",
        stored_worktree_fingerprint=None,
        stored_command_spec_fingerprint=None,
        captured_runs=[
            ObservedShellRun(
                command="pnpm run test -- tests/",
                cwd=str(workspace),
                completed=True,
                exit_code=0,
            )
        ],
        prior_failure_signature=None,
        identical_failure_count=0,
        max_identical_failures=3,
        workspace_root=workspace,
    )
    assert assessment.passed is True
    assert assessment.results[0].passed is True
    assert assessment.results[0].match_kind == "exact"
