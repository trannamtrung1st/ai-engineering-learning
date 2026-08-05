"""Whole-output review orchestration and outcome resolution (proposal §5.3, §11–§12.2, §15, §21)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.config import compute_input_digest, compute_output_goal_digest
from top_down_planning.domain.outcome import (
    evaluate_acceptance_invariant,
    load_approvals_for_acceptance,
    resolve_quality_outcome,
)
from top_down_planning.domain.production import (
    build_output_traceability,
    build_production_review_snapshot,
)
from top_down_planning.domain.review_loop_factory import new_whole_output_review_loop
from top_down_planning.domain.reviews import (
    ReviewLoop,
    build_primary_owner_finding_guidance,
    find_whole_plan_approval,
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
    build_output_analysis_context,
    contract_fields,
    required_audit_passes,
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
from top_down_planning.orchestrator.activity_context import (
    resolve_activity_for_reviewer_stage,
)
from top_down_planning.orchestrator.agent_context import (
    attach_activity_context_to_manifest,
)
from top_down_planning.orchestrator.capability import (
    revoke_capabilities_for_loop,
    revoke_capabilities_for_phase,
)
from top_down_planning.orchestrator.producer_session import primary_producer_provider_session_id
from top_down_planning.orchestrator.reviewer_session import (
    build_reviewer_protocol_instructions,
    build_reviewer_tool_instructions,
    reviewer_loop_provider_session_id,
)
from top_down_planning.orchestrator.errors import ProviderRunError
from top_down_planning.orchestrator.phases import OUTPUT_VALIDATED, WHOLE_OUTPUT_REVIEW
from top_down_planning.orchestrator.provider_turns import (
    build_producer_turn_recovery,
    build_reviewer_turn_recovery,
)
from top_down_planning.agent_tool.config import planning_limits_from_config
from top_down_planning.workspace import run_workspace
from top_down_planning.persistence.digests import (
    compute_config_contract_digest,
    compute_output_digest,
    compute_plan_digest,
)
from top_down_planning.persistence.interface import RunStore
from top_down_planning.persistence.sub_tdp_state import load_sub_tdp_state
from core_tools.provider import Provider

WholeOutputReviewResult = MandatoryWholeReviewResult

_OUTPUT_SPEC = MandatoryWholeReviewSpec(
    review_type="whole_output",
    phase=WHOLE_OUTPUT_REVIEW,
    approved_phase=OUTPUT_VALIDATED,
    owner_role="producer",
    limits_key="whole_output",
    event_prefix="whole_output",
    loop_id_prefix="review-whole-output",
    review_label="whole-output review",
)


class OutputWholeReviewAdapter(MandatoryReviewLoopAdapterMixin):
    """Output-specific mandatory whole-review adapter."""

    def __init__(self, store: RunStore, run_id: str) -> None:
        self._store = store
        self._run_id = run_id
        self._driver: ReviewLoopDriver | None = None

    def bind_driver(self, driver: ReviewLoopDriver) -> None:
        self._driver = driver

    @property
    def _driver_host(self) -> ReviewLoopDriver:
        if self._driver is None:
            raise RuntimeError("OutputWholeReviewAdapter is not bound to a driver")
        return self._driver

    @property
    def spec(self) -> MandatoryWholeReviewSpec:
        return _OUTPUT_SPEC

    def preflight(self, loop: ReviewLoop | None) -> None:
        if loop is None:
            self._require_completion_claim()
            self._require_plan_approval()
            return

    def current_artifact_binding(self) -> tuple[int, str]:
        production = self._store.load_production(self._run_id)
        return int(production["output_revision"]), compute_output_digest(production)

    def new_loop(self, loop_id: str) -> ReviewLoop:
        output_revision = int(
            self._store.load_production(self._run_id)["output_revision"]
        )
        config = self._store.load_resolved_config(self._run_id)
        return new_whole_output_review_loop(
            loop_id=loop_id,
            target_revision=output_revision,
            config=config,
        )

    def build_review_package(
        self,
        run: dict[str, Any],
        config: dict[str, Any],
        loop: ReviewLoop,
    ) -> dict[str, Any]:
        return build_whole_output_review_package(
            self._run_id,
            run,
            config,
            self._store.load_plan_model(self._run_id),
            self._store.load_production(self._run_id),
            loop,
        )

    def primary_owner_session_id(self, run: dict[str, Any]) -> str | None:
        return primary_producer_provider_session_id(run)

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
        request: dict[str, Any] = {
            "action": action,
            "phase": WHOLE_OUTPUT_REVIEW,
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
        if handoff == "revision":
            request["revision_instructions"] = {
                "apply_mode": "evidence_revision",
                "evidence_revision": True,
                "tool": "production_apply",
                "notes": (
                    "Set evidence_revision: true on production apply for terminal "
                    "plan_items targeted by open required findings. Keep existing "
                    "dispositions unchanged; attach new outputs or contributions. "
                    "Then submit-completion with goal_assessment. The orchestrator "
                    "closes the owner revision turn when the completion claim "
                    "persists; stop immediately afterward."
                ),
            }
        return request

    def build_owner_turn_recovery(
        self,
        phase: str,
        append_event: Any,
        model: str | None,
    ) -> Any:
        return build_producer_turn_recovery(
            self._store,
            self._run_id,
            phase=phase,
            expected_next_action="revise output after whole-output review",
            append_event=append_event,
            model=model,
            activity="output_revision",
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
            expected_next_action="continue whole-output reviewer turn",
            append_event=append_event,
            model=model,
            review_package=review_package,
        )

    def after_owner_turn(self, session_id: str) -> None:
        self._sync_output_digest()

    def complete_approval(self, loop: ReviewLoop) -> MandatoryWholeReviewResult:
        plan = self._store.load_plan_model(self._run_id)
        production = self._store.load_production(self._run_id)
        run = self._store.load_run(self._run_id)
        config = self._store.load_resolved_config(self._run_id)
        limits = planning_limits_from_config(config)
        review_limits = mandatory_review_limits_from_config(config, "whole_output")
        current_digest = compute_output_digest(production)

        loop = self._driver_host.reload_loop(loop.id)
        if not mandatory_approval_allowed(
            loop,
            current_artifact_digest=current_digest,
            limits=review_limits,
        ):
            return self._driver_host.terminate(
                "blocked",
                "mandatory whole-output approval invariant not satisfied",
                loop=loop,
            )

        loop = self._driver_host.persist_loop(mark_mandatory_approved(loop))

        reviews = self._store.list_reviews(self._run_id)

        plan_approval, output_approval = load_approvals_for_acceptance(
            reviews,
            plan_revision=plan.revision,
            output_revision=int(production["output_revision"]),
        )
        if output_approval is None:
            return self._driver_host.terminate(
                "blocked",
                "whole-output approval record missing for current output revision",
            )

        invariant, plan_validation, output_validation = evaluate_acceptance_invariant(
            plan=plan,
            production=production,
            reviews=reviews,
            limits=limits,
            plan_approval=plan_approval,
            output_approval=output_approval,
            actual_plan_digest=compute_plan_digest(plan),
            actual_config_contract_digest=compute_config_contract_digest(config),
            actual_output_digest=compute_output_digest(production),
            actual_input_digest=compute_input_digest(
                config,
                base_dir=run_workspace(run),
            ),
            actual_output_goal_digest=compute_output_goal_digest(
                config,
                base_dir=run_workspace(run),
            ),
            actual_context_spec_digest=(run.get("digests") or {}).get("context_spec"),
            actual_context_snapshot_digest=(run.get("digests") or {}).get(
                "context_snapshot"
            ),
        )

        if not plan_validation.ok:
            return self._driver_host.terminate(
                "blocked",
                "deterministic plan validation failed after whole-output approval",
            )

        if not output_validation.ok:
            return self._driver_host.terminate(
                "blocked",
                "deterministic output validation failed after whole-output approval",
            )

        outcome = resolve_quality_outcome(invariant)
        if outcome != "accepted":
            return self._driver_host.terminate(
                outcome,
                "acceptance invariant was not satisfied after whole-output approval",
            )

        expected_revision = int(run["revision"])
        revoke_capabilities_for_loop(self._store, self._run_id, loop.id)
        revoke_capabilities_for_phase(self._store, self._run_id, WHOLE_OUTPUT_REVIEW)
        run = dict(run)
        run["revision"] = expected_revision + 1
        run["phase"] = OUTPUT_VALIDATED
        run["status"] = "completed"
        run["outcome"] = outcome
        self._store.save_run(self._run_id, run, expected_revision)
        self._driver_host.append_event(
            "whole_output_review_approved",
            loop_id=loop.id,
            target_revision=int(production["output_revision"]),
            reviewer_session_id=reviewer_loop_provider_session_id(loop),
            outcome=outcome,
        )
        self._driver_host.append_event(
            "outcome_resolved",
            outcome=outcome,
            acceptance_invariant=invariant.to_dict(),
        )
        run = self._store.load_run(self._run_id)
        return self._driver_host.result_from_run(run, ok=True, loop=loop)

    def _sync_output_digest(self) -> None:
        run = self._store.load_run(self._run_id)
        production = self._store.load_production(self._run_id)
        expected_revision = int(run["revision"])
        run = dict(run)
        run["revision"] = expected_revision + 1
        digests = dict(run.get("digests") or {})
        digests["output"] = compute_output_digest(production)
        run["digests"] = digests
        self._store.save_run(self._run_id, run, expected_revision)

    def _require_completion_claim(self) -> None:
        production = self._store.load_production(self._run_id)
        claim = production.get("completion_claim")
        if not isinstance(claim, dict):
            raise ProviderRunError(
                "whole-output review requires a production completion claim"
            )

    def _require_plan_approval(self) -> None:
        plan = self._store.load_plan_model(self._run_id)
        approval = find_whole_plan_approval(
            self._store.list_reviews(self._run_id),
            plan.revision,
        )
        if approval is None:
            raise ProviderRunError(
                "whole-output review requires an approved whole-plan review "
                "for the current plan revision"
            )


class SubTdpWholeOutputReviewAdapter(OutputWholeReviewAdapter):
    """Whole-output review package enriched with Sub-TDP child evidence."""

    def build_review_package(
        self,
        run: dict[str, Any],
        config: dict[str, Any],
        loop: ReviewLoop,
    ) -> dict[str, Any]:
        package = build_whole_output_review_package(
            self._run_id,
            run,
            config,
            self._store.load_plan_model(self._run_id),
            self._store.load_production(self._run_id),
            loop,
        )
        production = self._store.load_production(self._run_id)
        state = load_sub_tdp_state(production)
        if state is None:
            return package

        workspace = Path(str(run.get("workspace") or ".")).resolve()
        sub_tdp_evidence: list[dict[str, Any]] = []
        integrated_deliverables: list[dict[str, Any]] = []

        for unit_record in state.get("units") or []:
            if not isinstance(unit_record, dict):
                continue
            child_run_id = str(unit_record.get("child_run_id") or "").strip()
            plan_item_id = str(unit_record.get("plan_item_id") or "").strip()
            if not child_run_id:
                continue
            production_ref = f"runs/{child_run_id}/production.json"
            sub_tdp_evidence.append(
                {
                    "child_run_id": child_run_id,
                    "plan_item_id": plan_item_id,
                    "title": unit_record.get("title"),
                    "status": unit_record.get("status"),
                    "production_ref": production_ref,
                    "summary": str(unit_record.get("summary") or ""),
                }
            )
            integrated_deliverables.append(
                {
                    "plan_item_id": plan_item_id,
                    "workspace_path": str(workspace),
                    "child_run_id": child_run_id,
                }
            )

        package["sub_tdp_evidence"] = sub_tdp_evidence
        package["integrated_deliverables"] = integrated_deliverables
        return package


class WholeOutputReviewOrchestrator:
    """Drive mandatory whole-output review and orchestrator-owned final outcomes."""

    def __init__(
        self,
        store: RunStore,
        run_id: str,
        provider: Provider,
    ) -> None:
        production = store.load_production(run_id)
        if load_sub_tdp_state(production) is not None:
            adapter: OutputWholeReviewAdapter | SubTdpWholeOutputReviewAdapter = (
                SubTdpWholeOutputReviewAdapter(store, run_id)
            )
        else:
            adapter = OutputWholeReviewAdapter(store, run_id)
        driver = ReviewLoopDriver(store, run_id, provider, adapter)
        adapter.bind_driver(driver)
        self._driver = driver

    def run(self) -> WholeOutputReviewResult:
        return self._driver.run()


def build_whole_output_review_package(
    run_id: str,
    run: dict[str, Any],
    config: dict[str, Any],
    plan: Any,
    production: dict[str, Any],
    loop: ReviewLoop,
) -> dict[str, Any]:
    """Package a bounded whole-output review for a fresh reviewer session."""

    digests = dict(run.get("digests") or {})
    review_cfg = (config.get("review") or {}).get("whole_output") or {}
    rubric = list(
        review_cfg.get("rubric")
        or DEFAULT_CONFIG["review"]["whole_output"]["rubric"]
    )
    rubric_items = rubric_items_with_ids([str(item) for item in rubric])
    traceability = build_output_traceability(plan, production)
    analysis_context = build_output_analysis_context(
        plan,
        production,
        config,
        stage=loop.active_stage,
        review_type="whole_output",
    )
    output_revision = int(production["output_revision"])
    output_digest = compute_output_digest(production)
    package: dict[str, Any] = {
        "run_id": run_id,
        "phase": WHOLE_OUTPUT_REVIEW,
        "type": "whole_output",
        "loop_id": loop.id,
        "purpose": (
            "Mandatory whole-output fresh scope review before final outcome"
            if loop.active_stage == "scope_review"
            else "Mandatory whole-output review before final outcome"
        ),
        "scope": dict(loop.scope),
        "target_revision": loop.target_revision,
        "target_digest": output_digest,
        "production": build_production_review_snapshot(production),
        "plan_contracts": traceability["plan_contracts"],
        "evidence_by_item": traceability["evidence_by_item"],
        "analysis_context": analysis_context,
        **stage_package_fields(loop),
        **contract_fields(loop),
        "review_budgets": review_gate_budgets_for_package(loop, config),
        "protocol_instructions": build_reviewer_protocol_instructions(
            stage=loop.active_stage or "initial_review",
            review_type=loop.type,
        ),
        "tool_instructions": build_reviewer_tool_instructions(
            run_id,
            review_type=loop.type,
        ),
    }
    if output_revision != loop.target_revision:
        package["output_revision"] = output_revision
    package["rubric_items"] = rubric_items
    package["required_audit_passes"] = list(required_audit_passes("whole_output"))
    if loop.active_stage == "finding_verification":
        package["family_verification_view"] = build_family_verification_view(
            loop,
            artifact_revision=output_revision,
            artifact_digest=output_digest,
        )
    elif loop.lifecycle_status in {
        "findings_open",
        "revision_in_progress",
        "verification_pending",
    }:
        package["active_families"] = build_active_family_view(
            loop,
            artifact_revision=output_revision,
            artifact_digest=output_digest,
        )
    return attach_activity_context_to_manifest(
        package,
        config=config,
        run=run,
        role="reviewer",
        activity=resolve_activity_for_reviewer_stage(loop.active_stage),  # type: ignore[arg-type]
        output_goal=plan.output_goal,
    )
