"""Whole-plan review orchestration (proposal §4.3, §5.2, §11, §12.1)."""

from __future__ import annotations

from typing import Any

from top_down_planning.agent_tool.config import planning_limits_from_config
from top_down_planning.agent_tool.views import build_plan_review_snapshot
from top_down_planning.config import compute_input_digest, compute_output_goal_digest
from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.domain.review_loop_factory import new_whole_plan_review_loop
from top_down_planning.domain.reviews import (
    ReviewLoop,
    build_primary_owner_finding_guidance,
    mandatory_review_limits_from_config,
    mandatory_approval_allowed,
    primary_review_resume_fields,
    review_gate_budgets_for_package,
)
from top_down_planning.domain.finding_families import (
    build_active_family_view,
    build_family_verification_view,
)
from top_down_planning.orchestrator.review_analysis_context import (
    build_plan_analysis_context,
    contract_fields,
    rubric_items_with_ids,
)
from top_down_planning.orchestrator.mandatory_review_stages import (
    mark_mandatory_approved,
    stage_package_fields,
)
from top_down_planning.orchestrator.mandatory_whole_review import (
    ReviewLoopDriver,
    MandatoryWholeReviewResult,
    MandatoryWholeReviewSpec,
    OwnerHandoff,
)
from top_down_planning.orchestrator.review_loop_adapter_mandatory import (
    MandatoryReviewLoopAdapterMixin,
)
from top_down_planning.domain.validators import (
    build_plan_approval_validation_context,
    validate_plan,
)
from top_down_planning.orchestrator.agent_context import (
    attach_role_context_to_manifest,
    plan_execution_contract_fields,
)
from top_down_planning.orchestrator.capability import (
    revoke_capabilities_for_loop,
    revoke_capabilities_for_phase,
)
from top_down_planning.orchestrator.planner_session import primary_planner_provider_session_id
from top_down_planning.orchestrator.reviewer_session import (
    build_reviewer_protocol_instructions,
    build_reviewer_tool_instructions,
    reviewer_loop_provider_session_id,
)
from top_down_planning.orchestrator.phases import PLAN_VALIDATED, WHOLE_PLAN_REVIEW
from top_down_planning.orchestrator.provider_turns import (
    build_planner_turn_recovery,
    build_reviewer_turn_recovery,
)
from top_down_planning.workspace import run_workspace
from top_down_planning.persistence.digests import compute_config_contract_digest, compute_plan_digest
from top_down_planning.persistence.interface import RunStore
from core_tools.provider import Provider

WholePlanReviewResult = MandatoryWholeReviewResult

_PLAN_SPEC = MandatoryWholeReviewSpec(
    review_type="whole_plan",
    phase=WHOLE_PLAN_REVIEW,
    approved_phase=PLAN_VALIDATED,
    owner_role="planner",
    limits_key="whole_plan",
    event_prefix="whole_plan",
    loop_id_prefix="review-whole-plan",
    review_label="whole-plan review",
)


