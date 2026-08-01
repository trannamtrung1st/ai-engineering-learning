"""Configuration tests for revise_at overrides and digests."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.config import ConfigError, resolve_config
from top_down_planning.config.defaults import ALLOWED_OVERRIDE_PATHS, DEFAULT_CONFIG
from top_down_planning.domain.review_policy import resolved_revise_at
from top_down_planning.persistence.digests import compute_config_contract_digest
from tests.helpers import write_config


def test_default_revise_at_overrides_are_null() -> None:
    review = DEFAULT_CONFIG["review"]
    assert review["revise_at"] is None
    assert review["focused_plan"]["revise_at"] is None
    assert review["focused_output"]["revise_at"] is None
    assert review["whole_plan"]["revise_at"] is None
    assert review["whole_output"]["revise_at"] is None
    for path in (
        "review.revise_at",
        "review.focused_plan.revise_at",
        "review.focused_output.revise_at",
        "review.whole_plan.revise_at",
        "review.whole_output.revise_at",
    ):
        assert path in ALLOWED_OVERRIDE_PATHS


def test_null_defaults_resolve_to_builtin(tmp_path: Path) -> None:
    config_path = write_config(tmp_path / "base.yaml", "run:\n  output_goal: Goal.\n")
    config = resolve_config(config_path)
    assert resolved_revise_at(config, "whole_plan") == "major"
    assert resolved_revise_at(config, "focused_plan") == "blocker"


def test_global_revise_at_override_via_cli(tmp_path: Path) -> None:
    config_path = write_config(tmp_path / "base.yaml", "run:\n  output_goal: Goal.\n")
    config = resolve_config(config_path, ["review.revise_at=minor"])
    for review_type in (
        "focused_plan",
        "focused_output",
        "whole_plan",
        "whole_output",
    ):
        assert resolved_revise_at(config, review_type) == "minor"


def test_per_type_revise_at_wins_over_global(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "base.yaml",
        """
run:
  output_goal: Goal.
review:
  revise_at: minor
  whole_plan:
    revise_at: blocker
""",
    )
    config = resolve_config(config_path)
    assert resolved_revise_at(config, "whole_plan") == "blocker"
    assert resolved_revise_at(config, "focused_output") == "minor"


def test_invalid_revise_at_rejected(tmp_path: Path) -> None:
    config_path = write_config(tmp_path / "base.yaml", "run:\n  output_goal: Goal.\n")
    with pytest.raises(ConfigError, match="review.revise_at"):
        resolve_config(config_path, ["review.revise_at=critical"])


def test_semantic_digest_includes_non_null_revise_at(tmp_path: Path) -> None:
    config_path = write_config(tmp_path / "base.yaml", "run:\n  output_goal: Goal.\n")
    base = resolve_config(config_path)
    overridden = resolve_config(config_path, ["review.whole_plan.revise_at=blocker"])
    assert compute_config_contract_digest(base) != compute_config_contract_digest(overridden)
