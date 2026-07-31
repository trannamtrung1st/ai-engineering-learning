"""Freeze-intent continuation/resume: contracts stay bound; working resources may change."""

from __future__ import annotations

from pathlib import Path

import pytest

from core_tools.persistence import dump_yaml
from core_tools.provider import StubProvider
from top_down_planning.agent_tool import ProductionAgentService
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator import (
    ProductionPhaseOrchestrator,
    ResumeError,
    validate_resume_preconditions,
)
from top_down_planning.orchestrator.phases import PLAN_VALIDATED, PRODUCTION, WHOLE_OUTPUT_REVIEW
from top_down_planning.orchestrator.production import build_producer_context_manifest
from top_down_planning.persistence import FileRunStore
from tests.helpers import (
    apply_production,
    create_run_kwargs,
    done_events,
    grant_capability,
    minimal_resolved_config,
    whole_plan_approval_record,
)


def _batch_request(
    *,
    plan_items: list[str],
    dispositions: dict,
    production_revision: int = 0,
    outputs: list[dict] | None = None,
) -> dict:
    return {
        "production_revision": production_revision,
        "plan_items": plan_items,
        "dispositions": dispositions,
        "outputs": outputs or [],
        "contributions": [],
        "summary": "batch complete",
        "empty_output": not bool(outputs),
        "empty_output_reason": None if outputs else "n/a",
    }


def _create_production_ready_run(
    store: FileRunStore,
    *,
    run_id: str = "run-20260101T009901-009901",
    config: dict | None = None,
) -> None:
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        kind="aggregate",
    )
    leaf = PlanItem(
        id="item-leaf",
        parent_id="item-root",
        order_key="0000000000",
        title="Leaf",
        outcome="Leaf outcome.",
        kind="work",
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver the feature.",
        items={"item-root": root, "item-leaf": leaf},
    )
    resolved = config or minimal_resolved_config(
        run={
            "output_goal": "Deliver the feature.",
            "input_refs": ["task.md"],
        },
        provider={"name": "stub"},
        limits={"production": {"max_batches": 50, "max_agent_turns_per_batch": 10}},
    )
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=resolved),
        phase=PLAN_VALIDATED,
    )
    store.save_review(run_id, whole_plan_approval_record(store, run_id))


