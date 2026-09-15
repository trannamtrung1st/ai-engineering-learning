"""Provider quota exhaustion pauses the run without session replacement."""

from __future__ import annotations

from pathlib import Path

from core_tools.provider import StubProvider
from core_tools.provider.errors import ProviderActionRequiredError

from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.session_recovery_state import (
    replacement_attempted_for_phase_action,
    session_replacement_phase_action_id,
)
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


def _create_run_at_plan_validated(
    store: FileRunStore,
    run_id: str = "run-20260101T000801-000801",
) -> str:
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
    return run_id


def test_engine_pauses_quota_exhaustion_without_session_replacement(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_run_at_plan_validated(store)
    workspace = tmp_path
    completed_file = workspace / "completed-first.md"
    partial_file = workspace / "partial-second.md"
    provider = StubProvider()
    provider.script_turn(done_events(text="producer session start"))
    provider.script_turn(
        done_events(signal="batch_complete", text="first batch"),
        mutate_store=lambda: (
            completed_file.write_text("first item done\n", encoding="utf-8"),
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
    provider.script_turn(
        [
            {"type": "assistant", "text": "starting second item"},
            {"type": "error", "text": INCIDENT_QUOTA_MESSAGE},
        ],
        mutate_store=lambda: partial_file.write_text(
            "partial second item\n", encoding="utf-8"
        ),
    )

    engine = RunEngine(store, create_provider=lambda _config, _ws: provider)
    result = engine.continue_run(run_id, single_step=True)

    run = store.load_run(run_id)
    assert result.ok is False
    assert result.status == "paused"
    assert run["status"] == "paused"
    assert run["phase"] == PRODUCTION
    assert run["stop"]["code"] == "provider_quota_exhausted"
    assert run["stop"]["category"] == "operational"
    assert run["stop"]["details"]["provider_failure"] == "quota_exhausted"
    assert run["stop"]["details"]["replacement_attempted"] is False
    assert run["stop"]["details"]["resume_eligible"] is True
    assert run["stop"]["details"]["domain_committed"] is False
    phase_action_id = str(run["phase_action_id"] or "").strip()
    assert phase_action_id
    assert run["stop"]["details"]["phase_action_id"] == phase_action_id
    assert session_replacement_phase_action_id(run) is None
    assert not replacement_attempted_for_phase_action(run, phase_action_id)
    production = store.load_production(run_id)
    assert production["dispositions"] == {"item-first": "completed"}
    assert len(production["batches"]) == 1
    assert completed_file.read_text(encoding="utf-8") == "first item done\n"
    assert partial_file.read_text(encoding="utf-8") == "partial second item\n"
    events = store.load_events(run_id)
    assert "session_replacement_started" not in {
        str(event.get("type") or "") for event in events
    }
    paused_events = [
        event for event in events if event.get("type") == "provider_action_required"
    ]
    assert paused_events
    assert paused_events[-1]["reason"] == "quota_exhausted"

    again = engine.continue_run(run_id, single_step=True)
    assert again.ok is False
    assert store.load_run(run_id)["stop"]["code"] == "provider_quota_exhausted"
    assert store.load_run(run_id)["revision"] == run["revision"]


def test_resume_after_quota_restoration_completes_without_duplicating_work(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_run_at_plan_validated(store)
    workspace = tmp_path
    completed_file = workspace / "completed-first.md"
    partial_file = workspace / "partial-second.md"
    quota_provider = StubProvider()
    quota_provider.script_turn(done_events(text="producer session start"))
    quota_provider.script_turn(
        done_events(signal="batch_complete", text="first batch"),
        mutate_store=lambda: (
            completed_file.write_text("first item done\n", encoding="utf-8"),
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
            {"type": "assistant", "text": "starting second item"},
            {"type": "error", "text": INCIDENT_QUOTA_MESSAGE},
        ],
        mutate_store=lambda: partial_file.write_text(
            "partial second item\n", encoding="utf-8"
        ),
    )

    paused = RunEngine(
        store, create_provider=lambda _config, _ws: quota_provider
    ).continue_run(run_id, single_step=True)
    assert paused.status == "paused"
    paused_run = store.load_run(run_id)
    preserved_action = paused_run["phase_action_id"]
    producer_session = None
    sessions = paused_run.get("sessions") or {}
    primary = sessions.get("primary_producer") or {}
    producer_session = primary.get("provider_session_id")
    assert producer_session

    stored = store.load_resolved_config(run_id)
    plan = prepare_resume(store, run_id, stored)
    apply_resume_plan_atomically(
        store,
        plan,
        resolved_config=stored,
        invocation=store.load_invocation(run_id),
    )
    resumed_run = store.load_run(run_id)
    assert resumed_run["status"] == "running"
    assert resumed_run["phase"] == PRODUCTION
    assert resumed_run["phase_action_id"] == preserved_action

    resume_provider = StubProvider()
    resume_provider.script_turn(done_events(text="resume producer"))
    resume_provider.script_turn(
        done_events(signal="batch_complete", text="second batch"),
        mutate_store=lambda: (
            partial_file.write_text("second item complete\n", encoding="utf-8"),
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
    assert result.status in {WHOLE_OUTPUT_REVIEW, final["status"]}
    production = store.load_production(run_id)
    assert production["dispositions"] == {
        "item-first": "completed",
        "item-second": "completed",
    }
    assert len(production["batches"]) == 2
    assert production["output_revision"] == 2
    assert completed_file.read_text(encoding="utf-8") == "first item done\n"
    assert "second item complete" in partial_file.read_text(encoding="utf-8")
    resumed_sessions = final.get("sessions") or {}
    resumed_primary = resumed_sessions.get("primary_producer") or {}
    assert resumed_primary.get("provider_session_id") == producer_session


def test_is_recoverable_session_loss_excludes_quota_errors() -> None:
    from top_down_planning.orchestrator.session_recovery import (
        is_recoverable_provider_session_loss,
    )

    exc = ProviderActionRequiredError(
        INCIDENT_QUOTA_MESSAGE,
        reason="quota_exhausted",
        session_id="chat-1",
    )
    assert is_recoverable_provider_session_loss(exc) is False


def test_resume_validator_allows_provider_quota_exhausted_with_phase_action(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_run_at_plan_validated(store)
    run = store.load_run(run_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["status"] = "paused"
    run["phase"] = PRODUCTION
    run["phase_action_id"] = "action-quota-01"
    run["stop"] = {
        "code": "provider_quota_exhausted",
        "category": "operational",
        "phase": PRODUCTION,
        "message": INCIDENT_QUOTA_MESSAGE,
        "details": {
            "phase_action_id": "action-quota-01",
            "domain_committed": False,
            "provider_failure": "quota_exhausted",
            "replacement_attempted": False,
            "resume_eligible": True,
        },
    }
    store.save_run(run_id, run, expected)
    stored = store.load_resolved_config(run_id)
    plan = prepare_resume(store, run_id, stored)
    apply_resume_plan_atomically(
        store,
        plan,
        resolved_config=stored,
        invocation=store.load_invocation(run_id),
    )
    assert store.load_run(run_id)["status"] == "running"
