"""Validation preflight and mechanical format auto-repair tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from todos_tool.models import ValidationCommandResult
from todos_tool.orchestrator import Orchestrator
from todos_tool.persistence import attempts_dir, new_run_state
from todos_tool.validation_runner import (
    infer_format_fix_commands,
    is_format_only_validation_failure,
    load_persisted_validation_results,
    run_mechanical_format_repair,
    run_validation_preflight,
)


def test_infer_format_fix_commands_from_project_check(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"check": "pnpm run format:check", "format": "oxfmt"}}),
        encoding="utf-8",
    )
    (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")

    fixes = infer_format_fix_commands(tmp_path, ["pnpm run check"])
    assert fixes == ["pnpm run format"]


def test_is_format_only_validation_failure_detects_oxfmt_output() -> None:
    results = [
        ValidationCommandResult(
            command="pnpm run check",
            passed=False,
            exit_code=1,
            summary=(
                "> pnpm run format:check\n"
                "Format issues found in above 3 files. Run without `--check` to fix."
            ),
        )
    ]
    assert is_format_only_validation_failure(results) is True


def test_is_format_only_validation_failure_rejects_type_errors() -> None:
    results = [
        ValidationCommandResult(
            command="pnpm run check",
            passed=False,
            exit_code=1,
            summary="src/app.ts(1,1): error TS2304: Cannot find name 'Foo'.",
        )
    ]
    assert is_format_only_validation_failure(results) is False


@pytest.mark.asyncio
async def test_run_validation_preflight_executes_format_script(tmp_path: Path) -> None:
    script = tmp_path / "run-format.sh"
    script.write_text("#!/bin/sh\ntouch formatted.marker\n", encoding="utf-8")
    script.chmod(0o755)
    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "scripts": {
                    "format": "./run-format.sh",
                    "format:check": "test -f formatted.marker",
                }
            }
        ),
        encoding="utf-8",
    )

    results = await run_validation_preflight(
        tmp_path,
        ["npm run format:check"],
        timeout_seconds=5,
    )
    assert len(results) == 1
    assert results[0].passed is True
    assert (tmp_path / "formatted.marker").is_file()


@pytest.mark.asyncio
async def test_mechanical_format_repair_reruns_validation(tmp_path: Path) -> None:
    state_file = tmp_path / ".format-pass-after-fix"
    check_script = tmp_path / "check.sh"
    check_script.write_text(
        "#!/bin/sh\n"
        "if [ -f .format-pass-after-fix ]; then exit 0; fi\n"
        "echo 'Format issues found in above 1 files.' >&2\n"
        "exit 1\n",
        encoding="utf-8",
    )
    check_script.chmod(0o755)
    fix_script = tmp_path / "fix.sh"
    fix_script.write_text(
        "#!/bin/sh\n"
        "touch .format-pass-after-fix\n",
        encoding="utf-8",
    )
    fix_script.chmod(0o755)
    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "scripts": {
                    "check": "./check.sh",
                    "format": "./fix.sh",
                    "format:check": "./check.sh",
                }
            }
        ),
        encoding="utf-8",
    )

    results = await run_mechanical_format_repair(
        tmp_path,
        ["npm run check"],
        timeout_seconds=5,
    )
    assert len(results) == 1
    assert results[0].passed is True
    assert state_file.is_file()


def test_load_persisted_validation_results_prefers_latest_repair_file(
    tmp_path: Path,
) -> None:
    attempt_dir = tmp_path / "attempts" / "01"
    attempt_dir.mkdir(parents=True)
    (attempt_dir / "validation-results.json").write_text(
        json.dumps(
            {
                "results": [
                    {
                        "command": "pytest",
                        "passed": False,
                        "exit_code": 1,
                        "summary": "first failure",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "validation-results-repair-1.json").write_text(
        json.dumps(
            {
                "results": [
                    {
                        "command": "pytest",
                        "passed": False,
                        "exit_code": 2,
                        "summary": "repair failure",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    loaded = load_persisted_validation_results(
        attempt_dir,
        validation_repair_count=1,
    )
    assert len(loaded) == 1
    assert loaded[0].summary == "repair failure"


def test_validation_failure_feedback_survives_cache_invalidate(
    git_project: Path,
) -> None:
    runs_dir = git_project / "todos" / "runs" / "TASK-001"
    attempt_dir = attempts_dir(runs_dir, 1)
    attempt_dir.mkdir(parents=True, exist_ok=True)
    (attempt_dir / "validation-results.json").write_text(
        json.dumps(
            {
                "results": [
                    {
                        "command": "pnpm run check",
                        "passed": False,
                        "exit_code": 1,
                        "summary": "Format issues found in above 2 files.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    state = new_run_state("TASK-001", "abc123")
    state.logical_attempt = 1
    state.validation_results = [
        ValidationCommandResult(
            command="pnpm run check",
            passed=False,
            exit_code=1,
            summary="Format issues found in above 2 files.",
        )
    ]

    orch = Orchestrator.__new__(Orchestrator)
    feedback = orch._validation_failure_feedback(state, runs_dir)
    state.validation_results = []
    feedback_after_invalidate = orch._validation_failure_feedback(state, runs_dir)

    assert "Format issues found" in feedback
    assert feedback == feedback_after_invalidate


def test_infer_format_fix_commands_for_pnpm_exec_oxfmt() -> None:
    fixes = infer_format_fix_commands(
        Path("/tmp"),
        ["pnpm exec oxfmt --check src/foo.ts"],
    )
    assert fixes == ["pnpm exec oxfmt src/foo.ts"]


def test_is_format_only_allows_oxlint_warning_with_format_failure() -> None:
    summary = (
        "> pnpm run format:check\n"
        "Format issues found in above 3 files.\n"
        "  ! react(only-export-components): warning\n"
        "Found 1 warning and 0 errors."
    )
    results = [
        ValidationCommandResult(
            command="pnpm run check",
            passed=False,
            exit_code=1,
            summary=summary,
        )
    ]
    assert is_format_only_validation_failure(results) is True


def test_validation_failure_feedback_loads_persisted_results(
    git_project: Path,
) -> None:
    runs_dir = git_project / "todos" / "runs" / "TASK-001"
    attempt_dir = attempts_dir(runs_dir, 1)
    attempt_dir.mkdir(parents=True, exist_ok=True)
    (attempt_dir / "validation-results.json").write_text(
        json.dumps(
            {
                "results": [
                    {
                        "command": "pnpm run check",
                        "passed": False,
                        "exit_code": 1,
                        "summary": "Format issues found in above 2 files.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    state = new_run_state("TASK-001", "abc123")
    state.logical_attempt = 1
    state.validation_results = []

    orch = Orchestrator.__new__(Orchestrator)
    feedback = orch._validation_failure_feedback(state, runs_dir)
    assert "Format issues found" in feedback
    assert "passed=false" in feedback
