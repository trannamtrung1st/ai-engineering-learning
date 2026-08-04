"""End-to-end Sub-TDP execution mode integration test."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from top_down_planning.orchestrator.phases import (
    OUTPUT_VALIDATED,
    PLAN_VALIDATED,
    WHOLE_OUTPUT_REVIEW,
    WHOLE_PLAN_REVIEW,
)
from top_down_planning.persistence import FileRunStore
from tests.conftest import run_cli
from tests.helpers import apply_production
from tests.integration.e2e_helpers import (
    E2EStubProvider,
    assert_acceptance_invariant_for_run,
    planning_two_item_script,
    queue_turn,
    script_whole_output_review,
    script_whole_plan_review,
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
def test_sub_tdps_e2e_reaches_accepted(
    tmp_path: Path,
    patch_provider: E2EStubProvider,
) -> None:
    config_path = write_e2e_config(tmp_path / "run.yaml")
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + "\nexecution:\n  mode: sub_tdps\n",
        encoding="utf-8",
    )
    runs_dir = tmp_path / "runs"
    store = FileRunStore(runs_dir)

    queue_turn(patch_provider, planning_two_item_script(store))
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
    run_id = run_result.json()["run_id"]
    assert run_result.json()["phase"] == WHOLE_PLAN_REVIEW

    script_whole_plan_review(patch_provider, store, run_id, decision="approved")
    plan_review_payload = _resume(run_id, runs_dir)
    assert plan_review_payload["phase"] == PLAN_VALIDATED

    def _stub_continue_child(
        child_store: FileRunStore,
        child_run_id: str,
        *,
        create_provider,
        workspace: Path,
    ) -> dict:
        plan = child_store.load_plan_model(child_run_id)
        plan_item_id = next(
            item_id
            for item_id, item in plan.items.items()
            if item_id != "item-root" and item.kind == "work"
        )
        run = child_store.load_run(child_run_id)
        expected = int(run["revision"])
        run = dict(run)
        run["revision"] = expected + 1
        run["phase"] = "production"
        child_store.save_run(child_run_id, run, expected)
        apply_production(
            child_store,
            child_run_id,
            {
                "production_revision": int(
                    child_store.load_production(child_run_id)["revision"]
                ),
                "plan_items": [plan_item_id],
                "dispositions": {plan_item_id: {"disposition": "completed"}},
                "outputs": [],
                "contributions": [],
                "summary": "batch complete",
            },
            handler="apply",
        )()
        apply_production(
            child_store,
            child_run_id,
            {"goal_assessment": f"{plan_item_id} delivered."},
            handler="submit_completion",
        )()
        run = child_store.load_run(child_run_id)
        expected = int(run["revision"])
        run = dict(run)
        run["revision"] = expected + 1
        run["status"] = "completed"
        run["phase"] = "output_validated"
        run["outcome"] = "accepted"
        run["stop"] = None
        child_store.save_run(child_run_id, run, expected)
        return child_store.load_run(child_run_id)

    with patch(
        "top_down_planning.orchestrator.sub_tdps.continue_child_sub_tdp",
        side_effect=_stub_continue_child,
    ):
        sub_tdps_payload = _resume(run_id, runs_dir)
    assert sub_tdps_payload["phase"] == WHOLE_OUTPUT_REVIEW

    from top_down_planning.orchestrator import WholeOutputReviewOrchestrator

    script_whole_output_review(patch_provider, store, run_id, decision="approved")
    review_result = WholeOutputReviewOrchestrator(
        store,
        run_id,
        patch_provider,
    ).run()
    assert review_result.ok is True
    output_payload = store.load_run(run_id)
    assert output_payload["phase"] == OUTPUT_VALIDATED
    assert output_payload["outcome"] == "accepted"
    assert_acceptance_invariant_for_run(store, run_id)