def test_continuation_into_whole_output_succeeds_after_working_resource_mutation(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    module = src / "feature.py"
    module.write_text("v1\n", encoding="utf-8")
    (tmp_path / "task.md").write_text("task\n", encoding="utf-8")

    config = minimal_resolved_config(
        run={
            "output_goal": "Deliver the feature.",
            "input_refs": ["task.md"],
        },
        provider={"name": "stub"},
        limits={"production": {"max_batches": 50, "max_agent_turns_per_batch": 10}},
        agent_context={
            "default": {"resources": [], "skills": []},
            "planner": {"resources": [], "skills": []},
            "producer": {"resources": ["src/"], "skills": []},
            "reviewer": {"resources": ["src/"], "skills": []},
        },
    )
    run_id = "run-20260101T009901-009901"
    _create_production_ready_run(store, run_id=run_id, config=config)

    provider = StubProvider()
    provider.script_turn(done_events(text="producer session start"))
    provider.script_turn(
        done_events(signal="batch_complete", text="production turn"),
        mutate_store=lambda: (
            module.write_text("v2-produced\n", encoding="utf-8"),
            apply_production(
                store,
                run_id,
                _batch_request(
                    plan_items=["item-leaf"],
                    dispositions={"item-leaf": {"disposition": "completed"}},
                    outputs=[
                        {
                            "id": "output-feature",
                            "type": "artifact",
                            "ref": "src/feature.py",
                        }
                    ],
                ),
                handler="apply",
            )(),
            apply_production(
                store,
                run_id,
                {"goal_assessment": "Output goal is fully met.", "goal_met": True},
                handler="submit_completion",
            )(),
        ),
    )

    result = ProductionPhaseOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    assert result.phase == WHOLE_OUTPUT_REVIEW
    assert store.load_run(run_id)["phase"] == WHOLE_OUTPUT_REVIEW
    # Next engine continuation / user resume must accept mutated working resources.
    validate_resume_preconditions(store, run_id)

    # Fresh package build still resolves current resource path selection.
    run = store.load_run(run_id)
    package = build_producer_context_manifest(
        run_id,
        run,
        store.load_resolved_config(run_id),
        store.load_plan_model(run_id),
        production=store.load_production(run_id),
    )
    resource_paths = [str(path) for path in package["agent_context"]["resources"]]
    src_root = str(src.resolve())
    assert any(
        path == src_root or path.startswith(src_root + "/")
        for path in resource_paths
    )


def test_multi_batch_working_resource_mutations_then_resume_ok(tmp_path: Path) -> None:
    """§15 mutable-workspace cases: modify/add/delete under configured dirs across batches."""

    store = FileRunStore(tmp_path)
    src = tmp_path / "src"
    tests_dir = tmp_path / "tests"
    src.mkdir()
    tests_dir.mkdir()
    module = src / "feature.py"
    obsolete = src / "obsolete.py"
    module.write_text("v1\n", encoding="utf-8")
    obsolete.write_text("gone-soon\n", encoding="utf-8")
    (tests_dir / ".keep").write_text("keep\n", encoding="utf-8")
    (tmp_path / "task.md").write_text("task\n", encoding="utf-8")

    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        kind="aggregate",
    )
    first = PlanItem(
        id="item-first",
        parent_id="item-root",
        order_key="0000000000",
        title="First",
        outcome="First outcome.",
        kind="work",
    )
    second = PlanItem(
        id="item-second",
        parent_id="item-root",
        order_key="0000000100",
        title="Second",
        outcome="Second outcome.",
        depends_on=["item-first"],
        kind="work",
    )
    plan = Plan(
        id="plan-run-20260101T009904-009904",
        revision=0,
        output_goal="Deliver the feature.",
        items={
            "item-root": root,
            "item-first": first,
            "item-second": second,
        },
    )
    config = minimal_resolved_config(
        run={
            "output_goal": "Deliver the feature.",
            "input_refs": ["task.md"],
        },
        provider={"name": "stub"},
        limits={"production": {"max_batches": 50, "max_agent_turns_per_batch": 10}},
        agent_context={
            "default": {"resources": [], "skills": []},
            "planner": {"resources": [], "skills": []},
            "producer": {"resources": ["src/", "tests/"], "skills": []},
            "reviewer": {"resources": ["src/", "tests/"], "skills": []},
        },
    )
    run_id = "run-20260101T009904-009904"
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=config),
        phase=PLAN_VALIDATED,
    )
    store.save_review(run_id, whole_plan_approval_record(store, run_id))

    provider = StubProvider()
    provider.script_turn(done_events(text="producer session start"))
    provider.script_turn(
        done_events(signal="batch_complete", text="batch 1"),
        mutate_store=lambda: (
            module.write_text("v2\n", encoding="utf-8"),
            obsolete.unlink(),
            apply_production(
                store,
                run_id,
                _batch_request(
                    plan_items=["item-first"],
                    dispositions={"item-first": {"disposition": "completed"}},
                    outputs=[
                        {
                            "id": "output-feature-v2",
                            "type": "artifact",
                            "ref": "src/feature.py",
                        }
                    ],
                ),
                handler="apply",
            )(),
        ),
    )
    provider.script_turn(
        done_events(signal="batch_complete", text="batch 2"),
        mutate_store=lambda: (
            (tests_dir / "test_feature.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8"),
            apply_production(
                store,
                run_id,
                _batch_request(
                    plan_items=["item-second"],
                    dispositions={"item-second": {"disposition": "completed"}},
                    production_revision=1,
                    outputs=[
                        {
                            "id": "output-test-feature",
                            "type": "artifact",
                            "ref": "tests/test_feature.py",
                        }
                    ],
                ),
                handler="apply",
            )(),
            apply_production(
                store,
                run_id,
                {"goal_assessment": "Output goal is fully met.", "goal_met": True},
                handler="submit_completion",
            )(),
        ),
    )

    result = ProductionPhaseOrchestrator(store, run_id, provider).run()
    assert result.ok is True
    assert result.phase == WHOLE_OUTPUT_REVIEW
    assert result.batch_count == 2
    assert not obsolete.exists()
    assert (tests_dir / "test_feature.py").is_file()
    validate_resume_preconditions(store, run_id)


