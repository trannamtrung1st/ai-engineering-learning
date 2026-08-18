"""Agent review request/respond service (proposal §8, §11)."""

from __future__ import annotations

from typing import Any

from top_down_planning.agent_tool.authorization import authorize_mutation
from top_down_planning.agent_tool.commit import commit_authorized
from top_down_planning.agent_tool.errors import RequestError, RevisionConflictError
from top_down_planning.agent_tool.mandatory_review_target import (
    resolve_focused_review_target,
    resolve_mandatory_review_target,
)
from top_down_planning.agent_tool.review_discovery import (
    apply_focused_discovery_response,
    apply_mandatory_discovery_response,
)
from top_down_planning.agent_tool.review_owner_actions import (
    apply_family_fixes,
)
from top_down_planning.agent_tool.review_verification import (
    merge_mandatory_family_verification,
)
from top_down_planning.agent_tool.request_audit import (
    AgentRequestContext,
    apply_request_audit_fields,
)
from top_down_planning.agent_tool.request_schema import validate_agent_request
from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.domain.approval_digests import (
    OUTPUT_APPROVAL_DIGEST_KEYS,
    PLAN_APPROVAL_DIGEST_KEYS,
    reject_legacy_approved_config_digest,
)
from top_down_planning.domain.review_policy import resolved_revise_at
from top_down_planning.domain.review_loop_factory import new_focused_review_loop
from top_down_planning.domain.reviews import (
    ReviewLoop,
    ScopeReviewResult,
    allocate_discovery_finding_set_id,
    apply_owner_finding_actions,
    expand_finding_actions_with_default,
    apply_review_response,
    build_record_actions_gate_fields,
    validate_review_stage,
    find_overlapping_active_focused_loop,
    is_discovery_respond_payload,
    is_mandatory_review_loop,
    is_review_respond_closed,
    is_scope_review_stage_name,
    is_terminal_review_loop,
    loop_revise_at,
    map_discovery_outcome_to_loop_status,
    merge_verification_findings,
    parse_reported_findings,
    parse_findings,
    focused_loop_count,
    policy_observability_fields_for_loop,
    require_review_respond_stage,
    supports_optional_families,
    uses_finding_family_protocol,
    validate_findings_within_scope,
    validate_finding_families_within_scope,
    validate_focused_scope,
    validate_mandatory_stage_decision,
    validate_review_respond_stage,
)
from top_down_planning.persistence.commit import CommitSpec
from top_down_planning.persistence.interface import RunStore
from top_down_planning.persistence.review_commit import review_record_revision

_FOCUSED_PLAN_LIMIT_DEFAULTS = DEFAULT_CONFIG["limits"]["focused_plan_review"]
_FOCUSED_OUTPUT_LIMIT_DEFAULTS = DEFAULT_CONFIG["limits"]["focused_output_review"]


def _reject_non_family_mandatory_loop(loop: ReviewLoop) -> None:
    if loop.type not in {"whole_plan", "whole_output"}:
        return
    if uses_finding_family_protocol(loop):
        return
    raise RequestError(
        f"mandatory {loop.type} review requires contract v2 finding-family protocol; "
        "contract-v1 review records are not supported — recreate the run"
    )


_REVIEW_FRESHNESS_ACTION = (
    "Refresh the artifact snapshot and retry with the current revision and digest."
)


def _artifact_revision_conflict(
    message: str,
    *,
    expected: int | None = None,
    actual: int | None = None,
) -> RevisionConflictError:
    return RevisionConflictError(
        message,
        expected=expected,
        actual=actual,
        action=_REVIEW_FRESHNESS_ACTION,
    )


def _current_focused_artifact_digest(store: RunStore, run_id: str, loop_type: str) -> str:
    from top_down_planning.persistence.digests import (
        compute_output_digest,
        compute_plan_digest,
    )

    if loop_type == "focused_output":
        return compute_output_digest(store.load_production(run_id))
    return compute_plan_digest(store.load_plan(run_id))


def _current_mandatory_artifact_digest(store: RunStore, run_id: str, loop_type: str) -> str:
    from top_down_planning.persistence.digests import (
        compute_output_digest,
        compute_plan_digest,
    )

    if loop_type == "whole_output":
        return compute_output_digest(store.load_production(run_id))
    return compute_plan_digest(store.load_plan_model(run_id))


