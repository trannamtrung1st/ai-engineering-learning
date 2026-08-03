"""End-to-end lifecycle tests under the stub provider (todo 17)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from top_down_planning.orchestrator.phases import (
    OUTPUT_VALIDATED,
    PLAN_VALIDATED,
    WHOLE_OUTPUT_REVIEW,
    WHOLE_PLAN_REVIEW,
)
from top_down_planning.persistence import FileRunStore
from core_tools.provider import StubProvider
from tests.conftest import run_cli
from tests.helpers import apply_plan, apply_production, done_events, request_amendment, save_review_payload, make_review_loop, with_root_contract, work_item_payload
from tests.integration.e2e_helpers import (
    E2EStubProvider,
    assert_acceptance_invariant_for_run,
    current_plan_revision,
    root_child_item_ids,
    planning_single_leaf_script,
    planning_two_item_script,
    production_batch_script,
    review_respond_script,
    queue_turn,
    script_whole_output_review,
    script_whole_plan_review,
    whole_output_review_script,
    whole_plan_review_script,
    write_agent_request,
    write_e2e_config,
)


@pytest.fixture
def provider() -> E2EStubProvider:
    return E2EStubProvider()


@pytest.fixture
def patch_provider(provider: E2EStubProvider):
    with patch("top_down_planning.cli.user.create_provider", return_value=provider):
        yield provider


def _resume(run_id: str, runs_dir: Path) -> dict:
    result = run_cli(
        [
            "resume",
            "--run",
            run_id,
            "--runs-dir",
            str(runs_dir),
            "--stream-json",
        ]
    )
    assert result.exit_code == 0, result.stderr
    return result.json()


@pytest.mark.integration
def test_happy_path_lifecycle_reaches_accepted(
    tmp_path: Path,
    patch_provider: E2EStubProvider,
) -> None:
    config_path = write_e2e_config(tmp_path / "run.yaml")
    runs_dir = tmp_path / "runs"
    store = FileRunStore(runs_dir)

    queue_turn(patch_provider, planning_single_leaf_script(store))
    run_result = run_cli(
        [
            "run",
            "--config",
            str(config_path),
            "--runs-dir",
            str(runs_dir),
            "--stream-json",
        ]
    )
    assert run_result.exit_code == 0, run_result.stderr
    run_payload = run_result.json()
    assert run_payload["ok"] is True
    assert run_payload["phase"] == WHOLE_PLAN_REVIEW
    run_id = run_payload["run_id"]

    script_whole_plan_review(patch_provider, store, run_id, decision="approved")
    plan_review_payload = _resume(run_id, runs_dir)
    assert plan_review_payload["phase"] == PLAN_VALIDATED

    leaf_id = root_child_item_ids(store, run_id)[0]
    queue_turn(patch_provider, production_batch_script(
            store,
            run_id,
            plan_items=[leaf_id],
            dispositions={leaf_id: {"disposition": "completed"}},
            submit_completion=True,
        )
    )
    production_payload = _resume(run_id, runs_dir)
    assert production_payload["phase"] == WHOLE_OUTPUT_REVIEW

    production = store.load_production(run_id)
    script_whole_output_review(patch_provider, store, run_id, decision="approved")
    output_payload = _resume(run_id, runs_dir)
    assert output_payload["ok"] is True
    assert output_payload["phase"] == OUTPUT_VALIDATED
    assert output_payload["outcome"] == "accepted"

    assert_acceptance_invariant_for_run(store, run_id)


@pytest.mark.integration
def test_whole_plan_blocked_does_not_accept(
    tmp_path: Path,
    patch_provider: E2EStubProvider,
) -> None:
    config_path = write_e2e_config(tmp_path / "run.yaml")
    runs_dir = tmp_path / "runs"
    store = FileRunStore(runs_dir)

    queue_turn(patch_provider, planning_single_leaf_script(store))
    run_result = run_cli(
        [
            "run",
            "--config",
            str(config_path),
            "--runs-dir",
            str(runs_dir),
            "--stream-json",
        ]
    )
    run_id = run_result.json()["run_id"]

    script_whole_plan_review(patch_provider, store, run_id, decision="blocked")
    resume_result = run_cli(
        [
            "resume",
            "--run",
            run_id,
            "--runs-dir",
            str(runs_dir),
            "--stream-json",
        ]
    )
    assert resume_result.exit_code == 1
    payload = resume_result.json()
    assert payload["ok"] is False
    assert payload["outcome"] == "blocked"


@pytest.mark.integration
def test_amendment_mid_production_finishes_accepted(
    tmp_path: Path,
    patch_provider: E2EStubProvider,
) -> None:
    config_path = write_e2e_config(tmp_path / "run.yaml")
    runs_dir = tmp_path / "runs"
    store = FileRunStore(runs_dir)

    queue_turn(patch_provider, planning_two_item_script(store))
    run_id = run_cli(
        [
            "run",
            "--config",
            str(config_path),
            "--runs-dir",
            str(runs_dir),
            "--stream-json",
        ]
    ).json()["run_id"]

    script_whole_plan_review(patch_provider, store, run_id, decision="approved")
    _resume(run_id, runs_dir)

    first_id, second_id = root_child_item_ids(store, run_id)

    def remaining_production_turn(_session_id: str) -> list[dict[str, Any]]:
        new_item_id = next(
            item_id
            for item_id in root_child_item_ids(store, run_id)
            if item_id not in {first_id, second_id}
        )
        production = store.load_production(run_id)
        apply_production(
            store,
            run_id,
            {
                "production_revision": int(production["revision"]),
                "plan_items": [second_id, new_item_id],
                "dispositions": {
                    second_id: {"disposition": "completed"},
                    new_item_id: {"disposition": "completed"},
                },
                "outputs": [],
                "contributions": [],
                "summary": "batch complete",
            },
            handler="apply",
        )()
        apply_production(
            store,
            run_id,
            {"goal_assessment": "Output goal is fully met.", "goal_met": True},
            handler="submit_completion",
        )()
        return done_events(signal="batch_complete", text="production turn")

    patch_provider.set_fallback_builder(remaining_production_turn)
    patch_provider.script_turn(
        done_events(signal="batch_complete", text="production turn"),
        mutate_store=lambda: (
            apply_production(
                store,
                run_id,
                {
                    "production_revision": 0,
                    "plan_items": [first_id],
                    "dispositions": {first_id: {"disposition": "completed"}},
                    "outputs": [],
                    "contributions": [],
                    "summary": "batch complete",
                },
                handler="apply",
            )(),
            request_amendment(
                store,
                run_id,
                {
                    "evidence": "Missing API branch in approved plan.",
                    "affected_refs": ["item-root"],
                    "summary": "Need API subtree.",
                },
            )(),
        ),
    )
    patch_provider.script_turn(
        done_events(signal="amendment_revision_ready", text="amendment turn"),
        mutate_store=apply_plan(
            store,
            run_id,
            base_revision=current_plan_revision(store, run_id),
            operations=with_root_contract(
                [
                    {
                        "op": "add_item",
                        "temp_id": "item-third",
                        "parent_id": "item-root",
                        "placement": {"last_child": True},
                        "item": work_item_payload(
                            title="Third",
                            outcome="Third outcome.",
                            acceptance=["Third is verifiable."],
                        ),
                    }
                ]
            ),
            phase="plan_amendment",
        ),
    )
    script_whole_plan_review(
        patch_provider,
        store,
        run_id,
        decision="approved",
        loop_id="review-whole-plan-02",
    )
    amendment_resume = _resume(run_id, runs_dir)
    assert amendment_resume["ok"] is True
    assert amendment_resume["phase"] == WHOLE_OUTPUT_REVIEW

    script_whole_output_review(patch_provider, store, run_id, decision="approved")
    output_payload = _resume(run_id, runs_dir)
    assert output_payload["outcome"] == "accepted"

    production = store.load_production(run_id)
    assert production["dispositions"][first_id] == "completed"
    assert production["reconciliation_reports"]
    assert_acceptance_invariant_for_run(store, run_id)


@pytest.mark.integration
def test_checkpoint_resume_from_whole_plan_review_reaches_accepted(
    tmp_path: Path,
    patch_provider: E2EStubProvider,
) -> None:
    """`tdp run` stops at whole-plan review; phased `tdp resume` completes the run."""

    config_path = write_e2e_config(tmp_path / "run.yaml")
    runs_dir = tmp_path / "runs"
    store = FileRunStore(runs_dir)

    queue_turn(patch_provider, planning_single_leaf_script(store))
    run_payload = run_cli(
        [
            "run",
            "--config",
            str(config_path),
            "--runs-dir",
            str(runs_dir),
            "--stream-json",
        ]
    ).json()
    run_id = run_payload["run_id"]
    assert run_payload["phase"] == WHOLE_PLAN_REVIEW

    status_before = run_cli(
        [
            "status",
            "--run",
            run_id,
            "--runs-dir",
            str(runs_dir),
            "--stream-json",
        ]
    ).json()
    assert status_before["run"]["phase"] == WHOLE_PLAN_REVIEW
    assert status_before["run"]["outcome"] is None

    script_whole_plan_review(patch_provider, store, run_id, decision="approved")
    _resume(run_id, runs_dir)

    leaf_id = root_child_item_ids(store, run_id)[0]
    queue_turn(patch_provider, production_batch_script(
            store,
            run_id,
            plan_items=[leaf_id],
            dispositions={leaf_id: {"disposition": "completed"}},
            submit_completion=True,
        )
    )
    _resume(run_id, runs_dir)

    production = store.load_production(run_id)
    script_whole_output_review(patch_provider, store, run_id, decision="approved")
    output_payload = _resume(run_id, runs_dir)
    assert output_payload["outcome"] == "accepted"
    assert_acceptance_invariant_for_run(store, run_id)


@pytest.mark.integration
def test_capability_guardrails_reject_missing_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TDP_CAPABILITY_TOKEN", raising=False)
    runs_dir = tmp_path / "runs"
    store = FileRunStore(runs_dir)
    config_path = write_e2e_config(tmp_path / "run.yaml")

    provider = StubProvider()
    queue_turn(provider, planning_single_leaf_script(store))
    with patch("top_down_planning.cli.user.create_provider", return_value=provider):
        run_id = run_cli(
            [
                "run",
                "--config",
                str(config_path),
                "--runs-dir",
                str(runs_dir),
                "--stream-json",
            ]
        ).json()["run_id"]

    request_path = write_agent_request(
        store.agent_requests_dir(run_id) / "plan-apply.json",
        {"base_revision": 0, "operations": []},
    )
    denied_result = run_cli(
        [
            "agent",
            "plan",
            "apply",
            "--run",
            run_id,
            "--runs-dir",
            str(runs_dir),
            "--request",
            str(request_path),
        ]
    )
    assert denied_result.exit_code == 1
    denied_payload = denied_result.json()
    assert denied_payload["ok"] is False
    assert denied_payload["error"]["code"] == "capability_denied"


@pytest.mark.integration
def test_planning_turn_limit_yields_paused_not_accepted(
    tmp_path: Path,
    patch_provider: E2EStubProvider,
) -> None:
    config_path = write_e2e_config(
        tmp_path / "run.yaml",
        limits={"planning": {"max_agent_turns": 1}},
    )
    runs_dir = tmp_path / "runs"

    patch_provider.script_turn(done_events(signal="continue", text="planning turn"))
    run_result = run_cli(
        [
            "run",
            "--config",
            str(config_path),
            "--runs-dir",
            str(runs_dir),
            "--stream-json",
        ]
    )
    assert run_result.exit_code == 1
    payload = run_result.json()
    assert payload["ok"] is False
    assert payload["outcome"] is None
    assert payload.get("status") == "paused"


@pytest.mark.integration
def test_example_config_and_stub_instructions_are_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    examples_dir = Path(__file__).resolve().parents[2] / "examples"
    example_config = examples_dir / "top-down-planning.yaml"
    readme = Path(__file__).resolve().parents[2] / "README.md"
    repo_root = Path(__file__).resolve().parents[4]

    assert example_config.exists()
    example_text = example_config.read_text(encoding="utf-8")
    assert "provider:" in example_text
    assert "name: cursor" in example_text
    assert "bundled_skills" in example_text or "auto-injected" in example_text

    readme_text = readme.read_text(encoding="utf-8")
    assert "tests default to `stub`" in readme_text
    assert "tools/top_down_planning/examples/top-down-planning.yaml" in readme_text

    from top_down_planning.config import resolve_config

    monkeypatch.chdir(repo_root)
    resolved = resolve_config(example_config, ["provider.name=stub", "run.input_refs=[]"])
    assert resolved["provider"]["name"] == "stub"

    runs_dir = tmp_path / "runs"
    store = FileRunStore(runs_dir)
    provider = E2EStubProvider()
    queue_turn(provider, planning_single_leaf_script(store))
    with patch("top_down_planning.cli.user.create_provider", return_value=provider):
        result = run_cli(
            [
                "run",
                "--config",
                str(example_config),
                "--set",
                "provider.name=stub",
                "--set",
                "run.input_refs=[]",
                "--runs-dir",
                str(runs_dir),
                "--stream-json",
            ]
        )

    assert result.exit_code == 0, result.stderr
    assert result.json()["phase"] == WHOLE_PLAN_REVIEW


@pytest.mark.integration
def test_enhancement_scenarios_multi_batch_traceability_and_focused_revision(
    tmp_path: Path,
) -> None:
    """Cover multi-batch production, shared artifacts, focused revision, and traceability."""

    from top_down_planning.agent_tool import ProductionAgentService
    from top_down_planning.domain.models import Plan, PlanItem
    from top_down_planning.domain.production import build_output_traceability
    from top_down_planning.domain.readiness import compute_ready_view, resolve_satisfaction
    from top_down_planning.orchestrator.phases import PRODUCTION
    from top_down_planning.orchestrator.whole_output_review import (
        build_whole_output_review_package,
    )
    from top_down_planning.domain.reviews import ReviewLoop
    from tests.helpers import create_run_kwargs, grant_capability, whole_plan_approval_record

    store = FileRunStore(tmp_path / "runs")
    docs = PlanItem(
        id="item-docs",
        parent_id=None,
        order_key="0000000000",
        title="Documentation",
        kind="aggregate",
        outcome="Docs complete.",
    )
    concepts = PlanItem(
        id="item-concepts",
        parent_id="item-docs",
        order_key="0000000000",
        title="Concepts",
        kind="work",
        outcome="Concepts written.",
        acceptance=["Concepts file exists"],
    )
    architecture = PlanItem(
        id="item-architecture",
        parent_id="item-docs",
        order_key="0000000100",
        title="Architecture",
        kind="work",
        outcome="Architecture written.",
        acceptance=["Architecture file exists"],
    )
    plan = Plan(
        id="plan-enh",
        revision=0,
        output_goal="Ship docs.",
        items={
            "item-docs": docs,
            "item-concepts": concepts,
            "item-architecture": architecture,
        },
    )
    store.create_run(
        "run-20260101T001001-001001",
        plan=plan,
        **create_run_kwargs(store.root),
        phase=PRODUCTION,
    )
    save_review_payload(store, "run-20260101T001001-001001",
        whole_plan_approval_record(store, "run-20260101T001001-001001"),
    )
    (store.root / "concepts.md").write_text("concepts", encoding="utf-8")
    (store.root / "architecture.md").write_text("architecture", encoding="utf-8")
    (store.root / "shared.md").write_text("shared", encoding="utf-8")

    ready = compute_ready_view(plan)
    assert "item-docs" not in ready.ready_item_ids
    assert set(ready.ready_item_ids) == {"item-concepts", "item-architecture"}

    service = ProductionAgentService(store, "run-20260101T001001-001001")
    token = grant_capability(
        store, "run-20260101T001001-001001", role="producer", phase=PRODUCTION
    )
    first = service.apply(
        {
            "production_revision": 0,
            "plan_items": ["item-concepts", "item-architecture"],
            "dispositions": {
                "item-concepts": {"disposition": "completed", "evidence": "concepts"},
                "item-architecture": {
                    "disposition": "completed",
                    "evidence": "architecture",
                },
            },
            "outputs": [
                {"id": "output-concepts", "type": "artifact", "ref": "concepts.md"},
                {"id": "output-arch", "type": "artifact", "ref": "architecture.md"},
                {"id": "output-shared", "type": "artifact", "ref": "shared.md"},
            ],
            "contributions": [
                {
                    "item_id": "item-concepts",
                    "output_refs": ["output-concepts", "output-shared"],
                    "summary": "concepts batch",
                },
                {
                    "item_id": "item-architecture",
                    "output_refs": ["output-arch", "output-shared"],
                    "summary": "architecture batch",
                },
            ],
            "summary": "multi-item batch with shared artifact",
        },
        capability_token=token,
    )
    assert first["ok"] is True
    assert resolve_satisfaction(
        store.load_plan_model("run-20260101T001001-001001"),
        "item-docs",
        store.load_production("run-20260101T001001-001001")["dispositions"],
    ).state == "satisfied"

    save_review_payload(store, "run-20260101T001001-001001", {
            "id": "review-focused-output-01",
            "type": "focused_output",
            "revise_at": "blocker",
            "reviewer_session_id": "stub-session-reviewer",
            "target_revision": 1,
            "scope": {"kind": "focused_output", "item_ids": ["item-concepts"]},
            "status": "changes_requested",
            "findings": [
                {
                    "id": "finding-01",
                    "severity": "blocker",
                    "category": "other",
                    "target_refs": ["item-concepts"],
                    "issue": "Need clearer concepts.",
                    "recommended_change": "Revise concepts.md",
                    "status": "unresolved",
                }
            ],
            "revision_cycles": 1,
        },
    )
    (store.root / "concepts-v2.md").write_text("concepts v2", encoding="utf-8")
    token = grant_capability(
        store, "run-20260101T001001-001001", role="producer", phase=PRODUCTION
    )
    revised = service.apply(
        {
            "production_revision": first["production_revision"],
            "evidence_revision": True,
            "focused_review_loop_id": "review-focused-output-01",
            "plan_items": ["item-concepts"],
            "dispositions": {
                "item-concepts": {"disposition": "completed", "evidence": "revised"}
            },
            "outputs": [
                {"id": "output-concepts-v2", "type": "artifact", "ref": "concepts-v2.md"}
            ],
            "contributions": [
                {
                    "item_id": "item-concepts",
                    "output_refs": ["output-concepts-v2"],
                    "summary": "focused revision",
                }
            ],
            "summary": "addressed focused finding",
        },
        capability_token=token,
    )
    assert revised["ok"] is True
    production = store.load_production("run-20260101T001001-001001")
    assert production["output_revision"] == 2
    assert production["completion_claim"] is None

    trace = build_output_traceability(
        store.load_plan_model("run-20260101T001001-001001"),
        production,
    )
    assert "item-concepts" in trace["plan_contracts"]
    assert "item-docs" in trace["plan_contracts"]
    shared = [
        e
        for entries in trace["evidence_by_item"].values()
        for e in entries
        if e["evidence_id"] == "output-shared"
    ]
    assert len(shared) == 2

    package = build_whole_output_review_package(
        "run-20260101T001001-001001",
        store.load_run("run-20260101T001001-001001"),
        store.load_resolved_config("run-20260101T001001-001001"),
        store.load_plan_model("run-20260101T001001-001001"),
        production,
        make_review_loop(
            id="review-whole-output-01",
            type="whole_output",
            reviewer_session_id="sess",
            target_revision=2,
            scope={"kind": "whole_output"},
        ),
    )
    assert package["plan_contracts"]["item-architecture"]["acceptance"]
    assert "output-concepts-v2" in [
        e["evidence_id"] for e in package["evidence_by_item"].get("item-concepts", [])
    ]