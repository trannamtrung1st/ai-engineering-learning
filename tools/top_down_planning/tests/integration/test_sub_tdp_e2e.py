"""End-to-end prepared Sub-TDP execution (prepare → execute)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from top_down_planning.orchestrator.phases import OUTPUT_VALIDATED, PLAN_VALIDATED
from top_down_planning.orchestrator.prepared_run_factory import PreparedRunFactory
from top_down_planning.orchestrator.sub_tdp_child_driver import PreparedChildResult
from top_down_planning.package.builder import ExecutionPackageBuilder
from top_down_planning.persistence import FileRunStore
from tests.conftest import run_cli
from tests.helpers import apply_production, done_events
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
        with patch(
            "top_down_planning.orchestrator.execution_runtime.build_provider",
            return_value=provider,
        ):
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
def test_prepared_sub_tdp_e2e_reaches_accepted(
    tmp_path: Path,
    patch_provider: E2EStubProvider,
) -> None:
    config_path = write_e2e_config(tmp_path / "run.yaml")
    runs_dir = tmp_path / "runs"
    store = FileRunStore(runs_dir)
    output_dir = tmp_path / "execution"

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
    planning_run_id = run_result.json()["run_id"]

    script_whole_plan_review(patch_provider, store, planning_run_id, decision="approved")
    plan_review_payload = _resume(planning_run_id, runs_dir)
    assert plan_review_payload["phase"] == PLAN_VALIDATED

    built = ExecutionPackageBuilder().build_from_planning_run(
        store,
        planning_run_id,
        output_dir=output_dir,
    )
    manifest_path = built.manifest_path

    captured_parent: dict[str, str] = {}
    original_create_parent = PreparedRunFactory.create_parent_run
    children_completed = 0
    unit_count_box: dict[str, int] = {"n": len(built.manifest.get("units") or [])}

    def _capture_parent(self, store_arg, package, **kwargs):
        parent_id = original_create_parent(self, store_arg, package, **kwargs)
        captured_parent["id"] = parent_id
        unit_count_box["n"] = len(package.units)
        return parent_id

    def _stub_continue_child(
        child_store: FileRunStore,
        child_run_id: str,
        *,
        create_provider,
        workspace: Path,
        observability=None,
    ) -> PreparedChildResult:
        nonlocal children_completed
        plan = child_store.load_plan_model(child_run_id)
        work_item_ids = [
            item_id
            for item_id, item in plan.items.items()
            if item.kind == "work"
        ]
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
                "plan_items": work_item_ids,
                "dispositions": {
                    item_id: {"disposition": "completed"} for item_id in work_item_ids
                },
                "outputs": [],
                "contributions": [],
                "summary": "batch complete",
            },
            handler="apply",
        )()
        apply_production(
            child_store,
            child_run_id,
            {"goal_assessment": "Child goal met."},
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
        children_completed += 1
        if children_completed >= unit_count_box["n"]:
            parent_id = captured_parent["id"]

            def _integration_mutate() -> None:
                apply_production(
                    store,
                    parent_id,
                    {"goal_assessment": "Parent integration validated; goal met."},
                    handler="submit_completion",
                )()

            queue_turn(
                patch_provider,
                (done_events(signal="batch_complete", text="integration turn"), _integration_mutate),
            )
            script_whole_output_review(
                patch_provider, store, parent_id, decision="approved"
            )
        return PreparedChildResult.from_run(
            child_store.load_run(child_run_id), ok=True
        )

    with (
        patch.object(PreparedRunFactory, "create_parent_run", _capture_parent),
        patch(
            "top_down_planning.orchestrator.prepared_unit_executor.continue_child_sub_tdp",
            side_effect=_stub_continue_child,
        ),
    ):
        execute_result = run_cli(
            [
                "execute",
                "--manifest",
                str(manifest_path),
                "--config",
                str(config_path),
                "--runs-dir",
                str(runs_dir),
                "--stream-json",
            ]
        )
    assert execute_result.exit_code == 0, execute_result.stderr
    payload = execute_result.json()
    assert payload["phase"] == OUTPUT_VALIDATED
    assert payload["ok"] is True
    parent_id = payload["run_id"]
    assert store.load_run(parent_id)["phase"] == OUTPUT_VALIDATED
    assert store.load_run(parent_id)["outcome"] == "accepted"
    claim = store.load_production(parent_id)["completion_claim"]
    assert claim["goal_met"] is True
    assert_acceptance_invariant_for_run(store, parent_id)


@pytest.mark.integration
def test_parent_only_execute_stops_for_attach(tmp_path: Path, patch_provider) -> None:
    config_path = write_e2e_config(tmp_path / "run.yaml")
    runs_dir = tmp_path / "runs"
    store = FileRunStore(runs_dir)
    output_dir = tmp_path / "execution"

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
    planning_run_id = run_result.json()["run_id"]
    script_whole_plan_review(patch_provider, store, planning_run_id, decision="approved")
    _resume(planning_run_id, runs_dir)

    built = ExecutionPackageBuilder().build_from_planning_run(
        store,
        planning_run_id,
        output_dir=output_dir,
    )

    execute_result = run_cli(
        [
            "execute",
            "--manifest",
            str(built.manifest_path),
            "--parent-only",
            "--config",
            str(config_path),
            "--runs-dir",
            str(runs_dir),
            "--stream-json",
        ]
    )
    assert execute_result.exit_code == 0, execute_result.stderr
    payload = execute_result.json()
    assert payload["parent_only"] is True
    assert payload["phase"] == "sub_tdps"
    assert payload["status"] == "paused"
    assert store.load_run(payload["run_id"])["phase"] == "sub_tdps"
    assert store.load_run(payload["run_id"])["status"] == "paused"
