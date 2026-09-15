"""Incident-shaped production fixture: partial work survives quota pause and resume."""

from __future__ import annotations

from pathlib import Path

from core_tools.provider import StubProvider

from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator import RunEngine
from top_down_planning.orchestrator.apply_resume import apply_resume_plan_atomically
from top_down_planning.orchestrator.phases import PLAN_VALIDATED, PRODUCTION, WHOLE_OUTPUT_REVIEW
from top_down_planning.orchestrator.prepare_resume import prepare_resume
from top_down_planning.persistence import FileRunStore
from tests.helpers import (
    apply_production,
    create_run_kwargs,
    done_events,
    whole_plan_approval_record,
)

INCIDENT_QUOTA_MESSAGE = (
    "Increase limits for faster responses You're out of usage. "
    "Switch to Auto, or ask your admin to increase your limit to continue."
)


def _batch_apply_request(
    *,
    plan_items: list[str],
    dispositions: dict,
    production_revision: int = 0,
) -> dict:
    return {
        "production_revision": production_revision,
        "plan_items": plan_items,
        "dispositions": dispositions,
        "outputs": [],
        "contributions": [],
        "summary": "batch complete",
        "empty_output": False,
        "empty_output_reason": None,
    }


def test_partial_production_work_survives_quota_pause_and_resume(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"
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
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver the feature.",
        items={
            "item-root": root,
            "item-first": first,
            "item-second": second,
        },
    )
    config = {
        "run": {
            "output_goal": "Deliver the feature.",
            "input_refs": ["README.md"],
        },
        "planning": {
            "stop_hint": "Stop when ready.",
            "max_depth": 4,
            "max_expansion_per_item": 7,
        },
        "limits": {
            "production": {
                "max_batches": 50,
                "max_agent_turns_per_batch": 10,
            }
        },
    }
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=config),
        phase=PLAN_VALIDATED,
    )
    store.save_review(run_id, whole_plan_approval_record(store, run_id))

    completed_path = tmp_path / "milestone-one.md"
    partial_path = tmp_path / "milestone-two-partial.md"
    quota_provider = StubProvider()
    quota_provider.script_turn(done_events(text="producer session start"))
    quota_provider.script_turn(
        done_events(signal="batch_complete", text="first milestone"),
        mutate_store=lambda: (
            completed_path.write_text("# milestone one\n", encoding="utf-8"),
            apply_production(
                store,
                run_id,
                _batch_apply_request(
                    plan_items=["item-first"],
                    dispositions={"item-first": {"disposition": "completed"}},
                ),
                handler="apply",
            )(),
        ),
    )
    quota_provider.script_turn(
        [
            {"type": "assistant", "text": "writing second milestone"},
            {"type": "error", "text": INCIDENT_QUOTA_MESSAGE},
        ],
        mutate_store=lambda: partial_path.write_text(
            "# milestone two (partial)\n", encoding="utf-8"
        ),
    )

    paused = RunEngine(
        store, create_provider=lambda _config, _ws: quota_provider
    ).continue_run(run_id, single_step=True)
    run = store.load_run(run_id)
    assert paused.ok is False
    assert run["status"] == "paused"
    assert run["stop"]["code"] == "provider_quota_exhausted"
    assert run["phase"] == PRODUCTION
    production = store.load_production(run_id)
    assert production["dispositions"]["item-first"] == "completed"
    assert "item-second" not in production["dispositions"]
    assert completed_path.read_text(encoding="utf-8") == "# milestone one\n"
    assert (
        partial_path.read_text(encoding="utf-8") == "# milestone two (partial)\n"
    )

    stored = store.load_resolved_config(run_id)
    resume_plan = prepare_resume(store, run_id, stored)
    apply_resume_plan_atomically(
        store,
        resume_plan,
        resolved_config=stored,
        invocation=store.load_invocation(run_id),
    )

    resume_provider = StubProvider()
    resume_provider.script_turn(done_events(text="resume after quota"))
    resume_provider.script_turn(
        done_events(signal="batch_complete", text="second milestone"),
        mutate_store=lambda: (
            partial_path.write_text("# milestone two\n", encoding="utf-8"),
            apply_production(
                store,
                run_id,
                _batch_apply_request(
                    plan_items=["item-second"],
                    dispositions={"item-second": {"disposition": "completed"}},
                    production_revision=1,
                ),
                handler="apply",
            )(),
            apply_production(
                store,
                run_id,
                {"goal_assessment": "Output goal is fully met."},
                handler="submit_completion",
            )(),
        ),
    )
    result = RunEngine(
        store, create_provider=lambda _config, _ws: resume_provider
    ).continue_run(run_id, single_step=True)
    final = store.load_run(run_id)
    production = store.load_production(run_id)
    assert result.ok is True or final["phase"] == WHOLE_OUTPUT_REVIEW
    assert production["dispositions"] == {
        "item-first": "completed",
        "item-second": "completed",
    }
    assert len(production["batches"]) == 2
    assert completed_path.read_text(encoding="utf-8") == "# milestone one\n"
    assert partial_path.read_text(encoding="utf-8") == "# milestone two\n"
    assert final["phase"] == WHOLE_OUTPUT_REVIEW
