from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import top_down_planning.orchestrator as orch_mod
from top_down_planning.cursor_client import SessionResult
from top_down_planning.input_loader import load_markdown_input, load_output_goal
from top_down_planning.models import DecompositionStatus, FinalStatus, PlanningLimits
from top_down_planning.orchestrator import Orchestrator, RunConfig
from top_down_planning.persistence import new_run_state, save_plan
from tests.helpers import default_generation
from tests.plan_factory import make_root_plan


@pytest.mark.asyncio
async def test_render_retry_writes_per_attempt_audit_files(
    tmp_path: Path,
    example_input: Path,
    fake_agent_bin: str,
) -> None:
    loaded = load_markdown_input(example_input)
    loaded_goal = load_output_goal(inline="Produce an actionable implementation plan")
    output_dir = tmp_path / "planning-output"
    limits = PlanningLimits(max_retries=2)
    plan = make_root_plan(
        input_file=str(example_input),
        output_goal=loaded_goal.text,
        input_digest=loaded.digest,
        output_goal_digest=loaded_goal.digest,
    )
    plan.plan[0].decomposition_status = DecompositionStatus.ACTIONABLE
    plan.result.status = FinalStatus.COMPLETE
    output_dir.mkdir(parents=True, exist_ok=True)
    save_plan(output_dir, plan)
    run_state = new_run_state(
        input_file=str(example_input),
        output_goal=loaded_goal.source_label,
        input_digest=loaded.digest,
        output_goal_digest=loaded_goal.digest,
        limits=limits,
        generation=default_generation(),
    )

    config = RunConfig(
        input_path=example_input,
        output_goal=loaded_goal,
        output_dir=output_dir,
        workspace_root=tmp_path,
        limits=limits,
        agent_bin=fake_agent_bin,
        skip_probe=True,
    )
    orch = Orchestrator(config)
    attempt_state = {"n": 0}

    def flaky_validate(plan, paths):
        attempt_state["n"] += 1
        if attempt_state["n"] == 1:
            return ["simulated missing item"]
        return []

    async def fake_session(**kwargs):
        return SessionResult(exit_code=0, assistant_text="rendered")

    with patch.object(orch_mod, "validate_render_coverage", side_effect=flaky_validate):
        with patch.object(orch_mod, "discover_written_artifacts", return_value=[tmp_path / "x.md"]):
            with patch.object(orch.client, "run_session", side_effect=fake_session):
                await orch._run_final_render(
                    loaded=loaded,
                    plan=plan,
                    output_dir=output_dir,
                    run_state=run_state,
                )

    iter_dir = output_dir / ".planning-output" / "iterations"
    assert (iter_dir / "render-001-request-prompt.md").is_file()
    assert (iter_dir / "render-001-response.json").is_file()
    assert (iter_dir / "render-002-request-prompt.md").is_file()
    assert (iter_dir / "render-002-response.json").is_file()
    assert not (iter_dir / "render-request-prompt.md").exists()
    assert attempt_state["n"] == 2
