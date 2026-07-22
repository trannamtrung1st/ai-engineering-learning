"""Evidence matcher acceptance cases."""

from __future__ import annotations

from todos_tool.evidence_matcher import (
    ObservedShellRun,
    match_spec_to_observed,
    normalize_command,
)


def test_exact_normalized_command_match() -> None:
    result = match_spec_to_observed(
        "pytest tests/unit",
        ".",
        [
            ObservedShellRun(
                command="pytest   tests/unit",
                cwd=".",
                completed=True,
                exit_code=0,
            )
        ],
    )
    assert result.passed is True
    assert result.match_kind == "exact"


def test_cd_prefix_wrapper_near_miss() -> None:
    result = match_spec_to_observed(
        "pytest",
        ".",
        [
            ObservedShellRun(
                command="cd subdir && pytest",
                cwd=".",
                completed=True,
                exit_code=0,
            )
        ],
    )
    assert result.passed is False
    assert result.near_misses
    assert result.near_misses[0].reason == "cd_prefix_wrapper"


def test_wrong_cwd_near_miss() -> None:
    result = match_spec_to_observed(
        "pytest",
        "subdir",
        [
            ObservedShellRun(
                command="pytest",
                cwd=".",
                completed=True,
                exit_code=0,
            )
        ],
    )
    assert result.passed is False
    assert result.near_misses[0].reason == "wrong_cwd"


def test_piped_variant_near_miss() -> None:
    result = match_spec_to_observed(
        "pytest",
        ".",
        [
            ObservedShellRun(
                command="pytest | tee log.txt",
                cwd=".",
                completed=True,
                exit_code=0,
            )
        ],
    )
    assert result.passed is False
    assert result.near_misses[0].reason == "piped_variant"


def test_bash_wrapper_near_miss() -> None:
    result = match_spec_to_observed(
        "pytest",
        ".",
        [
            ObservedShellRun(
                command="bash -c 'pytest'",
                cwd=".",
                completed=True,
                exit_code=0,
            )
        ],
    )
    assert result.passed is False
    assert result.near_misses[0].reason == "shell_wrapper"


def test_extra_chained_command_near_miss() -> None:
    result = match_spec_to_observed(
        "pytest",
        ".",
        [
            ObservedShellRun(
                command="pytest && echo done",
                cwd=".",
                completed=True,
                exit_code=0,
            )
        ],
    )
    assert result.passed is False
    assert result.near_misses[0].reason == "extra_chained_command"


def test_case_only_drift_not_exact_match() -> None:
    result = match_spec_to_observed(
        "PyTest",
        ".",
        [
            ObservedShellRun(
                command="pytest",
                cwd=".",
                completed=True,
                exit_code=0,
            )
        ],
    )
    assert result.passed is False
    assert any(m.reason == "case_drift" for m in result.near_misses)


def test_normalize_command_is_case_sensitive() -> None:
    assert normalize_command("PyTest") != normalize_command("pytest")
