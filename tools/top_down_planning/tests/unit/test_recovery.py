import json
from pathlib import Path

import pytest

from top_down_planning.models import (
    ChildDraft,
    DecompositionStatus,
    ExpandOperation,
    PlanningLimits,
    RunActiveStatus,
    UpdateItemOperation,
)
from top_down_planning.orchestrator import Orchestrator, RunConfig
from top_down_planning.persistence import (
    load_plan,
    load_run_state,
    new_run_state,
    save_plan,
    save_run_state,
)
from top_down_planning.recovery import (
    backup_canonical_plan,
    is_plan_run_state_desynced,
    plan_looks_reset,
    recover_plan_from_iterations,
    restore_canonical_plan,
)
from tests.helpers import default_generation, make_agent_response
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
        generation=default_generation(),
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

    response = make_agent_response(
        operations=[
            ExpandOperation(
                node_id="item-001",
                title="Generated root",
                objective="Describe the requested plan",
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


def test_recover_plan_replays_cross_item_updates(tmp_path: Path) -> None:
    plan = make_root_plan(
        input_file="./idea.md",
        output_goal="goal",
        input_digest="a",
        output_goal_digest="b",
    )
    save_plan(tmp_path, plan)

    first = make_agent_response(
        operations=[
            ExpandOperation(
                node_id="item-001",
                title="Generated root",
                objective="Describe the requested plan",
                children=[ChildDraft(title="Child", objective="child")],
            )
        ]
    )
    second = make_agent_response(
        operations=[
            ExpandOperation(
                node_id="item-002",
                children=[ChildDraft(title="Slice", objective="slice")],
            )
        ],
        updates=[
            UpdateItemOperation(
                node_id="item-001",
                reason="Align parent notes after child expansion.",
                notes=["updated during recovery replay"],
            )
        ],
    )
    audit_dir = tmp_path / ".planning-output" / "iterations"
    audit_dir.mkdir(parents=True)
    (audit_dir / "001-response.json").write_text(
        json.dumps(first.model_dump(mode="json")),
        encoding="utf-8",
    )
    (audit_dir / "002-response.json").write_text(
        json.dumps(second.model_dump(mode="json")),
        encoding="utf-8",
    )

    recovered = recover_plan_from_iterations(tmp_path, plan)
    assert recovered is not None
    parent = recovered.item_by_id("item-001")
    assert parent is not None
    assert parent.notes == ["updated during recovery replay"]


def test_recover_skips_failed_validation_audit(tmp_path: Path) -> None:
    plan = make_root_plan(
        input_file="./idea.md",
        output_goal="goal",
        input_digest="a",
        output_goal_digest="b",
    )
    save_plan(tmp_path, plan)

    good = make_agent_response(
        operations=[
            ExpandOperation(
                node_id="item-001",
                title="Generated root",
                objective="Describe the requested plan",
                children=[ChildDraft(title="Area A", objective="Do A")],
            )
        ]
    )
    bad = make_agent_response(
        operations=[
            ExpandOperation(
                node_id="item-001",
                title="Generated root",
                objective="Describe the requested plan",
                children=[ChildDraft(title="Area B", objective="Do B")],
            )
        ]
    )
    audit_dir = tmp_path / ".planning-output" / "iterations"
    audit_dir.mkdir(parents=True)
    (audit_dir / "001-response.json").write_text(
        json.dumps(good.model_dump(mode="json")),
        encoding="utf-8",
    )
    (audit_dir / "001-validation.json").write_text(
        json.dumps({"errors": []}),
        encoding="utf-8",
    )
    (audit_dir / "002-response.json").write_text(
        json.dumps(bad.model_dump(mode="json")),
        encoding="utf-8",
    )
    (audit_dir / "002-validation.json").write_text(
        json.dumps({"errors": ["cross-batch duplicate title"]}),
        encoding="utf-8",
    )

    recovered = recover_plan_from_iterations(tmp_path, plan)
    assert recovered is not None
    assert len(recovered.plan) == 2


def test_backup_uses_iteration_and_batch_suffix(tmp_path: Path) -> None:
    plan = make_root_plan(
        input_file="./idea.md",
        output_goal="goal",
        input_digest="a",
        output_goal_digest="b",
    )
    save_plan(tmp_path, plan)
    backup = backup_canonical_plan(tmp_path, suffix="002-01")
    assert backup.name == "plan.yaml.bak.002-01"


def test_restore_canonical_plan_after_agent_reset(tmp_path: Path) -> None:
    plan = make_root_plan(
        input_file="./idea.md",
        output_goal="goal",
        input_digest="a",
        output_goal_digest="b",
    )
    plan = apply_response(
        plan,
        make_agent_response(
            operations=[
                ExpandOperation(
                    node_id="item-001",
                    title="Generated root",
                    objective="Describe the requested plan",
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


def test_restore_canonical_plan_when_reset_root_matches_min_items(tmp_path: Path) -> None:
    plan = make_root_plan(
        input_file="./idea.md",
        output_goal="goal",
        input_digest="a",
        output_goal_digest="b",
    )
    plan = apply_response(
        plan,
        make_agent_response(
            operations=[
                ExpandOperation(
                    node_id="item-001",
                    title="Generated root",
                    objective="Describe the requested plan",
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
    reset_plan = load_plan(tmp_path)
    assert reset_plan is not None
    assert plan_looks_reset(reset_plan)

    restored = restore_canonical_plan(tmp_path, backup, min_items=1)
    assert restored
    loaded = load_plan(tmp_path)
    assert loaded is not None
    assert len(loaded.plan) == 2


def test_restore_canonical_plan_when_progressed_plan_reset_to_root(tmp_path: Path) -> None:
    progressed = make_root_plan(
        input_file="./idea.md",
        output_goal="goal",
        input_digest="a",
        output_goal_digest="b",
    )
    progressed = apply_response(
        progressed,
        make_agent_response(
            operations=[
                ExpandOperation(
                    node_id="item-001",
                    title="Generated root",
                    objective="Describe the requested plan",
                    children=[
                        ChildDraft(title="Area A", objective="Do A"),
                        ChildDraft(title="Area B", objective="Do B"),
                        ChildDraft(title="Area C", objective="Do C"),
                    ],
                )
            ]
        ),
    )
    save_plan(tmp_path, progressed)
    backup = backup_canonical_plan(tmp_path, suffix="003-00")

    save_plan(
        tmp_path,
        make_root_plan(
            input_file="./idea.md",
            output_goal="goal",
            input_digest="a",
            output_goal_digest="b",
        ),
    )

    restored = restore_canonical_plan(
        tmp_path,
        backup,
        min_items=len(progressed.plan),
    )
    assert restored
    loaded = load_plan(tmp_path)
    assert loaded is not None
    assert len(loaded.plan) == len(progressed.plan)


def test_restore_skips_when_backup_and_current_match_unexpanded_root(
    tmp_path: Path,
) -> None:
    plan = make_root_plan(
        input_file="./idea.md",
        output_goal="goal",
        input_digest="a",
        output_goal_digest="b",
    )
    save_plan(tmp_path, plan)
    backup = backup_canonical_plan(tmp_path, suffix="001-00")

    restored = restore_canonical_plan(tmp_path, backup, min_items=1)
    assert not restored
    assert not backup.is_file()


@pytest.mark.asyncio
async def test_interrupt_preserves_persisted_plan_progress(
    tmp_path: Path,
    example_input: Path,
) -> None:
    from top_down_planning.errors import UserInterrupted
    from top_down_planning.input_loader import load_markdown_input
    from tests.helpers import render_output_goal

    output_dir = tmp_path / "planning-output"
    loaded = load_markdown_input(example_input)
    loaded_goal = render_output_goal()
    limits = PlanningLimits(max_iterations=5)

    plan = make_root_plan(
        input_file=str(loaded.path),
        output_goal=loaded_goal.text,
        input_digest=loaded.digest,
        output_goal_digest=loaded_goal.digest,
    )
    response = make_agent_response(
        operations=[
            ExpandOperation(
                node_id="item-001",
                title="Generated root",
                objective="Describe the requested plan",
                children=[
                    ChildDraft(title="Area A", objective="A"),
                    ChildDraft(title="Area B", objective="B"),
                ],
            )
        ]
    )
    expanded_plan = apply_response(plan, response)
    run_state = new_run_state(
        input_file=str(loaded.path),
        output_goal=loaded_goal.source_label,
        input_digest=loaded.digest,
        output_goal_digest=loaded_goal.digest,
        limits=limits,
        generation=default_generation(),
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    save_plan(output_dir, plan)
    save_run_state(output_dir, run_state)

    config = RunConfig(
        input_path=example_input,
        output_goal=loaded_goal,
        output_dir=output_dir,
        workspace_root=tmp_path,
        limits=limits,
        resume=True,
        skip_probe=True,
    )
    orchestrator = Orchestrator(config)

    async def _interrupt_after_persisting_wave(loaded, plan, run_state, output_dir):
        save_plan(output_dir, expanded_plan)
        run_state.iteration = 1
        run_state.history.append({"event": "iteration_applied", "iteration": 1})
        save_run_state(output_dir, run_state)
        raise UserInterrupted("cancelled during second wave")

    orchestrator._planning_loop = _interrupt_after_persisting_wave  # type: ignore[method-assign]

    with pytest.raises(UserInterrupted):
        await orchestrator.run()

    persisted = load_plan(output_dir)
    assert persisted is not None
    assert len(persisted.plan) == len(expanded_plan.plan)
    root = persisted.item_by_id("item-001")
    assert root is not None
    assert root.decomposition_status == DecompositionStatus.EXPANDED
    resumed_run = load_run_state(output_dir)
    assert resumed_run is not None
    assert resumed_run.iteration == 1
    assert resumed_run.active_status == RunActiveStatus.PAUSED


@pytest.mark.asyncio
async def test_resume_recovers_reset_plan_from_audit(
    tmp_path: Path,
    example_input: Path,
    fake_agent_bin: str,
) -> None:
    from top_down_planning.input_loader import load_markdown_input
    from tests.helpers import render_output_goal

    output_dir = tmp_path / "planning-output"
    loaded = load_markdown_input(example_input)
    loaded_goal = render_output_goal()
    limits = PlanningLimits(max_iterations=5)

    plan = make_root_plan(
        input_file=str(loaded.path),
        output_goal=loaded_goal.text,
        input_digest=loaded.digest,
        output_goal_digest=loaded_goal.digest,
    )
    response = make_agent_response(
        operations=[
            ExpandOperation(
                node_id="item-001",
                title="Generated root",
                objective="Describe the requested plan",
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
        generation=default_generation(),
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
