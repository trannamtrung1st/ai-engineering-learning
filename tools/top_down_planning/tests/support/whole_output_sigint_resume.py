"""Seed whole-output mandatory review state for OS-process cancel/resume tests."""

from __future__ import annotations

from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.session_bindings import reviewer_binding_for_provider_session
from top_down_planning.orchestrator.phases import WHOLE_OUTPUT_REVIEW
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.digests import compute_output_digest
from tests.helpers import (
    bind_primary_session_for_tests,
    create_run_kwargs,
    ensure_input_ref_files,
    ensure_plan_work_scope_contracts,
    plan_root_item,
    save_review_payload,
    whole_plan_approval_record,
)


def seed_whole_output_revision_in_progress_run(
    store: FileRunStore,
    run_id: str,
    *,
    output_revision: int = 1,
    target_revision: int = 1,
    revision_cycles: int = 1,
    loop_id: str = "review-whole-output-01",
) -> str:
    """Persist a running whole_output_review run in owner-revision resume state."""

    workspace = store.root
    ensure_input_ref_files(workspace, {
        "run": {"input_refs": ["README.md"]},
    })
    root = plan_root_item(
        title="Deliver the feature",
        outcome="Deliver the feature.",
    )
    leaf = PlanItem(
        id="item-leaf",
        parent_id="item-root",
        order_key="0000000000",
        title="Leaf",
        outcome="Leaf outcome.",
        kind="work",
    )
    plan = ensure_plan_work_scope_contracts(
        Plan(
            id=f"plan-{run_id}",
            revision=0,
            output_goal="Deliver the feature.",
            items={"item-root": root, "item-leaf": leaf},
        )
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
            "whole_output_review": {
                "max_revision_cycles": 5,
            }
        },
        "provider": {"name": "stub", "skip_probe": True},
    }
    production = {
        "revision": 2,
        "output_revision": output_revision,
        "batches": [
            {
                "id": "batch-01",
                "plan_items": ["item-leaf"],
                "status": "completed",
                "result": {
                    "outputs": [],
                    "contributions": [],
                    "dispositions": {"item-leaf": {"disposition": "completed"}},
                    "summary": "done",
                    "empty_output": False,
                    "goal_assessment": "",
                },
            }
        ],
        "dispositions": {"item-leaf": "completed"},
        "output_evidence": [],
        "completion_claim": {
            "goal_assessment": "Output goal is fully met.",
            "goal_met": True,
            "summary": "All items complete.",
            "plan_revision": 0,
            "output_revision": output_revision,
            "all_applicable_items_processed": True,
        },
    }
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=config),
        phase=WHOLE_OUTPUT_REVIEW,
        production=production,
    )
    save_review_payload(
        store,
        run_id,
        whole_plan_approval_record(
            store,
            run_id,
            id="review-whole-plan-01",
            reviewer_session_id="stub-session-plan-reviewer",
        ),
    )
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["status"] = "running"
    run["stop"] = None
    run["outcome"] = None
    digests = dict(run.get("digests") or {})
    digests["output"] = compute_output_digest(production)
    run["digests"] = digests
    run["sessions"] = bind_primary_session_for_tests(
        dict(run.get("sessions") or {}),
        role="producer",
        provider_session_id="stub-session-producer-seed",
        config=config,
        workspace=workspace,
        activity="output_revision",
    )
    store.save_run(run_id, run, expected_revision)

    reviewer_binding = reviewer_binding_for_provider_session(
        "stub-session-output-reviewer",
        instance_seed=loop_id,
    )
    save_review_payload(
        store,
        run_id,
        {
            "id": loop_id,
            "type": "whole_output",
            "revise_at": "blocker",
            "target_revision": target_revision,
            "scope": {"kind": "whole_output"},
            "status": "pending",
            "findings": [
                {
                    "id": "finding-01",
                    "severity": "blocker",
                    "category": "correctness",
                    "target_refs": ["item-leaf"],
                    "issue": "Output evidence is missing.",
                    "recommended_change": "Add evidence.",
                    "status": "unresolved",
                }
            ],
            "revision_cycles": revision_cycles,
            "lifecycle_status": "revision_in_progress",
            "active_stage": "finding_verification",
            "finding_set_id": f"{loop_id}-fs-01",
            "verification_result": {"decision": "needs_revision"},
            "pending_revision_cycle_entry": False,
            "reviewer_binding": reviewer_binding.to_dict() if reviewer_binding is not None else None,
            "scope_review_rounds": 0,
            "review_record_schema_version": 2,
            "review_contract_version": 2,
        },
    )
    return loop_id
