from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from top_down_planning.input_loader import load_markdown_input, load_output_goal
from top_down_planning.models import DecompositionStatus, FinalStatus, PlanningLimits, RenderConfig
from top_down_planning.orchestrator import Orchestrator, RunConfig
from top_down_planning.persistence import new_run_state, save_plan
from top_down_planning.render_flow import render_from_confirmed_plan
from tests.helpers import default_generation
from tests.plan_factory import make_root_plan


@pytest.mark.asyncio
async def test_render_batch_retry_records_audit_files(
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
        render=RenderConfig(max_retries=2, final_review=False),
    )

    config = RunConfig(
        input_path=example_input,
        output_goal=loaded_goal,
        output_dir=output_dir,
        workspace_root=tmp_path,
        limits=limits,
        render=RenderConfig(max_retries=2, final_review=False),
        agent_bin=fake_agent_bin,
        skip_probe=True,
    )
    orch = Orchestrator(config)
    attempt_state = {"n": 0}

    def flaky_validate(*args, **kwargs):
        attempt_state["n"] += 1
        if attempt_state["n"] == 1:
            return ["simulated missing item"]
        return []

    with patch(
        "top_down_planning.render_flow.validate_batch_transaction",
        side_effect=flaky_validate,
    ):
        await render_from_confirmed_plan(
            orch._render_flow_deps(loaded=loaded, output_dir=output_dir),
            plan=plan,
            run_state=run_state,
        )

    batch_dir = output_dir / ".planning-output" / "render" / "batches" / "render-batch-001"
    assert (batch_dir / "request-001-prompt.md").is_file()
    assert (batch_dir / "request-002-prompt.md").is_file()
    assert attempt_state["n"] == 2
