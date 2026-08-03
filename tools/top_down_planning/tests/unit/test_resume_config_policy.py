"""Tests for resume execution-policy allowlist and config comparison (§21 tests 6–8, 16–20)."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.config.defaults import ALLOWED_OVERRIDE_PATHS
from top_down_planning.config.resume_policy import (
    RESUME_EXECUTION_POLICY_ALLOWLIST,
    RESUME_PRESENTATION_ALLOWLIST,
    compare_resume_configs,
    resolve_resume_candidate_config,
    validate_resume_config_comparison,
)
from top_down_planning.config import resolve_config
from top_down_planning.persistence.digests import (
    compute_config_contract_digest,
    compute_config_execution_digest,
)
from tests.helpers import write_config


def _base_config() -> dict:
    return resolve_config(None)


def test_resume_execution_allowlist_covers_all_limit_paths() -> None:
    limit_paths = {
        path for path in ALLOWED_OVERRIDE_PATHS if path.startswith("limits.")
    }
    assert limit_paths == RESUME_EXECUTION_POLICY_ALLOWLIST


def test_resume_presentation_allowlist_matches_observability_notifications_and_runs_dir() -> None:
    expected = {
        path
        for path in ALLOWED_OVERRIDE_PATHS
        if path.startswith("observability.")
        or path.startswith("notifications.")
        or path == "runtime.runs_dir"
    }
    assert expected == RESUME_PRESENTATION_ALLOWLIST


def test_resume_rejects_contract_path_change() -> None:
    stored = _base_config()
    candidate = resolve_config(None, ["planning.max_depth=2"])
    comparison = validate_resume_config_comparison(compare_resume_configs(stored, candidate))
    assert not comparison.ok
    assert any("contract change" in error for error in comparison.errors)


def test_resume_rejects_provider_change() -> None:
    stored = _base_config()
    candidate = resolve_config(None, ["provider.name=other"])
    comparison = validate_resume_config_comparison(compare_resume_configs(stored, candidate))
    assert not comparison.ok
    assert any("session-strategy" in error for error in comparison.errors)


def test_resume_rejects_skip_probe_change() -> None:
    stored = _base_config()
    candidate = resolve_config(None, ["provider.skip_probe=true"])
    comparison = validate_resume_config_comparison(compare_resume_configs(stored, candidate))
    assert not comparison.ok
    assert any("session-strategy" in error for error in comparison.errors)


def test_resume_rejects_model_change() -> None:
    stored = _base_config()
    candidate = resolve_config(None, ["agent_context.producer.model=gpt-4"])
    comparison = validate_resume_config_comparison(compare_resume_configs(stored, candidate))
    assert not comparison.ok
    assert any("session-strategy" in error for error in comparison.errors)


def test_resume_allows_limit_increase() -> None:
    stored = _base_config()
    candidate = resolve_config(None, ["limits.planning.max_agent_turns=80"])
    comparison = validate_resume_config_comparison(compare_resume_configs(stored, candidate))
    assert comparison.ok
    assert comparison.contract_digest_changed is False
    assert comparison.execution_digest_changed is True


def test_resume_rejects_limit_decrease() -> None:
    stored = resolve_config(None, ["limits.planning.max_agent_turns=40"])
    candidate = resolve_config(None, ["limits.planning.max_agent_turns=20"])
    comparison = validate_resume_config_comparison(compare_resume_configs(stored, candidate))
    assert not comparison.ok
    assert any("must increase the stored limit" in error for error in comparison.errors)


def test_resume_rejects_limit_equal_to_consumed_usage() -> None:
    stored = resolve_config(None, ["limits.planning.max_agent_turns=40"])
    candidate = resolve_config(None, ["limits.planning.max_agent_turns=41"])
    comparison = compare_resume_configs(stored, candidate)
    validated = validate_resume_config_comparison(
        comparison,
        consumed_limits={"limits.planning.max_agent_turns": 41},
        candidate_config=candidate,
    )
    assert not validated.ok
    assert any("strictly greater than consumed" in error for error in validated.errors)


def test_resume_rejects_limit_below_consumed_usage() -> None:
    stored = resolve_config(None, ["limits.planning.max_agent_turns=40"])
    candidate = resolve_config(None, ["limits.planning.max_agent_turns=50"])
    comparison = compare_resume_configs(stored, candidate)
    validated = validate_resume_config_comparison(
        comparison,
        consumed_limits={"limits.planning.max_agent_turns": 55},
        candidate_config=candidate,
    )
    assert not validated.ok
    assert any("strictly greater than consumed" in error for error in validated.errors)


def test_resume_from_limit_exhausted_requires_candidate_above_consumed() -> None:
    stored = resolve_config(None, ["limits.planning.max_agent_turns=5"])
    candidate = resolve_config(None, ["limits.planning.max_agent_turns=5"])
    comparison = compare_resume_configs(stored, candidate)
    validated = validate_resume_config_comparison(
        comparison,
        consumed_limits={"limits.planning.max_agent_turns": 5},
        candidate_config=candidate,
    )
    assert not validated.ok
    assert any(
        "strictly greater than consumed usage" in error for error in validated.errors
    )


def test_resume_allows_provider_retry_increase() -> None:
    stored = _base_config()
    candidate = resolve_config(None, ["limits.provider.max_retries_per_call=5"])
    comparison = validate_resume_config_comparison(compare_resume_configs(stored, candidate))
    assert comparison.ok


def test_resume_allows_provider_idle_timeout_override() -> None:
    stored = _base_config()
    candidate = resolve_config(None, ["limits.provider.turn_idle_timeout_seconds=600"])
    comparison = validate_resume_config_comparison(compare_resume_configs(stored, candidate))
    assert comparison.ok
    assert candidate["limits"]["provider"]["turn_idle_timeout_seconds"] == 600


def test_resume_allows_presentation_change() -> None:
    stored = _base_config()
    candidate = resolve_config(None, ["observability.log_level=verbose"])
    comparison = validate_resume_config_comparison(compare_resume_configs(stored, candidate))
    assert comparison.ok
    assert comparison.contract_digest_changed is False
    assert comparison.execution_digest_changed is False


def test_limit_only_change_preserves_contract_digest() -> None:
    stored = _base_config()
    candidate = resolve_config(None, ["limits.production.max_batches=99"])
    assert compute_config_contract_digest(stored) == compute_config_contract_digest(candidate)
    assert compute_config_execution_digest(stored) != compute_config_execution_digest(candidate)


def test_paths_outside_resume_allowlist_blocked_even_when_overridable(
    tmp_path: Path,
) -> None:
    config_path = write_config(
        tmp_path / "base.yaml",
        "run:\n  output_goal: Goal.\nreview:\n  revise_at: suggestion\n",
    )
    stored = resolve_config(config_path)
    candidate = resolve_config(config_path, ["review.revise_at=blocker"])
    assert "review.revise_at" in ALLOWED_OVERRIDE_PATHS
    assert "review.revise_at" not in RESUME_EXECUTION_POLICY_ALLOWLIST
    comparison = validate_resume_config_comparison(compare_resume_configs(stored, candidate))
    assert not comparison.ok


def test_resolve_resume_candidate_config_matches_resolve_config(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "base.yaml",
        "run:\n  output_goal: Goal.\nlimits:\n  production:\n    max_batches: 12\n",
    )
    overrides = ["limits.production.max_batches=15"]
    assert resolve_resume_candidate_config(config_path, overrides, cwd=tmp_path) == resolve_config(
        config_path,
        overrides,
        cwd=tmp_path,
    )
