import json
from pathlib import Path

import pytest

from top_down_planning.errors import ResumeError
from top_down_planning.models import PlanningLimits, RunState
from top_down_planning.persistence import (
    _normalize_legacy_run_state,
    ensure_resume_compatible,
    load_run_state,
    render_attempt_prefix,
    save_run_state,
)


def test_normalize_legacy_run_state_defaults_concurrency_to_one() -> None:
    normalized = _normalize_legacy_run_state(
        {
            "limits": {
                "max_iterations": 10,
                "batch_size": 2,
            }
        }
    )
    assert normalized["limits"]["concurrent_batches"] == 1


def test_load_run_state_applies_legacy_concurrency_default(tmp_path: Path) -> None:
    state_dir = tmp_path / ".planning-output"
    state_dir.mkdir(parents=True)
    (state_dir / "run-state.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "iteration": 2,
                "limits": {
                    "max_iterations": 10,
                    "max_depth": 6,
                    "max_items": 200,
                    "max_children_per_expansion": 12,
                    "batch_size": 2,
                    "max_retries": 3,
                    "session_timeout_seconds": 600,
                    "parse_error_threshold": 20,
                },
            }
        ),
        encoding="utf-8",
    )

    loaded = load_run_state(tmp_path)
    assert loaded is not None
    assert loaded.limits.concurrent_batches == 1


def test_resume_rejects_concurrent_batches_mismatch(tmp_path: Path) -> None:
    output_dir = tmp_path / "planning-output"
    output_dir.mkdir()
    state_dir = output_dir / ".planning-output"
    state_dir.mkdir()
    (state_dir / "plan.yaml").write_text(
        "\n".join(
            [
                "schema_version: 1",
                "source:",
                "  input_file: ./idea.md",
                "  output_goal: goal",
                "  input_digest: input-digest",
                "  output_goal_digest: goal-digest",
                "plan:",
                "  - id: item-001",
                "    title: Root",
                "    objective: Root objective",
                "    depth: 0",
                "    order: 1",
                "result:",
                "  status: planning",
            ]
        ),
        encoding="utf-8",
    )
    run_state = RunState(
        input_digest="input-digest",
        output_goal_digest="goal-digest",
        limits=PlanningLimits(concurrent_batches=1),
    )
    save_run_state(output_dir, run_state)

    with pytest.raises(ResumeError, match="concurrent_batches"):
        ensure_resume_compatible(
            output_dir,
            input_digest="input-digest",
            output_goal_digest="goal-digest",
            limits=PlanningLimits(concurrent_batches=3),
            resume=True,
        )


def test_render_attempt_prefix(tmp_path: Path) -> None:
    prefix = render_attempt_prefix(tmp_path, 2)
    assert prefix.endswith("/.planning-output/iterations/render-002")
