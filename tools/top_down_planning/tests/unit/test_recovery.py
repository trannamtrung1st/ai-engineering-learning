import json
from pathlib import Path

import pytest

from top_down_planning.models import (
    AgentResponse,
    ChildDraft,
    ExpandOperation,
    PlanningLimits,
    RunActiveStatus,
)
from top_down_planning.orchestrator import Orchestrator, RunConfig
from top_down_planning.persistence import (
    load_plan,
    new_run_state,
    save_plan,
    save_run_state,
)
from top_down_planning.recovery import (
    backup_canonical_plan,
    is_plan_run_state_desynced,
    recover_plan_from_iterations,
    restore_canonical_plan,
)
from top_down_planning.scheduler import initialize_root_plan
from tests.plan_factory import make_root_plan
from top_down_planning.state_updates import apply_response


def test_detect_desynced_plan_and_run_state() -> None:
    plan = make_root_plan(
        input_file="./idea.md",
        output_goal="goal",
        input_digest="a",
        output_goal_digest="b",
    )
    run = new_run_state(
        input_file="./idea.md",
        output_goal="goal",
        input_digest="a",
        output_goal_digest="b",
        limits=PlanningLimits(),
    )
    run.iteration = 4
    assert is_plan_run_state_desynced(plan, run)


def test_recover_plan_from_iteration_audit(tmp_path: Path) -> None:
    plan = make_root_plan(
        input_file="./idea.md",
        output_goal="goal",
        input_digest="a",
        output_goal_digest="b",
    )
    save_plan(tmp_path, plan)

    response = AgentResponse(
        operations=[
            ExpandOperation(
                node_id="item-001",
                children=[
                    ChildDraft(title="Area A", objective="Do A"),
                    ChildDraft(title="Area B", objective="Do B"),
                ],
            )
        ]
    )
    audit_dir = tmp_path / ".planning-output" / "iterations"
    audit_dir.mkdir(parents=True)
    (audit_dir / "001-response.json").write_text(
        json.dumps(response.model_dump(mode="json")),
        encoding="utf-8",
    )

    recovered = recover_plan_from_iterations(tmp_path, plan)
    assert recovered is not None
    assert len(recovered.plan) == 3


def test_recover_plan_from_transaction_audit(tmp_path: Path) -> None:
    plan = make_root_plan(
        input_file="./idea.md",
        output_goal="goal",
        input_digest="a",
        output_goal_digest="b",
    )
    save_plan(tmp_path, plan)

    response = AgentResponse(
        operations=[
            ExpandOperation(
                node_id="item-001",
                children=[
                    ChildDraft(title="Area A", objective="Do A"),
                    ChildDraft(title="Area B", objective="Do B"),
                ],
            )
        ]
    )
    audit_dir = tmp_path / ".planning-output" / "iterations"
    audit_dir.mkdir(parents=True)
    (audit_dir / "001-transaction.json").write_text(
        json.dumps(response.model_dump(mode="json")),
        encoding="utf-8",
    )

    recovered = recover_plan_from_iterations(tmp_path, plan)
    assert recovered is not None
    assert len(recovered.plan) == 3


def test_restore_canonical_plan_after_agent_reset(tmp_path: Path) -> None:
    plan = make_root_plan(
        input_file="./idea.md",
        output_goal="goal",
        input_digest="a",
        output_goal_digest="b",
    )
    plan = apply_response(
        plan,
        AgentResponse(
            operations=[
                ExpandOperation(
                    node_id="item-001",
                    children=[ChildDraft(title="Area A", objective="Do A")],
                )
            ]
        ),
    )
    save_plan(tmp_path, plan)
    backup = backup_canonical_plan(tmp_path)

    save_plan(
        tmp_path,
        make_root_plan(
            input_file="./idea.md",
            output_goal="goal",
            input_digest="a",
            output_goal_digest="b",
        ),
    )

    restored = restore_canonical_plan(tmp_path, backup, min_items=len(plan.plan))
    assert restored
    loaded = load_plan(tmp_path)
    assert loaded is not None
    assert len(loaded.plan) == 2


@pytest.mark.asyncio
async def test_resume_recovers_reset_plan_from_audit(
    tmp_path: Path,
    example_input: Path,
    fake_agent_bin: str,
) -> None:
    from top_down_planning.input_loader import load_markdown_input, load_output_goal

    output_dir = tmp_path / "planning-output"
    loaded = load_markdown_input(example_input)
    loaded_goal = load_output_goal(inline="Produce an actionable implementation plan")
    limits = PlanningLimits(max_iterations=5, batch_size=2, concurrent_batches=1)

    plan = make_root_plan(
        input_file=str(loaded.path),
        output_goal=loaded_goal.text,
        input_digest=loaded.digest,
        output_goal_digest=loaded_goal.digest,
    )
    response = AgentResponse(
        operations=[
            ExpandOperation(
                node_id="item-001",
                children=[
                    ChildDraft(title="Area A", objective="A"),
                    ChildDraft(title="Area B", objective="B"),
                ],
            )
        ]
    )
    plan = apply_response(plan, response)
    run_state = new_run_state(
        input_file=str(loaded.path),
        output_goal=loaded_goal.source_label,
        input_digest=loaded.digest,
        output_goal_digest=loaded_goal.digest,
        limits=limits,
    )
    run_state.iteration = 1
    run_state.active_status = RunActiveStatus.PAUSED
    run_state.history.append({"event": "iteration_applied", "iteration": 1})

    output_dir.mkdir(parents=True, exist_ok=True)
    save_plan(output_dir, plan)
    save_run_state(output_dir, run_state)
    audit_dir = output_dir / ".planning-output" / "iterations"
    audit_dir.mkdir(parents=True, exist_ok=True)
    (audit_dir / "001-response.json").write_text(
        json.dumps(response.model_dump(mode="json")),
        encoding="utf-8",
    )

    save_plan(
        output_dir,
        make_root_plan(
            input_file=str(loaded.path),
            output_goal=loaded_goal.text,
            input_digest=loaded.digest,
            output_goal_digest=loaded_goal.digest,
        ),
    )

    config = RunConfig(
        input_path=example_input,
        output_goal=loaded_goal,
        output_dir=output_dir,
        workspace_root=tmp_path,
        limits=limits,
        resume=True,
        agent_bin=fake_agent_bin,
        skip_probe=True,
    )
    report = await Orchestrator(config).run()
    recovered = load_plan(output_dir)
    assert recovered is not None
    assert len(recovered.plan) >= 3
    assert report.iterations >= 2