class PlanWholeReviewAdapter(MandatoryReviewLoopAdapterMixin):
    """Plan-specific mandatory whole-review adapter."""

    def __init__(self, store: RunStore, run_id: str) -> None:
        self._store = store
        self._run_id = run_id
        self._driver: ReviewLoopDriver | None = None

    def bind_driver(self, driver: ReviewLoopDriver) -> None:
        self._driver = driver

    @property
    def _driver_host(self) -> ReviewLoopDriver:
        if self._driver is None:
            raise RuntimeError("PlanWholeReviewAdapter is not bound to a driver")
        return self._driver

    @property
    def spec(self) -> MandatoryWholeReviewSpec:
        return _PLAN_SPEC

    def preflight(self, loop: ReviewLoop | None) -> None:
        return None

    def current_artifact_binding(self) -> tuple[int, str]:
        plan = self._store.load_plan(self._run_id)
        return int(plan["revision"]), compute_plan_digest(plan)

    def new_loop(self, loop_id: str) -> ReviewLoop:
        plan_revision = int(self._store.load_plan(self._run_id)["revision"])
        config = self._store.load_resolved_config(self._run_id)
        return new_whole_plan_review_loop(
            loop_id=loop_id,
            target_revision=plan_revision,
            config=config,
        )

    def build_review_package(
        self,
        run: dict[str, Any],
        config: dict[str, Any],
        loop: ReviewLoop,
    ) -> dict[str, Any]:
        return build_whole_plan_review_package(
            self._run_id,
            run,
            config,
            self._store.load_plan_model(self._run_id),
            loop,
        )

    def primary_owner_session_id(self, run: dict[str, Any]) -> str | None:
        return primary_planner_provider_session_id(run)

    def build_owner_request(
        self,
        loop: ReviewLoop,
        config: dict[str, Any],
        handoff: OwnerHandoff,
    ) -> dict[str, Any]:
        revision, digest = self.current_artifact_binding()
        action = (
            "address_review_findings"
            if handoff == "revision"
            else "address_optional_findings"
        )
        return {
            "action": action,
            "phase": WHOLE_PLAN_REVIEW,
            "loop_id": loop.id,
            "target_revision": loop.target_revision,
            **primary_review_resume_fields(
                loop,
                config=config,
                artifact_revision=revision,
                artifact_digest=digest,
            ),
            "tool_instructions": {
                "record_actions": (
                    f"tdp agent review record-actions --run {self._run_id} "
                    "--request $TDP_AGENT_REQUESTS_DIR/review-record-actions-<loop>-a01.json"
                ),
                "notes": build_primary_owner_finding_guidance(
                    handoff=handoff,
                    loop=loop,
                    config=config,
                ),
            },
        }

    def build_owner_turn_recovery(
        self,
        phase: str,
        append_event: Any,
        model: str | None,
    ) -> Any:
        return build_planner_turn_recovery(
            self._store,
            self._run_id,
            phase=phase,
            expected_next_action="revise plan after whole-plan review",
            append_event=append_event,
            model=model,
        )

    def build_reviewer_turn_recovery(
        self,
        loop_id: str,
        phase: str,
        append_event: Any,
        model: str | None,
        review_package: dict[str, Any],
    ) -> Any:
        return build_reviewer_turn_recovery(
            self._store,
            self._run_id,
            loop_id=loop_id,
            phase=phase,
            expected_next_action="continue whole-plan reviewer turn",
            append_event=append_event,
            model=model,
            review_package=review_package,
        )

    def after_owner_turn(self, session_id: str) -> None:
        return None

    def complete_approval(self, loop: ReviewLoop) -> MandatoryWholeReviewResult:
        plan = self._store.load_plan_model(self._run_id)
        run = self._store.load_run(self._run_id)
        config = self._store.load_resolved_config(self._run_id)
        limits = planning_limits_from_config(config)
        review_limits = mandatory_review_limits_from_config(config, "whole_plan")
        current_digest = compute_plan_digest(plan)

        loop = self._driver_host.reload_loop(loop.id)
        if not mandatory_approval_allowed(
            loop,
            current_artifact_digest=current_digest,
            limits=review_limits,
        ):
            return self._driver_host.terminate(
                "blocked",
                "mandatory whole-plan approval invariant not satisfied",
                loop=loop,
            )

        loop = self._driver_host.persist_loop(mark_mandatory_approved(loop))

        review_state, digest_bundle = build_plan_approval_validation_context(
            plan=plan,
            approval=loop.to_dict(),
            actual_plan_digest=compute_plan_digest(plan),
            actual_config_contract_digest=compute_config_contract_digest(config),
            actual_input_digest=compute_input_digest(
                config,
                base_dir=run_workspace(run),
            ),
            actual_output_goal_digest=compute_output_goal_digest(
                config,
                base_dir=run_workspace(run),
            ),
            actual_context_spec_digest=(run.get("digests") or {}).get("context_spec"),
        )
        validation = validate_plan(
            plan,
            limits=limits,
            review_state=review_state,
            digests=digest_bundle,
            mode="approval",
            reviews=self._store.list_reviews(self._run_id),
        )
        if not validation.ok:
            return self._driver_host.terminate(
                "blocked",
                "deterministic plan validation failed after whole-plan approval",
            )

        expected_revision = int(run["revision"])
        revoke_capabilities_for_loop(self._store, self._run_id, loop.id)
        revoke_capabilities_for_phase(self._store, self._run_id, WHOLE_PLAN_REVIEW)
        run = dict(run)
        run["revision"] = expected_revision + 1
        run["phase"] = PLAN_VALIDATED
        self._store.save_run(self._run_id, run, expected_revision)
        self._driver_host.append_event(
            "whole_plan_review_approved",
            loop_id=loop.id,
            target_revision=plan.revision,
            reviewer_session_id=reviewer_loop_provider_session_id(loop),
        )
        run = self._store.load_run(self._run_id)
        return self._driver_host.result_from_run(run, ok=True, loop=loop)


