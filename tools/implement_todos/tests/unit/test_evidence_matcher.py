"""Evidence matcher acceptance cases."""

from __future__ import annotations

from todos_tool.evidence_matcher import (
    ObservedShellRun,
    cwd_matches_spec,
    match_spec_to_observed,
    normalize_command,
    resolve_evidence_cwd,
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


def test_absolute_workspace_root_matches_dot_spec(tmp_path) -> None:
    workspace = tmp_path / "apps" / "frontend"
    workspace.mkdir(parents=True)
    assert resolve_evidence_cwd(str(workspace), workspace) == "."
    assert cwd_matches_spec(".", str(workspace), workspace_root=workspace) is True


def test_absolute_subdir_matches_relative_spec(tmp_path) -> None:
    workspace = tmp_path / "apps" / "frontend"
    subdir = workspace / "tests"
    subdir.mkdir(parents=True)
    assert resolve_evidence_cwd(str(subdir), workspace) == "tests"
    assert cwd_matches_spec("tests", str(subdir), workspace_root=workspace) is True


def test_absolute_wrong_directory_still_near_miss(tmp_path) -> None:
    workspace = tmp_path / "apps" / "frontend"
    other = tmp_path / "elsewhere"
    workspace.mkdir(parents=True)
    other.mkdir()
    result = match_spec_to_observed(
        "pytest",
        ".",
        [
            ObservedShellRun(
                command="pytest",
                cwd=str(other),
                completed=True,
                exit_code=0,
            )
        ],
        workspace_root=workspace,
    )
    assert result.passed is False
    assert result.near_misses[0].reason == "wrong_cwd"


def test_absolute_workspace_root_exact_match(tmp_path) -> None:
    workspace = tmp_path / "apps" / "frontend"
    workspace.mkdir(parents=True)
    result = match_spec_to_observed(
        "pnpm run test -- tests/",
        ".",
        [
            ObservedShellRun(
                command="pnpm run test -- tests/",
                cwd=str(workspace),
                completed=True,
                exit_code=0,
            )
        ],
        workspace_root=workspace,
    )
    assert result.passed is True
    assert result.match_kind == "exact"


def test_absolute_cwd_without_workspace_root_stays_strict() -> None:
    """Without workspace_root, captured mode keeps legacy exact cwd matching."""
    result = match_spec_to_observed(
        "pytest",
        ".",
        [
            ObservedShellRun(
                command="pytest",
                cwd="/tmp/project/apps/frontend",
                completed=True,
                exit_code=0,
            )
        ],
    )
    assert result.passed is False
    assert result.near_misses[0].reason == "wrong_cwd"


def test_relative_dot_still_matches_without_workspace_root() -> None:
    result = match_spec_to_observed(
        "pytest",
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
    assert result.passed is True


def test_trailing_slash_absolute_workspace_root(tmp_path) -> None:
    workspace = tmp_path / "apps" / "frontend"
    workspace.mkdir(parents=True)
    assert cwd_matches_spec(
        ".",
        f"{workspace}/",
        workspace_root=workspace,
    )