def _resolve_focused_artifact_digest(
    store: RunStore,
    run_id: str,
    loop: ReviewLoop,
    request: dict[str, Any],
    *,
    require_explicit: bool = False,
) -> str:
    requested = str(request.get("target_digest") or "").strip()
    current = _current_focused_artifact_digest(store, run_id, loop.type)
    if require_explicit and not requested:
        raise RequestError(f"{loop.type} respond requires target_digest")
    if requested:
        if requested != current:
            label = "output" if loop.type == "focused_output" else "plan"
            raise _artifact_revision_conflict(
                f"target_digest does not match current {label} digest"
            )
        return requested
    return current


def _value_error_as_request_error(exc: ValueError) -> RequestError:
    message = str(exc)
    hint: str | None = None
    if "rubric_item_ids union mismatch" in message:
        hint = (
            "Set audit_attestation.passes[].rubric_item_ids from the delivered "
            "review package rubric_items (union across passes must equal every "
            "rubric_items[].id). See tdp agent readme, section Audit attestation."
        )
    elif "must be a built-in rule or match custom" in message:
        hint = (
            "Pick a built-in rule_id from tdp agent readme (section Built-in "
            "finding-family rule_id values) or use custom.<slug> with "
            "rule_definition. See tdp agent example "
            "review-respond-family-discovery-output for a custom rule example."
        )
    elif "produced no new fix actions" in message:
        hint = (
            "Record the initial family_fix while required findings are still open, "
            "or rebind only after owner fix actions exist at the current "
            "target_revision and target_digest."
        )
    elif "target_digest does not match current" in message:
        return _artifact_revision_conflict(message)
    return RequestError(message, hint=hint)