def test_resume_still_rejects_contract_and_context_selection_drift(
    tmp_path: Path,
) -> None:
    import copy

    store = FileRunStore(tmp_path)
    skill_dir = tmp_path / ".agents" / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("skill-a\n", encoding="utf-8")
    goal_file = tmp_path / "goal.md"
    goal_file.write_text("Deliver the feature.\n", encoding="utf-8")
    task = tmp_path / "task.md"
    task.write_text("task-a\n", encoding="utf-8")

    config = minimal_resolved_config(
        run={
            "output_goal_file": "goal.md",
            "input_refs": ["task.md"],
        },
        provider={"name": "stub"},
        agent_context={
            "default": {"resources": [], "skills": [".agents/skills/demo/"]},
            "planner": {"resources": [], "skills": []},
            "producer": {"resources": [], "skills": []},
            "reviewer": {"resources": [], "skills": []},
        },
    )
    # Drop inline goal when using file-backed goal.
    config["run"].pop("output_goal", None)

    run_id = "run-20260101T009902-009902"
    _create_production_ready_run(store, run_id=run_id, config=config)
    run = store.load_run(run_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["phase"] = PRODUCTION
    store.save_run(run_id, run, expected)

    original_resolved = copy.deepcopy(store.load_resolved_config(run_id))
    config_path = tmp_path / run_id / "resolved-config.yaml"

    task.write_text("task-b\n", encoding="utf-8")
    with pytest.raises(ResumeError, match="input digest mismatch"):
        validate_resume_preconditions(store, run_id)
    task.write_text("task-a\n", encoding="utf-8")

    goal_file.write_text("Changed goal content.\n", encoding="utf-8")
    with pytest.raises(ResumeError, match="output goal digest mismatch"):
        validate_resume_preconditions(store, run_id)
    goal_file.write_text("Deliver the feature.\n", encoding="utf-8")

    drifted = copy.deepcopy(original_resolved)
    drifted["planning"]["max_depth"] = 99
    config_path.write_text(dump_yaml(drifted) + "\n", encoding="utf-8")
    with pytest.raises(ResumeError, match="semantic config digest mismatch"):
        validate_resume_preconditions(store, run_id)
    config_path.write_text(dump_yaml(original_resolved) + "\n", encoding="utf-8")

    skill_file.write_text("skill-b\n", encoding="utf-8")
    with pytest.raises(ResumeError, match="context digest mismatch"):
        validate_resume_preconditions(store, run_id)


def test_approved_evidence_snapshot_immutable_under_workspace_change(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    (tmp_path / "task.md").write_text("task\n", encoding="utf-8")
    artifact = tmp_path / "leaf.txt"
    artifact.write_text("captured-v1\n", encoding="utf-8")

    run_id = "run-20260101T009903-009903"
    _create_production_ready_run(store, run_id=run_id)
    run = store.load_run(run_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["phase"] = PRODUCTION
    store.save_run(run_id, run, expected)

    service = ProductionAgentService(store, run_id)
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)
    service.apply(
        _batch_request(
            plan_items=["item-leaf"],
            dispositions={"item-leaf": {"disposition": "completed"}},
            outputs=[{"id": "output-leaf", "type": "artifact", "ref": "leaf.txt"}],
        ),
        capability_token=token,
    )

    production = store.load_production(run_id)
    evidence = production["output_evidence"][0]
    snapshot_ref = evidence["snapshot_ref"]
    parts = Path(snapshot_ref).parts
    snapshot_path = store.artifact_path(run_id, parts[1], parts[2])
    assert snapshot_path.read_text(encoding="utf-8") == "captured-v1\n"

    # Later workspace edits must not rewrite historical evidence.
    artifact.write_text("workspace-v2\n", encoding="utf-8")
    assert snapshot_path.read_text(encoding="utf-8") == "captured-v1\n"
    validate_resume_preconditions(store, run_id)

    # Corrupting the stored snapshot blocks resume.
    snapshot_path.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ResumeError, match="evidence snapshot"):
        validate_resume_preconditions(store, run_id)
