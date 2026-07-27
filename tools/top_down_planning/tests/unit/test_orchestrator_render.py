from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from top_down_planning.input_loader import load_markdown_input
from top_down_planning.models import DecompositionStatus, FinalStatus, PlanningLimits, RenderConfig
from top_down_planning.orchestrator import Orchestrator, RunConfig
from top_down_planning.persistence import new_run_state, save_plan
from top_down_planning.render_flow import render_from_confirmed_plan
from tests.helpers import default_generation, render_output_goal
from tests.plan_factory import make_root_plan


@pytest.mark.asyncio
async def test_render_node_retry_records_audit_files(
    tmp_path: Path,
    example_input: Path,
    fake_agent_bin: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_AGENT_RENDER_PRODUCE_NODE", "item-001")
    loaded = load_markdown_input(example_input)
    loaded_goal = render_output_goal()
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
            return ["simulated validation failure"]
        return []

    with patch(
        "top_down_planning.render_flow.validate_node_render_transaction",
        side_effect=flaky_validate,
    ):
        await render_from_confirmed_plan(
            orch._render_flow_deps(loaded=loaded, output_dir=output_dir),
            plan=plan,
            run_state=run_state,
        )

    node_dir = (
        output_dir
        / ".planning-output"
        / "render"
        / "transactions"
        / "txn-item-001-render"
    )
    assert (node_dir / "request-001-prompt.md").is_file()
    assert (node_dir / "request-002-prompt.md").is_file()
    assert attempt_state["n"] == 2
