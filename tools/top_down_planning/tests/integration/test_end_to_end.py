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
from tests.helpers import apply_plan, apply_production, done_events, request_amendment
from tests.integration.e2e_helpers import (
    E2EStubProvider,
    assert_acceptance_invariant_for_run,
    current_plan_revision,
    root_child_item_ids,
    planning_single_leaf_script,
    planning_two_item_script,
    production_batch_script,
    review_respond_script,
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

    patch_provider.script_turn(*planning_single_leaf_script(store))
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

    patch_provider.script_turn(*whole_plan_review_script(store, run_id, decision="approved"))
    plan_review_payload = _resume(run_id, runs_dir)
    assert plan_review_payload["phase"] == PLAN_VALIDATED

    leaf_id = root_child_item_ids(store, run_id)[0]
    patch_provider.script_turn(
        *production_batch_script(
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
    patch_provider.script_turn(*whole_output_review_script(store, run_id, decision="approved"))
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

    patch_provider.script_turn(*planning_single_leaf_script(store))
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

    patch_provider.script_turn(
        *whole_plan_review_script(store, run_id, decision="blocked")
    )
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

    patch_provider.script_turn(*planning_two_item_script(store))
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

    patch_provider.script_turn(*whole_plan_review_script(store, run_id, decision="approved"))
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
            operations=[
                {
                    "op": "add_item",
                    "temp_id": "item-third",
                    "parent_id": "item-root",
                    "placement": {"last_child": True},
                    "item": {
                        "title": "Third",
                        "outcome": "Third outcome.",
                        "acceptance": ["Third is verifiable."],
                    },
                }
            ],
        ),
    )
    amended_revision = current_plan_revision(store, run_id) + 1
    patch_provider.script_turn(
        *review_respond_script(
            store,
            run_id,
            decision="approved",
            loop_id="review-whole-plan-02",
            target_revision=amended_revision,
        )
    )
    amendment_resume = _resume(run_id, runs_dir)
    assert amendment_resume["ok"] is True
    assert amendment_resume["phase"] == WHOLE_OUTPUT_REVIEW

    patch_provider.script_turn(*whole_output_review_script(store, run_id, decision="approved"))
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

    patch_provider.script_turn(*planning_single_leaf_script(store))
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

    patch_provider.script_turn(*whole_plan_review_script(store, run_id, decision="approved"))
    _resume(run_id, runs_dir)

    leaf_id = root_child_item_ids(store, run_id)[0]
    patch_provider.script_turn(
        *production_batch_script(
            store,
            run_id,
            plan_items=[leaf_id],
            dispositions={leaf_id: {"disposition": "completed"}},
            submit_completion=True,
        )
    )
    _resume(run_id, runs_dir)

    production = store.load_production(run_id)
    patch_provider.script_turn(*whole_output_review_script(store, run_id, decision="approved"))
    output_payload = _resume(run_id, runs_dir)
    assert output_payload["outcome"] == "accepted"
    assert_acceptance_invariant_for_run(store, run_id)


@pytest.mark.integration
def test_capability_guardrails_reject_missing_token(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    store = FileRunStore(runs_dir)
    config_path = write_e2e_config(tmp_path / "run.yaml")

    provider = StubProvider()
    provider.script_turn(*planning_single_leaf_script(store))
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
        tmp_path / "plan-apply.json",
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
def test_planning_turn_limit_yields_blocked_not_accepted(
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
    assert payload["outcome"] == "blocked"


@pytest.mark.integration
def test_example_config_and_stub_instructions_are_present(tmp_path: Path) -> None:
    examples_dir = Path(__file__).resolve().parents[2] / "examples"
    example_config = examples_dir / "top-down-planning.yaml"
    readme = Path(__file__).resolve().parents[2] / "README.md"

    assert example_config.exists()
    example_text = example_config.read_text(encoding="utf-8")
    assert "provider:" in example_text
    assert "name: cursor" in example_text

    readme_text = readme.read_text(encoding="utf-8")
    assert "provider.name=stub" in readme_text
    assert "tools/top_down_planning/examples/top-down-planning.yaml" in readme_text

    from top_down_planning.config import resolve_config

    resolved = resolve_config(example_config, ["provider.name=stub", "run.input_refs=[]"])
    assert resolved["provider"]["name"] == "stub"

    runs_dir = tmp_path / "runs"
    store = FileRunStore(runs_dir)
    provider.script_turn(*planning_single_leaf_script(store))
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
