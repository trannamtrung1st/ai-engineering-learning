"""Unit tests for invocation options and observability precedence."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from top_down_planning.cli.main import build_parser
from top_down_planning.config import resolve_config
from top_down_planning.invocation import (
    _optional_positive_limit,
    observability_options_from_args_and_config,
    invocation_options_from_args,
    invocation_to_dict,
)
from top_down_planning.persistence.digests import compute_config_contract_digest
from tests.helpers import write_config


def _parse(argv: list[str]) -> Namespace:
    return build_parser().parse_args(argv)


def test_yaml_log_level_applies_when_cli_omits_flag(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "obs.yaml",
        """
run:
  output_goal: Goal.
observability:
  log_level: verbose
""",
    )
    resolved = resolve_config(config_path)
    args = _parse(["run", "--config", str(config_path)])
    options = observability_options_from_args_and_config(args, resolved_config=resolved)
    assert options.log_level == "verbose"


def test_observability_defaults_show_timestamps_off(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "obs.yaml",
        "run:\n  output_goal: Goal.\n",
    )
    resolved = resolve_config(config_path)
    args = _parse(["run", "--config", str(config_path)])
    options = observability_options_from_args_and_config(args, resolved_config=resolved)
    assert options.show_timestamps is False


def test_explicit_no_timestamps_overrides_yaml_true(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "obs.yaml",
        """
run:
  output_goal: Goal.
observability:
  show_timestamps: true
""",
    )
    resolved = resolve_config(config_path)
    args = _parse(["run", "--config", str(config_path), "--no-timestamps"])
    options = observability_options_from_args_and_config(args, resolved_config=resolved)
    assert options.show_timestamps is False


def test_explicit_no_agent_transcript_overrides_yaml_true(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "obs.yaml",
        """
run:
  output_goal: Goal.
observability:
  agent_transcript: true
""",
    )
    resolved = resolve_config(config_path)
    args = _parse(["run", "--config", str(config_path), "--no-agent-transcript"])
    options = observability_options_from_args_and_config(args, resolved_config=resolved)
    assert options.agent_transcript is False


def test_explicit_agent_transcript_enables_when_yaml_false(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "obs.yaml",
        """
run:
  output_goal: Goal.
observability:
  agent_transcript: false
""",
    )
    resolved = resolve_config(config_path)
    args = _parse(["run", "--config", str(config_path), "--agent-transcript"])
    options = observability_options_from_args_and_config(args, resolved_config=resolved)
    assert options.agent_transcript is True


def test_set_override_sits_below_explicit_cli_log_level(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "obs.yaml",
        "run:\n  output_goal: Goal.\n",
    )
    resolved = resolve_config(config_path, ["observability.log_level=trace"])
    args = _parse(
        ["run", "--config", str(config_path), "--set", "observability.log_level=trace", "--log-level", "quiet"]
    )
    options = observability_options_from_args_and_config(args, resolved_config=resolved)
    assert resolved["observability"]["log_level"] == "trace"
    assert options.log_level == "quiet"


def test_observability_changes_do_not_affect_config_digest(tmp_path: Path) -> None:
    base_path = write_config(
        tmp_path / "base.yaml",
        """
run:
  output_goal: Goal.
planning:
  max_depth: 4
""",
    )
    verbose_path = write_config(
        tmp_path / "verbose.yaml",
        """
run:
  output_goal: Goal.
planning:
  max_depth: 4
observability:
  log_level: verbose
  log_format: jsonl
  color: never
  show_agent_text: false
  show_timestamps: false
  agent_transcript: true
""",
    )
    base = resolve_config(base_path)
    verbose = resolve_config(verbose_path)
    assert compute_config_contract_digest(base) == compute_config_contract_digest(verbose)


def test_run_boundaries_and_acceptance_affect_config_digest(tmp_path: Path) -> None:
    base = resolve_config(
        write_config(
            tmp_path / "base.yaml",
            """
run:
  output_goal: Goal.
  boundaries:
    - stay in tools/
  acceptance:
    - tests pass
""",
        )
    )
    drifted_boundaries = resolve_config(
        write_config(
            tmp_path / "boundaries.yaml",
            """
run:
  output_goal: Goal.
  boundaries:
    - stay in tools/
    - no docs rewrites
  acceptance:
    - tests pass
""",
        )
    )
    drifted_acceptance = resolve_config(
        write_config(
            tmp_path / "acceptance.yaml",
            """
run:
  output_goal: Goal.
  boundaries:
    - stay in tools/
  acceptance:
    - tests pass
    - resume stays green
""",
        )
    )
    assert compute_config_contract_digest(base) != compute_config_contract_digest(drifted_boundaries)
    assert compute_config_contract_digest(base) != compute_config_contract_digest(drifted_acceptance)


def test_runtime_runs_dir_excluded_from_config_digest(tmp_path: Path) -> None:
    no_runtime = write_config(
        tmp_path / "no-runtime.yaml",
        "run:\n  output_goal: Goal.\n",
    )
    with_runtime = write_config(
        tmp_path / "with-runtime.yaml",
        """
run:
  output_goal: Goal.
runtime:
  runs_dir: .tdp/runs
""",
    )
    assert compute_config_contract_digest(resolve_config(no_runtime)) == compute_config_contract_digest(
        resolve_config(with_runtime)
    )


def test_invocation_to_dict_round_trip_fields() -> None:
    args = _parse(
        [
            "run",
            "--config",
            "cfg.yaml",
            "--log-level",
            "trace",
            "--no-agent-text",
            "--agent-transcript",
        ]
    )
    invocation = invocation_options_from_args(args)
    payload = invocation_to_dict(invocation)
    assert payload["observability"]["log_level"] == "trace"
    assert payload["observability"]["show_agent_text"] is False
    assert payload["observability"]["agent_transcript"] is True
    assert payload["command"] == "run"


def test_observability_truncation_limits_from_yaml_and_cli(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "obs.yaml",
        """
run:
  output_goal: Goal.
observability:
  max_message_length: 500
  max_tool_summary_length: 120
""",
    )
    resolved = resolve_config(config_path)
    args = _parse(["run", "--config", str(config_path)])
    options = observability_options_from_args_and_config(args, resolved_config=resolved)
    assert options.max_message_length == 500
    assert options.max_tool_summary_length == 120

    cli_args = _parse(
        [
            "run",
            "--config",
            str(config_path),
            "--max-message-length",
            "80",
            "--max-tool-summary-length",
            "60",
        ]
    )
    cli_options = observability_options_from_args_and_config(
        cli_args,
        resolved_config=resolved,
    )
    assert cli_options.max_message_length == 80
    assert cli_options.max_tool_summary_length == 60


def test_observability_truncation_defaults_are_unlimited(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "obs.yaml",
        "run:\n  output_goal: Goal.\n",
    )
    resolved = resolve_config(config_path)
    args = _parse(["run", "--config", str(config_path)])
    options = observability_options_from_args_and_config(args, resolved_config=resolved)
    assert options.max_message_length is None
    assert options.max_tool_summary_length is None


def test_observability_truncation_rejects_non_positive_values() -> None:
    with pytest.raises(ValueError, match=r"max_message_length must be >= 1"):
        _optional_positive_limit(0, field="observability.max_message_length")


def test_notification_defaults_from_invocation_options() -> None:
    args = _parse(["run", "--config", "cfg.yaml"])
    invocation = invocation_options_from_args(args)
    assert invocation.notifications.enabled is True
    assert invocation.notifications.progress is False
