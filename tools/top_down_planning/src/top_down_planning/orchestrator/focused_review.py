"""Optional focused plan/output review loops (proposal §4.3, §5.1, §11)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from top_down_planning.agent_tool.config import planning_limits_from_config
from top_down_planning.agent_tool.views import build_plan_review_snapshot
from top_down_planning.domain.finding_families import build_active_family_view
from top_down_planning.domain.production import (
    build_output_traceability,
    build_production_review_snapshot,
)
from top_down_planning.domain.reviews import (
    ReviewLoop,
    build_active_findings_view,
    build_primary_owner_finding_guidance,
    focused_review_revision_limit_from_config,
    primary_review_resume_fields,
    reviewer_package_policy_guidance,
    loop_uses_finding_families,
    review_gate_budgets_for_package,
)
from top_down_planning.orchestrator.agent_context import (
    attach_role_context_to_manifest,
    plan_execution_contract_fields,
)
from top_down_planning.orchestrator.capability import revoke_capabilities_for_loop
from top_down_planning.orchestrator.errors import ProviderRunError
from top_down_planning.orchestrator.mandatory_review_stages import (
    _focused_verification_package_fields,
    prepare_focused_verification_recheck,
)
from top_down_planning.orchestrator.mandatory_whole_review import (
    MandatoryWholeReviewResult,
    OwnerHandoff,
)
from top_down_planning.orchestrator.phases import PLANNING, PRODUCTION
from top_down_planning.orchestrator.planner_session import primary_planner_provider_session_id
from top_down_planning.orchestrator.producer_session import primary_producer_provider_session_id
from top_down_planning.orchestrator.provider_turns import (
    build_planner_turn_recovery,
    build_producer_turn_recovery,
    build_reviewer_turn_recovery,
)
from top_down_planning.orchestrator.reviewer_session import (
    build_reviewer_protocol_instructions,
    build_reviewer_tool_instructions,
    reviewer_loop_provider_session_id,
)
from top_down_planning.orchestrator.review_loop_driver import ReviewLoopDriver
from top_down_planning.orchestrator.review_loop_profile import FOCUSED_PROFILE
from top_down_planning.orchestrator.review_loop_types import MandatoryWholeReviewSpec
from top_down_planning.orchestrator.run_transitions import pause_for_limit_exhausted
from top_down_planning.persistence.digests import compute_output_digest, compute_plan_digest
from top_down_planning.persistence.interface import RunStore
from top_down_planning.persistence.review_commit import (
    review_record_revision,
    save_review_with_expected_revision,
)
from core_tools.provider import Provider


@dataclass(frozen=True)
class FocusedReviewResult:
    ok: bool
    loop_id: str
    status: str
    reviewer_session_id: str | None
    revision_cycles: int
    reason: str | None = None


def _focused_spec(loop: ReviewLoop) -> MandatoryWholeReviewSpec:
    if loop.type == "focused_plan":
        return MandatoryWholeReviewSpec(
            review_type="focused_plan",
            phase=PLANNING,
            approved_phase=PLANNING,
            owner_role="planner",
            limits_key="focused_plan",
            event_prefix="focused_review",
            loop_id_prefix="review-focused-plan",
            review_label="focused plan review",
        )
    return MandatoryWholeReviewSpec(
        review_type="focused_output",
        phase=PRODUCTION,
        approved_phase=PRODUCTION,
        owner_role="producer",
        limits_key="focused_output",
        event_prefix="focused_review",
        loop_id_prefix="review-focused-output",
        review_label="focused output review",
    )


class FocusedReviewAdapter:
    """Focused-review adapter for the shared review-loop driver."""

    def __init__(self, store: RunStore, run_id: str) -> None:
        self._store = store
        self._run_id = run_id
        self._loop: ReviewLoop | None = None
        self._driver: ReviewLoopDriver | None = None

    def bind_driver(self, driver: ReviewLoopDriver) -> None:
        self._driver = driver

    def bind_loop(self, loop: ReviewLoop) -> None:
        self._loop = loop

    @property
    def profile(self):
        return FOCUSED_PROFILE

    @property
    def spec(self) -> MandatoryWholeReviewSpec:
        if self._loop is None:
            raise RuntimeError("FocusedReviewAdapter loop is not bound")
        return _focused_spec(self._loop)

    def preflight(self, loop: ReviewLoop | None) -> None:
        if loop is not None and loop.type not in {"focused_plan", "focused_output"}:
            raise ProviderRunError(f"review loop {loop.id} is not a focused review loop")

    def current_artifact_binding(self) -> tuple[int, str]:
        loop = self._require_loop()
        if loop.type == "focused_output":
            production = self._store.load_production(self._run_id)
            from top_down_planning.persistence.digests import compute_output_digest

            return int(production["output_revision"]), compute_output_digest(production)
        plan = self._store.load_plan(self._run_id)
        from top_down_planning.persistence.digests import compute_plan_digest

        return int(plan["revision"]), compute_plan_digest(plan)

    def new_loop(self, loop_id: str) -> ReviewLoop:
        raise ProviderRunError("focused review loops are created by review request")

    def build_review_package(
        self,
        run: dict[str, Any],
        config: dict[str, Any],
        loop: ReviewLoop,
    ) -> dict[str, Any]:
        return build_focused_review_package(
            self._run_id,
            run,
            config,
            loop,
            plan=self._store.load_plan_model(self._run_id),
            production=(
                self._store.load_production(self._run_id)
                if loop.type == "focused_output"
                else None
            ),
        )

    def primary_owner_session_id(self, run: dict[str, Any]) -> str | None:
        loop = self._require_loop()
        if loop.type == "focused_plan":
            return primary_planner_provider_session_id(run)
        return primary_producer_provider_session_id(run)

    def build_owner_request(
        self,
        loop: ReviewLoop,
        config: dict[str, Any],
        handoff: OwnerHandoff,
    ) -> dict[str, Any]:
        action = (
            "address_review_findings"
            if handoff == "revision"
            else "address_optional_findings"
        )
        phase = PLANNING if loop.type == "focused_plan" else PRODUCTION
        artifact_revision, artifact_digest = self.current_artifact_binding()
        request: dict[str, Any] = {
            "action": action,
            "phase": phase,
            "loop_id": loop.id,
            "review_type": loop.type,
            "target_revision": loop.target_revision,
            "scope": dict(loop.scope),
            **primary_review_resume_fields(
                loop,
                config=config,
                artifact_revision=artifact_revision,
                artifact_digest=artifact_digest,
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
        if handoff == "revision" and loop.type == "focused_output":
            request["revision_instructions"] = {
                "apply_mode": "evidence_revision",
                "evidence_revision": True,
                "focused_review_loop_id": loop.id,
                "tool": "production_apply",
                "notes": (
                    "Set evidence_revision: true on production apply for "
                    "terminal plan_items targeted by open required findings "
                    "within this focused_output scope. Keep existing "
                    "dispositions unchanged; attach new output evidence IDs. "
                    "Output revision advances for reviewer recheck."
                ),
            }
        return request

    def build_owner_turn_recovery(
        self,
        phase: str,
        append_event: Any,
        model: str | None,
    ) -> Any:
        loop = self._require_loop()
        if loop.type == "focused_plan":
            return build_planner_turn_recovery(
                self._store,
                self._run_id,
                phase=PLANNING,
                expected_next_action="address focused plan findings",
                append_event=append_event,
                model=model,
            )
        return build_producer_turn_recovery(
            self._store,
            self._run_id,
            phase=PRODUCTION,
            expected_next_action="address focused output findings",
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
            expected_next_action="continue reviewer turn",
            append_event=append_event,
            model=model,
            review_package=review_package,
        )

    def after_owner_turn(self, session_id: str) -> None:
        loop = self._require_loop()
        if loop.type == "focused_output":
            _sync_output_digest(self._store, self._run_id)

    def complete_approval(self, loop: ReviewLoop) -> MandatoryWholeReviewResult:
        raise ProviderRunError("focused reviews do not use complete_approval")

    def phase_for_session(self, loop: ReviewLoop, run: dict[str, Any]) -> str:
        return PLANNING if loop.type == "focused_plan" else PRODUCTION

    def prepare_recheck_transition(
        self, loop: ReviewLoop, target_revision: int
    ) -> ReviewLoop:
        return prepare_focused_verification_recheck(
            loop,
            target_revision=target_revision,
        )

    def enter_revision_cycle(
        self, loop: ReviewLoop, revision_cycles: int
    ) -> ReviewLoop:
        return replace(
            loop,
            status="pending",
            revision_cycles=revision_cycles,
        )

    def complete_success(self, loop: ReviewLoop) -> FocusedReviewResult:
        revoke_capabilities_for_loop(self._store, self._run_id, loop.id)
        if self._driver is not None:
            self._driver.append_event(
                "focused_review_approved",
                loop_id=loop.id,
                review_type=loop.type,
                target_revision=loop.target_revision,
            )
        return FocusedReviewResult(
            ok=True,
            loop_id=loop.id,
            status=loop.status,
            reviewer_session_id=reviewer_loop_provider_session_id(loop),
            revision_cycles=loop.revision_cycles,
        )

    def handle_blocked(self, loop: ReviewLoop) -> FocusedReviewResult:
        revoke_capabilities_for_loop(self._store, self._run_id, loop.id)
        return FocusedReviewResult(
            ok=False,
            loop_id=loop.id,
            status=loop.status,
            reviewer_session_id=reviewer_loop_provider_session_id(loop),
            revision_cycles=loop.revision_cycles,
            reason="focused reviewer blocked the scoped review",
        )

    def handle_limit_exhausted(
        self, loop: ReviewLoop, revision_cycles: int
    ) -> FocusedReviewResult:
        config = self._store.load_resolved_config(self._run_id)
        max_revision_cycles = focused_review_revision_limit_from_config(
            config,
            loop.type,  # type: ignore[arg-type]
        )
        stored_loop = ReviewLoop.from_dict(self._store.load_review(self._run_id, loop.id))
        loop = replace(
            stored_loop,
            status="blocked",
            revision_cycles=revision_cycles,
        )
        save_review_with_expected_revision(
            self._store,
            self._run_id,
            loop,
            expected_revision=review_record_revision(stored_loop.to_dict()),
        )
        phase = PLANNING if loop.type == "focused_plan" else PRODUCTION
        message = (
            "focused review exceeded max_revision_cycles_per_loop "
            f"({max_revision_cycles})"
        )
        pause_for_limit_exhausted(
            self._store,
            self._run_id,
            phase=phase,
            message=message,
            limit=(
                "limits.focused_plan_review.max_revision_cycles_per_loop"
                if loop.type == "focused_plan"
                else "limits.focused_output_review.max_revision_cycles_per_loop"
            ),
            consumed=revision_cycles,
            configured=max_revision_cycles,
            role="reviewer",
            revoke_phase=phase,
            loop_id=loop.id,
            review_type=loop.type,
        )
        if self._driver is not None:
            self._driver.append_event(
                "focused_review_limit_exceeded",
                loop_id=loop.id,
                review_type=loop.type,
                reason=message,
            )
        run = self._store.load_run(self._run_id)
        revoke_capabilities_for_loop(self._store, self._run_id, loop.id)
        return FocusedReviewResult(
            ok=False,
            loop_id=loop.id,
            status=str(run.get("status") or "paused"),
            reviewer_session_id=reviewer_loop_provider_session_id(loop),
            revision_cycles=loop.revision_cycles,
            reason=message,
        )

    def handle_review_incomplete(self, loop: ReviewLoop) -> FocusedReviewResult:
        marker = loop.review_incomplete or {}
        reason = str(
            marker.get("reason") or "focused review could not be completed"
        )
        revoke_capabilities_for_loop(self._store, self._run_id, loop.id)
        run = self._store.load_run(self._run_id)
        return FocusedReviewResult(
            ok=False,
            loop_id=loop.id,
            status=str(run.get("status") or loop.status),
            reviewer_session_id=reviewer_loop_provider_session_id(loop),
            revision_cycles=loop.revision_cycles,
            reason=reason,
        )

    def reviewer_session_started_scope(self, loop: ReviewLoop) -> dict[str, Any] | None:
        return {"scope": dict(loop.scope)}

    def _require_loop(self) -> ReviewLoop:
        if self._loop is None:
            raise RuntimeError("FocusedReviewAdapter loop is not bound")
        return self._loop


class FocusedReviewOrchestrator:
    """Drive one optional focused review loop without advancing mandatory gates."""

    def __init__(
        self,
        store: RunStore,
        run_id: str,
        provider: Provider,
    ) -> None:
        self._store = store
        self._run_id = run_id
        self._provider = provider

    def run(self, loop_id: str) -> FocusedReviewResult:
        loop = ReviewLoop.from_dict(self._store.load_review(self._run_id, loop_id))
        adapter = FocusedReviewAdapter(self._store, self._run_id)
        adapter.bind_loop(loop)
        driver = ReviewLoopDriver(self._store, self._run_id, self._provider, adapter)
        adapter.bind_driver(driver)
        result = driver.run(loop_id)
        if not isinstance(result, FocusedReviewResult):
            raise ProviderRunError("focused review driver returned unexpected result")
        return result


def build_focused_review_package(
    run_id: str,
    run: dict[str, Any],
    config: dict[str, Any],
    loop: ReviewLoop,
    *,
    plan: Any,
    production: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Package a bounded focused review for a fresh reviewer session."""

    digests = dict(run.get("digests") or {})
    phase = PLANNING if loop.type == "focused_plan" else PRODUCTION
    revision_label = "plan" if loop.type == "focused_plan" else "output"

    extra_instructions: dict[str, str] = {
        "scope_rule": (
            "Findings must reference only item ids declared in scope.item_ids."
        ),
    }
    if loop.type == "focused_plan":
        extra_instructions["plan_snapshot"] = (
            f"tdp agent plan snapshot --run {run_id} --view active"
        )
    tool_instructions = build_reviewer_tool_instructions(
        run_id,
        review_type=loop.type,
        **extra_instructions,
    )

    package: dict[str, Any] = attach_role_context_to_manifest(
        {
            "run_id": run_id,
            "phase": phase,
            "type": loop.type,
            "loop_id": loop.id,
            "finding_set_id": loop.finding_set_id,
            "purpose": f"Optional focused {revision_label} review within declared scope",
            "scope": dict(loop.scope),
            "target_revision": loop.target_revision,
            **plan_execution_contract_fields(plan),
            "digests": digests,
            "review_policy": reviewer_package_policy_guidance(),
            "review_budgets": review_gate_budgets_for_package(loop, config),
            "instance_ref_guidance": {
                "optional": True,
                "notes": (
                    "Prefer structured instance_ref on findings that target a "
                    "specific plan field, dependency, or output artifact within "
                    "scope.item_ids. Flat target_refs remain valid."
                ),
            },
            "protocol_instructions": build_reviewer_protocol_instructions(
                stage=loop.active_stage,
                review_type=loop.type,
            ),
            "tool_instructions": tool_instructions,
        },
        config=config,
        run=run,
        role="reviewer",
        output_goal=plan.output_goal,
    )
    if loop.type == "focused_plan":
        limits = planning_limits_from_config(config)
        package["plan_revision"] = plan.revision
        package["plan"] = build_plan_review_snapshot(plan, limits=limits)
    if production is not None:
        package["output_revision"] = int(production["output_revision"])
        package["production"] = build_production_review_snapshot(production)
        if loop.type == "focused_output":
            scope_item_ids = [
                str(item_id) for item_id in (loop.scope.get("item_ids") or [])
            ]
            traceability = build_output_traceability(
                plan,
                production,
                item_ids=scope_item_ids,
            )
            package["plan_contracts"] = traceability["plan_contracts"]
            package["evidence_by_item"] = traceability["evidence_by_item"]
    if loop.active_stage == "finding_verification":
        package.update(_focused_verification_package_fields(loop))
        package.update(build_active_findings_view(loop))
        if loop_uses_finding_families(loop):
            if loop.type == "focused_plan":
                artifact_revision = int(plan.revision)
                artifact_digest = compute_plan_digest(plan)
            else:
                artifact_revision = (
                    int(production["output_revision"])
                    if production is not None
                    else int(loop.target_revision)
                )
                artifact_digest = (
                    compute_output_digest(production) if production is not None else None
                )
            package["active_families"] = build_active_family_view(
                loop,
                artifact_revision=artifact_revision,
                artifact_digest=artifact_digest,
            )
    return package


def _sync_output_digest(store: RunStore, run_id: str) -> None:
    run = store.load_run(run_id)
    production = store.load_production(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    digests = dict(run.get("digests") or {})
    digests["output"] = compute_output_digest(production)
    run["digests"] = digests
    store.save_run(run_id, run, expected_revision)