class WholePlanReviewOrchestrator:
    """Drive the mandatory whole-plan review loop until approval or terminal failure."""

    def __init__(
        self,
        store: RunStore,
        run_id: str,
        provider: Provider,
    ) -> None:
        adapter = PlanWholeReviewAdapter(store, run_id)
        driver = ReviewLoopDriver(store, run_id, provider, adapter)
        adapter.bind_driver(driver)
        self._driver = driver

    def run(self) -> WholePlanReviewResult:
        return self._driver.run()


def build_whole_plan_review_package(
    run_id: str,
    run: dict[str, Any],
    config: dict[str, Any],
    plan: Any,
    loop: ReviewLoop,
) -> dict[str, Any]:
    """Package a bounded whole-plan review for a fresh reviewer session."""

    digests = dict(run.get("digests") or {})
    limits = planning_limits_from_config(config)
    review_cfg = (config.get("review") or {}).get("whole_plan") or {}
    rubric = list(
        review_cfg.get("rubric")
        or DEFAULT_CONFIG["review"]["whole_plan"]["rubric"]
    )
    rubric_items = rubric_items_with_ids([str(item) for item in rubric])
    analysis_context = build_plan_analysis_context(
        plan,
        config,
        stage=loop.active_stage,
        review_type="whole_plan",
    )
    package: dict[str, Any] = {
        "run_id": run_id,
        "phase": WHOLE_PLAN_REVIEW,
        "type": "whole_plan",
        "loop_id": loop.id,
        "purpose": (
            "Mandatory whole-plan fresh scope review before production"
            if loop.active_stage == "scope_review"
            else "Mandatory whole-plan review before production"
        ),
        "scope": dict(loop.scope),
        "target_revision": loop.target_revision,
        "plan_revision": plan.revision,
        "plan": build_plan_review_snapshot(plan, limits=limits),
        "analysis_context": analysis_context,
        **plan_execution_contract_fields(plan),
        "digests": digests,
        **stage_package_fields(loop),
        **contract_fields(loop),
        "review_budgets": review_gate_budgets_for_package(loop, config),
        "protocol_instructions": build_reviewer_protocol_instructions(
            stage=loop.active_stage or "initial_review",
            review_type=loop.type,
        ),
        "tool_instructions": {
            **build_reviewer_tool_instructions(
                run_id,
                review_type=loop.type,
                plan_snapshot=(
                    f"tdp agent plan snapshot --run {run_id} --view active"
                ),
            ),
        },
    }
    package["rubric_items"] = rubric_items
    package["required_audit_passes"] = analysis_context["audit_passes"]
    if loop.active_stage == "finding_verification":
        package["family_verification_view"] = build_family_verification_view(
            loop,
            artifact_revision=plan.revision,
            artifact_digest=digests.get("plan"),
        )
    elif loop.lifecycle_status in {
        "findings_open",
        "revision_in_progress",
        "verification_pending",
    }:
        package["active_families"] = build_active_family_view(
            loop,
            artifact_revision=plan.revision,
            artifact_digest=digests.get("plan"),
        )
    return attach_role_context_to_manifest(
        package,
        config=config,
        run=run,
        role="reviewer",
        output_goal=plan.output_goal,
    )