class ReviewAgentService:
    """Structured review interaction for agents against a persisted run."""

    def __init__(self, store: RunStore, run_id: str) -> None:
        self._store = store
        self._run_id = run_id

    def request(
        self,
        request: dict[str, Any],
        *,
        capability_token: str | None = None,
        request_audit: AgentRequestContext | None = None,
    ) -> dict[str, Any]:
        auth = authorize_mutation(
            self._store,
            self._run_id,
            operation="review_request",
            capability_token=capability_token,
        )
        role = auth.role
        validate_agent_request("review_request", request)
        review_type = str(request.get("type") or "").strip()
        if review_type not in {"focused_plan", "focused_output"}:
            raise RequestError(
                "request.type must be focused_plan or focused_output"
            )

        if review_type == "focused_plan" and role != "planner":
            raise RequestError("focused_plan reviews require a planner capability")
        if review_type == "focused_output" and role != "producer":
            raise RequestError("focused_output reviews require a producer capability")

        config = self._store.load_resolved_config(self._run_id)
        review_config = (config.get("review") or {}).get(
            "focused_plan" if review_type == "focused_plan" else "focused_output"
        ) or {}
        if review_config.get("enabled") is not True:
            raise RequestError(f"{review_type} reviews are disabled in config")

        try:
            scope = validate_focused_scope(request.get("scope"), review_type)
        except ValueError as exc:
            raise RequestError(str(exc)) from exc

        reviews = self._store.list_reviews(self._run_id)
        overlapping = find_overlapping_active_focused_loop(
            reviews,
            review_type,
            scope["item_ids"],
        )
        if overlapping is not None:
            raise RequestError(
                f"active {review_type} review {overlapping} already covers overlapping scope"
            )

        loop_count = focused_loop_count(reviews, review_type)
        max_loops = _focused_max_loops(config, review_type)
        if loop_count >= max_loops:
            raise RequestError(
                f"{review_type} review exceeded max_loops ({max_loops})"
            )

        if review_type == "focused_output":
            production = self._store.load_production(self._run_id)
            target_revision = int(production["output_revision"])
            current_digest = _current_focused_artifact_digest(
                self._store, self._run_id, review_type
            )
        else:
            plan = self._store.load_plan(self._run_id)
            target_revision = int(plan["revision"])
            current_digest = _current_focused_artifact_digest(
                self._store, self._run_id, review_type
            )
        requested_revision = request.get("target_revision")
        if requested_revision is None:
            raise RevisionConflictError(
                "focused review request requires target_revision",
                action="Call `tdp agent plan snapshot` or production snapshot and retry.",
            )
        try:
            requested_revision_int = int(requested_revision)
        except (TypeError, ValueError) as exc:
            raise RequestError("target_revision must be an integer") from exc
        if requested_revision_int != target_revision:
            raise RevisionConflictError(
                (
                    f"focused review target_revision conflict: expected {requested_revision_int}, "
                    f"current {target_revision}"
                ),
                expected=requested_revision_int,
                actual=target_revision,
                action="Refresh the artifact snapshot and retry with current revision and digest.",
            )
        requested_digest = str(request.get("target_digest") or "").strip()
        if not requested_digest:
            raise RevisionConflictError(
                "focused review request requires target_digest",
                action="Refresh the artifact snapshot and retry with current revision and digest.",
            )
        if requested_digest != current_digest:
            raise RevisionConflictError(
                "focused review target_digest does not match the current artifact digest",
                action="Refresh the artifact snapshot and retry with current revision and digest.",
            )

        loop_id = _next_focused_loop_id(reviews, review_type)
        loop = new_focused_review_loop(
            loop_id=loop_id,
            review_type=review_type,  # type: ignore[arg-type]
            target_revision=target_revision,
            scope=scope,
            config=config,
        )
        loop, _finding_set_id = allocate_discovery_finding_set_id(loop)
        commit_authorized(
            self._store,
            self._run_id,
            CommitSpec(
                reviews=[loop.to_dict()],
                events=[
                    apply_request_audit_fields(
                        {
                            "type": "focused_review_requested",
                            "run_id": self._run_id,
                            "loop_id": loop_id,
                            "review_type": review_type,
                            "scope": scope,
                            "target_revision": target_revision,
                            "requested_by": role,
                        },
                        request_audit,
                    )
                ],
            ),
            auth,
            conflict_action="Refresh reviews and retry the focused review request.",
        )

        return {
            "ok": True,
            "loop_id": loop_id,
            "type": review_type,
            "scope": scope,
            "target_revision": target_revision,
            "status": loop.status,
        }

    def respond(
        self,
        request: dict[str, Any],
        *,
        capability_token: str | None = None,
        request_audit: AgentRequestContext | None = None,
    ) -> dict[str, Any]:
        loop_id = request.get("loop_id")
        if loop_id is None or not str(loop_id).strip():
            raise RequestError("respond requires loop_id")
        loop_id = str(loop_id).strip()

        auth = authorize_mutation(
            self._store,
            self._run_id,
            operation="review_respond",
            capability_token=capability_token,
            loop_id=loop_id,
        )
        validate_agent_request("review_respond", request)

        if "target_revision" not in request:
            raise RequestError("respond requires target_revision")
        target_revision = int(request["target_revision"])

        loop = ReviewLoop.from_dict(self._store.load_review(self._run_id, loop_id))
        expected_review_revision = review_record_revision(loop.to_dict())
        if is_review_respond_closed(loop):
            raise RequestError(f"review loop {loop_id} is already terminal: {loop.status}")

        stage: str | None = None
        discovery_mode = is_discovery_respond_payload(request)
        try:
            if loop.type in {"whole_plan", "whole_output"}:
                stage = require_review_respond_stage(request)
                expected_stage = loop.active_stage or "initial_review"
                if validate_review_stage(stage) != validate_review_stage(
                    expected_stage
                ):
                    raise ValueError(
                        f"respond stage {stage!r} does not match loop active_stage "
                        f"{loop.active_stage!r}"
                    )
                if stage == "finding_verification":
                    if discovery_mode:
                        raise ValueError(
                            "finding_verification must not use discovery payload"
                        )
                    if "decision" not in request:
                        raise RequestError("respond requires decision")
                    decision = validate_mandatory_stage_decision(
                        stage,
                        str(request["decision"]),
                    )
                else:
                    if not discovery_mode:
                        raise ValueError(
                            "initial_review and scope_review require discovery "
                            "respond fields (finding_set_id, reported_findings, "
                            "review_completed)"
                        )
                    decision = None
            else:
                raw_stage = request.get("stage")
                if (
                    raw_stage is not None
                    and str(raw_stage).strip() == "finding_verification"
                ):
                    stage = "finding_verification"
                    if discovery_mode:
                        raise ValueError(
                            "finding_verification must not use discovery payload"
                        )
                    if loop.active_stage != "finding_verification":
                        raise ValueError(
                            "finding_verification respond requires loop "
                            "active_stage finding_verification"
                        )
                    if "decision" not in request:
                        raise RequestError("respond requires decision")
                    decision = validate_mandatory_stage_decision(
                        stage,
                        str(request["decision"]),
                    )
                else:
                    validate_review_respond_stage(request)
                    if not discovery_mode:
                        raise ValueError(
                            "focused review respond requires discovery contract "
                            "fields (finding_set_id, reported_findings, "
                            "review_completed)"
                        )
                    decision = None
        except ValueError as exc:
            raise _value_error_as_request_error(exc) from exc

        verification_payload = None
        scope_review_payload = None
        derived_outcome = None
        updated: ReviewLoop | None = None
        findings: list = []
        family_events: list[dict[str, Any]] = []

        if discovery_mode:
            if not (
                loop.type in {"focused_plan", "focused_output"}
                or stage == "initial_review"
                or is_scope_review_stage_name(stage or "")
            ):
                raise RequestError(
                    "discovery payload is only valid for focused reviews and "
                    "mandatory initial_review / scope_review stages"
                )
            try:
                if loop.type in {"whole_plan", "whole_output"}:
                    _reject_non_family_mandatory_loop(loop)
                    artifact_digest = str(request.get("target_digest") or "").strip()
                    if not artifact_digest:
                        raise RequestError(
                            f"{loop.type} discovery respond requires target_digest"
                        )
                    target = resolve_mandatory_review_target(
                        self._store,
                        self._run_id,
                        loop,
                        artifact_revision=target_revision,
                        artifact_digest=artifact_digest,
                    )
                    updated, findings, derived_outcome, family_events = (
                        apply_mandatory_discovery_response(
                            loop,
                            request,
                            stage=stage,
                            review_type=target.review_type,
                            artifact_revision=target.artifact_revision,
                            artifact_digest=target.artifact_digest,
                            rubric=[
                                str(item["text"]) for item in target.rubric_items
                            ],
                            allowed_artifact_ref_kinds=target.allowed_artifact_ref_kinds,
                            family_scope_kind=target.family_scope_kind,
                        )
                    )
                elif supports_optional_families(loop):
                    artifact_digest = _resolve_focused_artifact_digest(
                        self._store,
                        self._run_id,
                        loop,
                        request,
                        require_explicit=bool(request.get("finding_families")),
                    )
                    target = resolve_focused_review_target(
                        self._store,
                        self._run_id,
                        loop,
                        artifact_revision=target_revision,
                        artifact_digest=artifact_digest,
                    )
                    updated, findings, derived_outcome, family_events = (
                        apply_focused_discovery_response(
                            loop,
                            request,
                            stage=stage,
                            review_type=target.review_type,
                            artifact_revision=target.artifact_revision,
                            artifact_digest=target.artifact_digest,
                            allowed_artifact_ref_kinds=target.allowed_artifact_ref_kinds,
                            family_scope_kind=target.family_scope_kind,
                        )
                    )
                else:
                    raise RequestError(
                        f"unsupported review loop type for discovery respond: {loop.type}"
                    )
            except ValueError as exc:
                raise _value_error_as_request_error(exc) from exc
            if loop.type in {"focused_plan", "focused_output"}:
                try:
                    validate_findings_within_scope(
                        findings,
                        loop.scope,
                        review_type=loop.type,
                    )
                    if updated is not None:
                        validate_finding_families_within_scope(
                            updated,
                            loop.scope,
                            review_type=loop.type,
                        )
                except ValueError as exc:
                    raise _value_error_as_request_error(exc) from exc
            decision = map_discovery_outcome_to_loop_status(
                derived_outcome,
                stage=stage,
            )
            if is_scope_review_stage_name(stage) and derived_outcome in {
                "approved",
                "changes_requested",
                "blocked",
            }:
                from dataclasses import replace as dc_replace

                target_digest = str(request.get("target_digest") or "").strip()
                scope_id = str(
                    request.get("scope_id") or loop.scope.get("kind") or ""
                ).strip()
                reported_for_stage = parse_reported_findings(request)
                stage_decision = (
                    "approved"
                    if derived_outcome == "approved"
                    else "changes_requested"
                    if derived_outcome == "changes_requested"
                    else "blocked"
                )
                scope_review_payload = ScopeReviewResult(
                    target_digest=target_digest,
                    decision=stage_decision,  # type: ignore[arg-type]
                    scope_id=scope_id or str(loop.scope.get("kind") or ""),
                    acceptance_criteria_checked=[
                        str(item)
                        for item in (request.get("acceptance_criteria_checked") or [])
                    ],
                    reported_findings=(
                        reported_for_stage
                        if derived_outcome == "changes_requested"
                        else []
                    ),
                    summary=str(request.get("summary") or ""),
                ).to_dict()
                updated = dc_replace(
                    updated,
                    scope_review_result=scope_review_payload,
                )
        elif stage == "finding_verification":
            try:
                if loop.type in {"whole_plan", "whole_output"}:
                    _reject_non_family_mandatory_loop(loop)
                    artifact_digest = str(request.get("target_digest") or "").strip()
                    if not artifact_digest:
                        raise RequestError(
                            f"{loop.type} verification respond requires target_digest"
                        )
                    verify_target = resolve_mandatory_review_target(
                        self._store,
                        self._run_id,
                        loop,
                        artifact_revision=target_revision,
                        artifact_digest=artifact_digest,
                    )
                    findings, verification_result, updated_loop, family_events = (
                        merge_mandatory_family_verification(
                            loop,
                            request,
                            artifact_revision=target_revision,
                            artifact_digest=artifact_digest,
                            allowed_artifact_ref_kinds=verify_target.allowed_artifact_ref_kinds,
                        )
                    )
                    verification_payload = verification_result.to_dict()
                    updated = apply_review_response(
                        updated_loop,
                        target_revision=target_revision,
                        decision=decision,
                        findings=findings,
                        approved_digests=None,
                        verification_result=verification_payload,
                        scope_review_result=None,
                    )
                elif supports_optional_families(loop):
                    _resolve_focused_artifact_digest(
                        self._store,
                        self._run_id,
                        loop,
                        request,
                        require_explicit=True,
                    )
                    findings, verification_result = merge_verification_findings(
                        loop, request
                    )
                    verification_payload = verification_result.to_dict()
                else:
                    raise RequestError(
                        f"unsupported review loop type for verification respond: {loop.type}"
                    )
            except ValueError as exc:
                raise _value_error_as_request_error(exc) from exc
            if loop.type in {"focused_plan", "focused_output"}:
                try:
                    validate_findings_within_scope(
                        parse_findings(
                            request.get("new_direct_side_effect_findings") or []
                        ),
                        loop.scope,
                        review_type=loop.type,
                    )
                except ValueError as exc:
                    raise _value_error_as_request_error(exc) from exc
        else:
            raise RequestError("unsupported review respond payload")

        if loop.type == "whole_output" or loop.type == "focused_output":
            current_revision = int(self._store.load_production(self._run_id)["output_revision"])
            revision_label = "output"
        else:
            current_revision = int(self._store.load_plan(self._run_id)["revision"])
            revision_label = "plan"
        if target_revision != current_revision:
            raise RequestError(
                f"target_revision {target_revision} does not match current {revision_label} "
                f"revision {current_revision}"
            )
        if loop.target_revision != target_revision:
            raise _artifact_revision_conflict(
                f"target_revision {target_revision} does not match loop target "
                f"{loop.target_revision}",
                expected=int(loop.target_revision),
                actual=int(target_revision),
            )

        approved_digests: dict[str, str] | None = None
        artifact_digest: str | None = None
        if loop.type in {"whole_plan", "whole_output"}:
            run = self._store.load_run(self._run_id)
            run_digests = run.get("digests") or {}
            allowed_keys = (
                PLAN_APPROVAL_DIGEST_KEYS
                if loop.type == "whole_plan"
                else OUTPUT_APPROVAL_DIGEST_KEYS
            )
            approved_digests = {
                str(key): str(value)
                for key, value in run_digests.items()
                if key in allowed_keys and value is not None
            }
            reject_legacy_approved_config_digest(approved_digests)
            if loop.type == "whole_output":
                from top_down_planning.persistence.digests import compute_output_digest

                production = self._store.load_production(self._run_id)
                approved_digests["output"] = compute_output_digest(production)
                artifact_digest = approved_digests.get("output")
            else:
                from top_down_planning.persistence.digests import compute_plan_digest

                plan = self._store.load_plan_model(self._run_id)
                approved_digests["plan"] = compute_plan_digest(plan)
                artifact_digest = approved_digests.get("plan")

            mandatory_stage = stage or (loop.active_stage or "initial_review")
            request_digest = str(request.get("target_digest") or "").strip()
            if mandatory_stage == "finding_verification" or is_scope_review_stage_name(
                mandatory_stage
            ):
                if not request_digest:
                    raise RequestError(
                        f"{mandatory_stage} respond requires target_digest"
                    )
                if artifact_digest is not None and request_digest != artifact_digest:
                    artifact_key = "plan" if loop.type == "whole_plan" else "output"
                    raise _artifact_revision_conflict(
                        f"target_digest does not match current {artifact_key} digest"
                    )
            if decision == "approved":
                if artifact_digest is None:
                    raise RequestError(
                        "mandatory review approval requires artifact digest"
                    )
                if not request_digest:
                    raise RequestError(
                        f"{mandatory_stage} approval requires target_digest"
                    )
                if artifact_digest is not None and request_digest != artifact_digest:
                    artifact_key = "plan" if loop.type == "whole_plan" else "output"
                    raise _artifact_revision_conflict(
                        f"target_digest does not match current {artifact_key} digest"
                    )

        if updated is None:
            assert decision is not None
            try:
                updated = apply_review_response(
                    loop,
                    target_revision=target_revision,
                    decision=decision,
                    findings=findings,
                    approved_digests=(
                        approved_digests
                        if decision == "approved"
                        else None
                    ),
                    verification_result=verification_payload,
                    scope_review_result=scope_review_payload,
                )
            except ValueError as exc:
                raise _value_error_as_request_error(exc) from exc
        elif decision == "approved" and approved_digests is not None:
            updated = replace_loop_approved_digests(updated, approved_digests)

        event = apply_request_audit_fields(
            {
                "type": "review_responded",
                "run_id": self._run_id,
                "loop_id": loop_id,
                "decision": decision,
                "target_revision": target_revision,
                "finding_count": len(updated.findings),
            },
            request_audit,
        )
        if stage is not None:
            event["stage"] = stage
        observability = policy_observability_fields_for_loop(updated)
        from top_down_planning.domain.finding_families import family_observability_fields

        observability.update(
            family_observability_fields(
                updated,
                artifact_revision=target_revision,
                artifact_digest=str(request.get("target_digest") or "").strip() or None,
            )
        )
        event.update(observability)
        if derived_outcome is not None:
            event["derived_outcome"] = derived_outcome

        extra_events: list[dict[str, Any]] = []
        if derived_outcome is not None or stage is not None:
            # Concise audit companions (no full finding payloads).
            reported = observability
            findings_event = {
                "type": "review_findings_reported",
                "run_id": self._run_id,
                "loop_id": loop_id,
                "stage": stage or (loop.active_stage or "initial_review"),
                "finding_set_id": updated.finding_set_id,
                **{
                    key: reported[key]
                    for key in (
                        "revise_at",
                        "finding_count",
                        "required_open_finding_count",
                        "optional_open_finding_count",
                        "required_open_finding_ids",
                        "optional_open_finding_ids",
                        "optional_finding_ids_missing_owner_response",
                        "optional_finding_ids_requiring_verification",
                    )
                },
            }
            extra_events.append(findings_event)
            revision_statuses = {
                "changes_requested",
                "needs_revision",
            }
            if (
                derived_outcome == "changes_requested"
                or str(decision or "") in revision_statuses
                or (
                    updated.status in revision_statuses
                    and derived_outcome != "blocked"
                )
            ):
                extra_events.append(
                    {
                        "type": "review_revision_required",
                        "run_id": self._run_id,
                        "loop_id": loop_id,
                        "stage": stage or (loop.active_stage or "initial_review"),
                        "finding_set_id": updated.finding_set_id,
                        "revise_at": observability["revise_at"],
                        "required_open_finding_count": observability[
                            "required_open_finding_count"
                        ],
                        "required_open_finding_ids": observability[
                            "required_open_finding_ids"
                        ],
                    }
                )

        if derived_outcome == "review_incomplete":
            marker = updated.review_incomplete or {}
            reason = str(marker.get("reason") or "Review could not be completed.")
            incomplete_event: dict[str, Any] = {
                "type": "review_incomplete",
                "run_id": self._run_id,
                "loop_id": loop_id,
                "reason": reason,
                "finding_set_id": updated.finding_set_id,
                "stage": marker.get("stage") or stage,
                "revise_at": observability["revise_at"],
            }
            if loop.type in {"focused_plan", "focused_output"}:
                run = self._store.load_run(self._run_id)
                incomplete_event["phase"] = run.get("phase")
                commit_authorized(
                    self._store,
                    self._run_id,
                    CommitSpec(
                        reviews=[updated.to_dict()],
                        events=[event, *extra_events, *family_events, incomplete_event],
                        review_expected_revisions={loop_id: expected_review_revision},
                    ),
                    auth,
                    conflict_action="Refresh the review loop and retry respond.",
                )
            else:
                run = self._store.load_run(self._run_id)
                if run.get("outcome") is not None:
                    raise RequestError(
                        "review_incomplete cannot override an existing quality outcome"
                    )
                run_patch = dict(run)
                run_patch["revision"] = auth.run_revision + 1
                run_patch["status"] = "failed"
                incomplete_event["phase"] = run.get("phase")
                commit_authorized(
                    self._store,
                    self._run_id,
                    CommitSpec(
                        reviews=[updated.to_dict()],
                        events=[event, *extra_events, *family_events, incomplete_event],
                        run=run_patch,
                        run_expected_revision=auth.run_revision,
                        review_expected_revisions={loop_id: expected_review_revision},
                    ),
                    auth,
                    conflict_action="Refresh the review loop and retry respond.",
                )
        else:
            commit_authorized(
                self._store,
                self._run_id,
                CommitSpec(
                    reviews=[updated.to_dict()],
                    events=[event, *extra_events, *family_events],
                    review_expected_revisions={loop_id: expected_review_revision},
                ),
                auth,
                conflict_action="Refresh the review loop and retry respond.",
            )

        response: dict[str, Any] = {
            "ok": True,
            "loop_id": loop_id,
            "decision": decision,
            "target_revision": target_revision,
            "status": updated.status,
            "findings": [finding.to_dict() for finding in updated.findings],
            **observability,
        }
        if stage is not None:
            response["stage"] = stage
        if derived_outcome is not None:
            response["derived_outcome"] = derived_outcome
        return response

    def record_finding_actions(
        self,
        request: dict[str, Any],
        *,
        capability_token: str | None = None,
        request_audit: AgentRequestContext | None = None,
    ) -> dict[str, Any]:
        """Record primary-agent owner actions for optional/required findings."""

        loop_id = request.get("loop_id")
        if loop_id is None or not str(loop_id).strip():
            raise RequestError("record_finding_actions requires loop_id")
        loop_id = str(loop_id).strip()

        auth = authorize_mutation(
            self._store,
            self._run_id,
            operation="review_record_finding_actions",
            capability_token=capability_token,
        )
        role = auth.role
        if role not in {"planner", "producer"}:
            raise RequestError(
                "review_record_finding_actions requires a planner or producer capability"
            )
        validate_agent_request("review_record_finding_actions", request)

        loop = ReviewLoop.from_dict(self._store.load_review(self._run_id, loop_id))
        expected_review_revision = review_record_revision(loop.to_dict())
        if is_terminal_review_loop(loop):
            raise RequestError(
                f"review loop {loop_id} is already closed: {loop.status}"
            )
        if loop.status == "approved":
            if is_mandatory_review_loop(loop):
                raise RequestError(
                    f"review loop {loop_id} already satisfied finding policy: "
                    f"{loop.status}"
                )
            raise RequestError(
                f"review loop {loop_id} is already closed: {loop.status}"
            )

        raw_actions = request.get("finding_actions")
        if raw_actions is None:
            raw_actions = []
        if not isinstance(raw_actions, list):
            raise RequestError("finding_actions must be a list")
        raw_fixes = request.get("family_fixes") or []
        if not isinstance(raw_fixes, list):
            raise RequestError("family_fixes must be a list")
        default_optional = request.get("default_optional_action")
        if (
            not raw_actions
            and not raw_fixes
            and (default_optional is None or not str(default_optional).strip())
        ):
            raise RequestError(
                "record_finding_actions requires finding_actions, family_fixes, or "
                "default_optional_action"
            )

        if loop.type in {"whole_output", "focused_output"}:
            current_artifact_revision = int(
                self._store.load_production(self._run_id)["output_revision"]
            )
        else:
            current_artifact_revision = int(self._store.load_plan(self._run_id)["revision"])

        root_finding_set_id = str(
            request.get("finding_set_id") or loop.finding_set_id or ""
        ).strip()

        if "target_revision" in request:
            try:
                requested_revision = int(request["target_revision"])
            except (TypeError, ValueError) as exc:
                raise RequestError("target_revision must be an integer") from exc
            if requested_revision != current_artifact_revision:
                raise _artifact_revision_conflict(
                    f"target_revision {requested_revision} does not match current "
                    f"revision {current_artifact_revision}",
                    expected=current_artifact_revision,
                    actual=requested_revision,
                )
            artifact_revision = requested_revision
        else:
            artifact_revision = current_artifact_revision

        requested_digest = str(request.get("target_digest") or "").strip()
        if requested_digest:
            if loop.type in {"whole_output", "focused_output"}:
                current_digest = _current_focused_artifact_digest(
                    self._store, self._run_id, "focused_output"
                ) if loop.type == "focused_output" else _current_mandatory_artifact_digest(
                    self._store, self._run_id, loop.type
                )
            else:
                current_digest = (
                    _current_focused_artifact_digest(
                        self._store, self._run_id, "focused_plan"
                    )
                    if loop.type == "focused_plan"
                    else _current_mandatory_artifact_digest(
                        self._store, self._run_id, loop.type
                    )
                )
            if requested_digest != current_digest:
                raise _artifact_revision_conflict(
                    "target_digest does not match current artifact digest"
                )

        family_events: list[dict[str, Any]] = []
        try:
            if (
                raw_fixes
                and uses_finding_family_protocol(loop)
                and loop.type in {"whole_plan", "whole_output"}
            ):
                target_digest = str(request.get("target_digest") or "").strip()
                if not target_digest:
                    raise RequestError("family_fixes require target_digest")
                current_digest = _current_mandatory_artifact_digest(
                    self._store,
                    self._run_id,
                    loop.type,
                )
                if target_digest != current_digest:
                    label = "output" if loop.type == "whole_output" else "plan"
                    raise _artifact_revision_conflict(
                        f"target_digest does not match current {label} digest"
                    )
                updated, parsed, family_events = apply_family_fixes(
                    loop,
                    request,
                    actor_role=role,
                    artifact_revision=artifact_revision,
                    artifact_digest=target_digest,
                    finding_set_id=root_finding_set_id,
                    current_artifact_revision=current_artifact_revision,
                )
            else:
                if raw_fixes:
                    raise RequestError(
                        "family_fixes apply only to mandatory whole_plan and "
                        "whole_output contract-v2 reviews"
                    )

                expanded_actions = expand_finding_actions_with_default(
                    loop,
                    raw_actions,
                    default_optional_action=(
                        str(default_optional).strip()
                        if default_optional is not None
                        and str(default_optional).strip()
                        else None
                    ),
                    actor_role=role,
                    artifact_revision=artifact_revision,
                )
                stamped_actions: list[dict[str, Any]] = []
                for item in expanded_actions:
                    payload = dict(item)
                    payload.setdefault("artifact_revision", artifact_revision)
                    if root_finding_set_id and not str(
                        payload.get("finding_set_id") or ""
                    ).strip():
                        payload["finding_set_id"] = root_finding_set_id
                    stamped_actions.append(payload)
                updated, parsed = apply_owner_finding_actions(
                    loop,
                    stamped_actions,
                    actor_role=role,
                    artifact_revision=artifact_revision,
                )
        except ValueError as exc:
            raise _value_error_as_request_error(exc) from exc

        event: dict[str, Any] = apply_request_audit_fields(
            {
                "type": "review_finding_action_recorded",
                "run_id": self._run_id,
                "loop_id": loop_id,
                "actor_role": role,
                "action_count": len(parsed),
                "actions": [action.action for action in parsed],
            },
            request_audit,
        )
        if any(action.action == "challenge" for action in parsed):
            event["type"] = "review_challenge_submitted"
        event.update(policy_observability_fields_for_loop(updated))

        commit_authorized(
            self._store,
            self._run_id,
            CommitSpec(
                reviews=[updated.to_dict()],
                events=[event, *family_events],
                review_expected_revisions={loop_id: expected_review_revision},
            ),
            auth,
            conflict_action="Refresh the review loop and retry record-actions.",
        )

        return {
            "ok": True,
            "loop_id": loop_id,
            "status": updated.status,
            "recorded_actions": [action.to_dict() for action in parsed],
            **policy_observability_fields_for_loop(updated),
            **build_record_actions_gate_fields(updated),
        }


def replace_loop_approved_digests(
    loop: ReviewLoop,
    approved_digests: dict[str, str],
) -> ReviewLoop:
    from dataclasses import replace

    return replace(loop, approved_digests=dict(approved_digests))


def _focused_max_loops(config: dict[str, Any], review_type: str) -> int:
    if review_type == "focused_plan":
        review_limits = (config.get("limits") or {}).get("focused_plan_review") or {}
        return int(
            review_limits.get("max_loops", _FOCUSED_PLAN_LIMIT_DEFAULTS["max_loops"])
        )
    review_limits = (config.get("limits") or {}).get("focused_output_review") or {}
    return int(
        review_limits.get("max_loops", _FOCUSED_OUTPUT_LIMIT_DEFAULTS["max_loops"])
    )


def _next_focused_loop_id(reviews: list[dict[str, Any]], review_type: str) -> str:
    prefix = (
        "review-focused-plan"
        if review_type == "focused_plan"
        else "review-focused-output"
    )
    existing = [
        payload.get("id")
        for payload in reviews
        if payload.get("type") == review_type and payload.get("id")
    ]
    index = len(existing) + 1
    return f"{prefix}-{index:02d}"
