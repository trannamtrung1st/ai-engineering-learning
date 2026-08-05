"""Verify child-to-parent lineage for attach and resume (proposal §14)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from top_down_planning.domain.run_kind import RUN_KIND_SUB_TDP_EXECUTION, resolve_run_kind
from top_down_planning.domain.production import extract_accepted_delivery
from top_down_planning.package.loader import LoadedExecutionPackage
from top_down_planning.persistence.digests import (
    compute_output_digest,
    compute_plan_digest,
    digest_canonical_payload,
)

# Keep in sync with orchestrator.phases.OUTPUT_VALIDATED — do not import
# orchestrator here (circular: package.lineage → orchestrator → package.lineage).
_OUTPUT_VALIDATED = "output_validated"


@dataclass(frozen=True)
class LineageMismatch:
    field: str
    expected: str
    actual: str


class ExecutionLineageValidator:
    """Validate independently executed children against parent orchestration."""

    def validate_attach(
        self,
        *,
        parent_package: LoadedExecutionPackage,
        parent_manifest_digest: str,
        child_run: dict[str, Any],
        child_production: dict[str, Any],
        child_plan: Any,
    ) -> list[LineageMismatch]:
        expected_digest = parent_manifest_digest or str(
            parent_package.manifest.get("package_digest") or ""
        )
        if not expected_digest:
            raise ValueError("parent package_digest is required for attach validation")

        mismatches = self._validate_binding(
            parent_package=parent_package,
            child_run=child_run,
            expected_package_digest=expected_digest,
        )
        status = str(child_run.get("status") or "")
        phase = str(child_run.get("phase") or "")
        outcome = str(child_run.get("outcome") or "")

        if status != "completed":
            mismatches.append(LineageMismatch("status", "completed", status))
        if phase != _OUTPUT_VALIDATED:
            mismatches.append(LineageMismatch("phase", _OUTPUT_VALIDATED, phase))
        if outcome != "accepted":
            mismatches.append(
                LineageMismatch("outcome", "accepted", outcome or "<missing>")
            )

        unit_id = str(
            (child_run.get("package_binding") or {}).get("selected_unit_id")
            or (child_run.get("package_binding") or {}).get("unit_id")
            or ""
        )
        unit = parent_package.units.get(unit_id)
        if unit is not None:
            actual_plan_digest = compute_plan_digest(child_plan)
            expected_plan_digest = compute_plan_digest(unit.plan)
            if actual_plan_digest != expected_plan_digest:
                mismatches.append(
                    LineageMismatch(
                        "persisted_plan_digest",
                        expected_plan_digest,
                        actual_plan_digest,
                    )
                )

        claim = child_production.get("completion_claim")
        if not isinstance(claim, dict):
            mismatches.append(
                LineageMismatch("completion_claim", "present", "<missing>")
            )
        elif claim.get("goal_met") is not True:
            mismatches.append(
                LineageMismatch(
                    "completion_claim.goal_met",
                    "true",
                    str(claim.get("goal_met")),
                )
            )
        output_digest = compute_output_digest(child_production)
        binding = child_run.get("package_binding") or {}
        expected_output = str((child_run.get("digests") or {}).get("output") or "").strip()
        if not expected_output:
            mismatches.append(
                LineageMismatch("output_digest", "present", "<missing>")
            )
        elif expected_output != output_digest:
            mismatches.append(
                LineageMismatch("output_digest", expected_output, output_digest)
            )

        review_id = str(binding.get("whole_output_review_id") or "").strip()
        review_digest = str(binding.get("whole_output_review_digest") or "").strip()
        if not review_id:
            mismatches.append(
                LineageMismatch("whole_output_review_id", "present", "<missing>")
            )
        if not review_digest:
            mismatches.append(
                LineageMismatch("whole_output_review_digest", "present", "<missing>")
            )

        return mismatches

    def validate_resume(
        self,
        *,
        parent_package: LoadedExecutionPackage,
        child_run: dict[str, Any],
        expected_unit_id: str,
    ) -> list[LineageMismatch]:
        mismatches = self._validate_binding(
            parent_package=parent_package,
            child_run=child_run,
            expected_package_digest=str(
                parent_package.manifest.get("package_digest") or ""
            ),
        )
        binding = child_run.get("package_binding") or {}
        unit_id = str(
            binding.get("selected_unit_id") or binding.get("unit_id") or ""
        )
        if unit_id != expected_unit_id:
            mismatches.append(
                LineageMismatch("unit_id", expected_unit_id, unit_id or "<missing>")
            )
        return mismatches

    def _validate_binding(
        self,
        *,
        parent_package: LoadedExecutionPackage,
        child_run: dict[str, Any],
        expected_package_digest: str,
    ) -> list[LineageMismatch]:
        mismatches: list[LineageMismatch] = []
        try:
            kind = resolve_run_kind(child_run)
        except ValueError as exc:
            mismatches.append(
                LineageMismatch("run_kind", RUN_KIND_SUB_TDP_EXECUTION, str(exc))
            )
            return mismatches
        if kind != RUN_KIND_SUB_TDP_EXECUTION:
            mismatches.append(
                LineageMismatch("run_kind", RUN_KIND_SUB_TDP_EXECUTION, kind)
            )

        binding = child_run.get("package_binding") or {}
        if not isinstance(binding, dict):
            binding = {}

        child_package_id = str(binding.get("package_id") or "")
        parent_package_id = str(parent_package.manifest.get("package_id") or "")
        if child_package_id != parent_package_id:
            mismatches.append(
                LineageMismatch("package_id", parent_package_id, child_package_id)
            )

        child_package_digest = str(binding.get("package_digest") or "")
        if child_package_digest != expected_package_digest:
            mismatches.append(
                LineageMismatch(
                    "package_digest",
                    expected_package_digest,
                    child_package_digest,
                )
            )

        planning_run_id = str(
            (parent_package.manifest.get("planning_run") or {}).get("run_id") or ""
        )
        child_planning = str(binding.get("planning_run_id") or "")
        if planning_run_id and child_planning != planning_run_id:
            mismatches.append(
                LineageMismatch(
                    "planning_run_id",
                    planning_run_id,
                    child_planning or "<missing>",
                )
            )

        parent_plan_digest = str(
            (parent_package.manifest.get("parent") or {}).get("plan_digest") or ""
        )
        child_parent_digest = str(binding.get("parent_plan_digest") or "")
        if parent_plan_digest and child_parent_digest != parent_plan_digest:
            mismatches.append(
                LineageMismatch(
                    "parent_plan_digest",
                    parent_plan_digest,
                    child_parent_digest or "<missing>",
                )
            )

        unit_id = str(binding.get("selected_unit_id") or binding.get("unit_id") or "")
        if unit_id not in parent_package.units:
            mismatches.append(
                LineageMismatch("unit_id", "known unit", unit_id or "<missing>")
            )
        else:
            unit_record = parent_package.units[unit_id]
            child_unit_digest = str(binding.get("unit_plan_digest") or "")
            if child_unit_digest != unit_record.plan_digest:
                mismatches.append(
                    LineageMismatch(
                        "unit_plan_digest",
                        unit_record.plan_digest,
                        child_unit_digest or "<missing>",
                    )
                )
            child_subtree_digest = str(binding.get("assigned_subtree_digest") or "")
            if child_subtree_digest != unit_record.assigned_subtree_digest:
                mismatches.append(
                    LineageMismatch(
                        "assigned_subtree_digest",
                        unit_record.assigned_subtree_digest,
                        child_subtree_digest or "<missing>",
                    )
                )
        return mismatches


def accepted_result_record(
    *,
    child_run: dict[str, Any],
    child_production: dict[str, Any],
    unit_id: str,
    unit_plan_digest: str,
    package_id: str,
    package_digest: str,
    assigned_subtree_digest: str,
    whole_output_review_id: str = "",
    whole_output_review_digest: str = "",
    evidence_digest: str = "",
) -> dict[str, Any]:
    package_id = str(package_id or "").strip()
    package_digest = str(package_digest or "").strip()
    assigned_subtree_digest = str(assigned_subtree_digest or "").strip()
    unit_plan_digest = str(unit_plan_digest or "").strip()
    if not package_id:
        raise ValueError("accepted_result_record requires package_id")
    if not package_digest:
        raise ValueError("accepted_result_record requires package_digest")
    if not assigned_subtree_digest:
        raise ValueError("accepted_result_record requires assigned_subtree_digest")
    if not unit_plan_digest:
        raise ValueError("accepted_result_record requires unit_plan_digest")
    if not unit_id:
        raise ValueError("accepted_result_record requires unit_id")

    digests = child_run.get("digests") or {}
    binding = child_run.get("package_binding") or {}
    if not isinstance(binding, dict):
        binding = {}
    live_output_digest = compute_output_digest(child_production)
    run_output_digest = str(digests.get("output") or "").strip()
    if run_output_digest and run_output_digest != live_output_digest:
        raise ValueError(
            "accepted_result_record requires child production output digest "
            "to match run digests.output"
        )
    output_digest = run_output_digest or live_output_digest
    if not output_digest:
        raise ValueError("accepted_result_record requires a child output digest")
    review_id = str(
        whole_output_review_id
        or binding.get("whole_output_review_id")
        or ""
    ).strip()
    review_digest = str(
        whole_output_review_digest
        or binding.get("whole_output_review_digest")
        or ""
    ).strip()
    if not review_id:
        raise ValueError("accepted_result_record requires whole_output_review_id")
    if not review_digest:
        raise ValueError("accepted_result_record requires whole_output_review_digest")
    delivery = extract_accepted_delivery(child_production)
    if not evidence_digest:
        evidence_ids = [
            str(item.get("id") or "")
            for item in delivery.output_evidence
            if item.get("id")
        ]
        evidence_digest = digest_canonical_payload({"evidence_ids": evidence_ids})
    output_refs = list(delivery.outputs)
    contributions = list(delivery.contributions)
    claim = child_production.get("completion_claim")
    completion_assessment = ""
    if isinstance(claim, dict):
        completion_assessment = str(claim.get("goal_assessment") or "").strip()
    return {
        "schema_version": 1,
        "package_id": package_id,
        "package_digest": package_digest,
        "unit_id": unit_id,
        "unit_plan_digest": unit_plan_digest,
        "assigned_subtree_digest": assigned_subtree_digest,
        "child_run_id": child_run.get("id"),
        "output_revision": int(child_production.get("output_revision") or 0),
        "output_digest": output_digest,
        "whole_output_review_id": review_id,
        "whole_output_review_digest": review_digest,
        "outcome": str(child_run.get("outcome") or ""),
        "evidence_digest": evidence_digest,
        "output_refs": output_refs,
        "contributions": contributions,
        "completion_assessment": completion_assessment,
    }


def accepted_result_digest(record: dict[str, Any]) -> str:
    """Digest the canonical accepted-result attestation (not just output digest)."""

    return digest_canonical_payload(record)


def upstream_accepted_result_binding(
    accepted_result: dict[str, Any],
    *,
    upstream_contract_digest: str,
) -> dict[str, Any]:
    """Wrap an accepted-result attestation with its digest and upstream contract."""

    digest = accepted_result_digest(accepted_result)
    return {
        "accepted_result": accepted_result,
        "accepted_result_digest": digest,
        "upstream_contract_digest": upstream_contract_digest,
    }


def unwrap_upstream_accepted_result(binding: dict[str, Any]) -> dict[str, Any]:
    """Flatten a stored upstream wrapper for producer context."""

    verify_upstream_accepted_result_binding(binding)
    accepted = binding["accepted_result"]
    entry = dict(accepted)
    entry["upstream_contract_digest"] = str(binding["upstream_contract_digest"])
    return entry


def verify_upstream_accepted_result_binding(binding: dict[str, Any]) -> None:
    """Fail closed when an upstream wrapper digest does not match its attestation."""

    accepted = binding.get("accepted_result")
    stored_digest = str(binding.get("accepted_result_digest") or "").strip()
    if not isinstance(accepted, dict):
        raise ValueError("upstream accepted_result attestation is missing")
    if not stored_digest:
        raise ValueError("upstream accepted_result_digest is missing")
    recomputed = accepted_result_digest(accepted)
    if recomputed != stored_digest:
        raise ValueError(
            "upstream accepted_result_digest does not match accepted_result attestation"
        )
    verify_accepted_result_attestation(
        {
            "accepted_result": accepted,
            "accepted_result_digest": stored_digest,
        }
    )
    if not str(binding.get("upstream_contract_digest") or "").strip():
        raise ValueError("upstream accepted_result missing upstream_contract_digest")


def verify_accepted_result_attestation(unit_record: dict[str, Any]) -> None:
    """Fail closed when stored accepted_result digests do not match the attestation."""

    accepted = unit_record.get("accepted_result")
    digest = str(unit_record.get("accepted_result_digest") or "").strip()
    if not isinstance(accepted, dict):
        raise ValueError("unit accepted_result attestation is missing")
    if not digest:
        raise ValueError("unit accepted_result_digest is missing")
    recomputed = accepted_result_digest(accepted)
    if recomputed != digest:
        raise ValueError(
            "unit accepted_result_digest does not match accepted_result attestation"
        )
    if str(accepted.get("outcome") or "") != "accepted":
        raise ValueError(
            f"accepted_result outcome must be accepted, got {accepted.get('outcome')!r}"
        )
    if not str(accepted.get("output_digest") or "").strip():
        raise ValueError("accepted_result missing output_digest")
    if not str(accepted.get("package_id") or "").strip():
        raise ValueError("accepted_result missing package_id")
    if not str(accepted.get("package_digest") or "").strip():
        raise ValueError("accepted_result missing package_digest")
    if not str(accepted.get("assigned_subtree_digest") or "").strip():
        raise ValueError("accepted_result missing assigned_subtree_digest")
    if not str(accepted.get("whole_output_review_id") or "").strip():
        raise ValueError("accepted_result missing whole_output_review_id")
    if not str(accepted.get("whole_output_review_digest") or "").strip():
        raise ValueError("accepted_result missing whole_output_review_digest")
    if not str(accepted.get("child_run_id") or "").strip():
        raise ValueError("accepted_result missing child_run_id")
    unit_child = str(unit_record.get("child_run_id") or "").strip()
    accepted_child = str(accepted.get("child_run_id") or "").strip()
    if unit_child and unit_child != accepted_child:
        raise ValueError(
            "unit child_run_id does not match accepted_result.child_run_id"
        )
    plan_item_id = str(unit_record.get("plan_item_id") or "").strip()
    accepted_unit_id = str(accepted.get("unit_id") or "").strip()
    if not accepted_unit_id:
        raise ValueError("accepted_result missing unit_id")
    if plan_item_id and plan_item_id != accepted_unit_id:
        raise ValueError(
            "accepted_result.unit_id does not match unit plan_item_id"
        )
    unit_plan_digest = str(unit_record.get("unit_plan_digest") or "").strip()
    accepted_plan_digest = str(accepted.get("unit_plan_digest") or "").strip()
    if not accepted_plan_digest:
        raise ValueError("accepted_result missing unit_plan_digest")
    if unit_plan_digest and unit_plan_digest != accepted_plan_digest:
        raise ValueError(
            "accepted_result.unit_plan_digest does not match unit unit_plan_digest"
        )
    if "output_refs" not in accepted or not isinstance(accepted.get("output_refs"), list):
        raise ValueError("accepted_result missing output_refs")
    if "contributions" not in accepted or not isinstance(
        accepted.get("contributions"), list
    ):
        raise ValueError("accepted_result missing contributions")
    if "completion_assessment" not in accepted:
        raise ValueError("accepted_result missing completion_assessment")


def validate_child_package_bindings(binding: dict[str, Any]) -> str | None:
    """Require production-ready binding keys on prepared child runs."""

    if not isinstance(binding, dict):
        return "child package_binding is missing"
    if "upstream_accepted_results" not in binding:
        return "child missing upstream_accepted_results binding"
    upstream = binding.get("upstream_accepted_results")
    if not isinstance(upstream, list):
        return "child upstream_accepted_results is invalid"
    if "workspace_baseline_accepted_results" not in binding:
        return "child missing workspace_baseline_accepted_results binding"
    baseline = binding.get("workspace_baseline_accepted_results")
    if not isinstance(baseline, list):
        return "child workspace_baseline_accepted_results is invalid"
    if "external_prerequisites" not in binding:
        return "child missing external_prerequisites binding"
    external = binding.get("external_prerequisites")
    if not isinstance(external, list):
        return "child external_prerequisites is invalid"
    return None


def validate_attach_dependency_consistency(
    *,
    child_run: dict[str, Any],
    package: LoadedExecutionPackage,
    orchestration_state: dict[str, Any],
    plan_item_id: str,
) -> str | None:
    """Verify child upstream bindings match already-attached dependency results."""

    from top_down_planning.persistence.sub_tdp_state import (
        UNIT_STATUS_COMPLETED,
        find_unit,
    )

    unit = package.units.get(plan_item_id)
    if unit is None:
        return f"unknown unit: {plan_item_id!r}"

    for dep_id in unit.depends_on:
        dep_record = find_unit(orchestration_state, dep_id)
        if dep_record is None:
            return (
                f"dependency {dep_id!r} must be attached before attaching {plan_item_id!r}"
            )
        if str(dep_record.get("status") or "") != UNIT_STATUS_COMPLETED:
            return (
                f"dependency {dep_id!r} must be completed before attaching {plan_item_id!r}"
            )
        dep_digest = str(dep_record.get("accepted_result_digest") or "").strip()
        if not dep_digest:
            return f"dependency {dep_id!r} missing accepted_result_digest"

    binding = child_run.get("package_binding") or {}
    binding_error = validate_child_package_bindings(binding)
    if binding_error:
        return binding_error
    if list(binding.get("external_prerequisites") or []) != list(
        unit.external_prerequisites
    ):
        return (
            f"child external_prerequisites do not match package unit contract "
            f"for {plan_item_id!r}"
        )
    upstream_wrappers = binding["upstream_accepted_results"]

    wrapper_by_unit: dict[str, dict[str, Any]] = {}
    for wrapper in upstream_wrappers:
        if not isinstance(wrapper, dict):
            return "child upstream_accepted_results entry is invalid"
        try:
            verify_upstream_accepted_result_binding(wrapper)
        except ValueError as exc:
            return f"child upstream wrapper invalid: {exc}"
        accepted = wrapper.get("accepted_result") or {}
        dep_unit_id = str(accepted.get("unit_id") or "").strip()
        if not dep_unit_id:
            return "child upstream accepted_result missing unit_id"
        if dep_unit_id in wrapper_by_unit:
            return f"duplicate upstream wrapper for dependency {dep_unit_id!r}"
        wrapper_by_unit[dep_unit_id] = wrapper

    expected_deps = set(unit.depends_on)
    if set(wrapper_by_unit) != expected_deps:
        missing = sorted(expected_deps - set(wrapper_by_unit))
        extra = sorted(set(wrapper_by_unit) - expected_deps)
        parts: list[str] = []
        if missing:
            parts.append(f"missing upstream wrappers: {', '.join(missing)}")
        if extra:
            parts.append(f"unexpected upstream wrappers: {', '.join(extra)}")
        return "; ".join(parts)

    for dep_id in unit.depends_on:
        dep_record = find_unit(orchestration_state, dep_id) or {}
        dep_digest = str(dep_record.get("accepted_result_digest") or "").strip()
        wrapper = wrapper_by_unit[dep_id]
        wrapper_digest = str(wrapper.get("accepted_result_digest") or "").strip()
        if wrapper_digest != dep_digest:
            return (
                f"upstream result for {dep_id!r} does not match attached dependency "
                f"(expected {dep_digest}, got {wrapper_digest})"
            )
        dep_unit = package.units[dep_id]
        contract = str(wrapper.get("upstream_contract_digest") or "").strip()
        if contract != dep_unit.assigned_subtree_digest:
            return (
                f"upstream contract for {dep_id!r} does not match package dependency contract"
            )
        accepted = wrapper.get("accepted_result") or {}
        if str(accepted.get("child_run_id") or "") != str(
            dep_record.get("child_run_id") or ""
        ):
            return f"upstream child_run_id for {dep_id!r} does not match attached child"
        dep_accepted = dep_record.get("accepted_result") or {}
        if str(accepted.get("output_digest") or "") != str(
            dep_accepted.get("output_digest") or ""
        ):
            return f"upstream output_digest for {dep_id!r} does not match attached result"

    baseline_wrappers = binding["workspace_baseline_accepted_results"]
    baseline_digests: set[str] = set()
    for wrapper in baseline_wrappers:
        if not isinstance(wrapper, dict):
            return "child workspace_baseline_accepted_results entry is invalid"
        try:
            verify_upstream_accepted_result_binding(wrapper)
        except ValueError as exc:
            return f"child workspace baseline wrapper invalid: {exc}"
        digest = str(wrapper.get("accepted_result_digest") or "").strip()
        if not digest:
            return "child workspace baseline wrapper missing accepted_result_digest"
        baseline_digests.add(digest)
    upstream_digests = {
        str(wrapper.get("accepted_result_digest") or "").strip()
        for wrapper in upstream_wrappers
    }
    missing_in_baseline = sorted(d for d in upstream_digests if d and d not in baseline_digests)
    if missing_in_baseline:
        return (
            "child workspace_baseline_accepted_results missing upstream digests: "
            + ", ".join(missing_in_baseline)
        )
    return None


def validate_accepted_child_delivery(
    *,
    store: Any,
    child_run_id: str,
    child_run: dict[str, Any] | None = None,
    child_production: dict[str, Any] | None = None,
    verify_evidence: bool = True,
) -> None:
    """Fail closed when child WOR attestation or evidence cannot be proven."""

    from top_down_planning.agent_tool.artifacts import verify_evidence_snapshot
    from top_down_planning.domain.reviews import find_whole_output_approval
    from top_down_planning.package.builder import digest_review_record

    run = child_run if child_run is not None else store.load_run(child_run_id)
    production = (
        child_production
        if child_production is not None
        else store.load_production(child_run_id)
    )
    status = str(run.get("status") or "")
    phase = str(run.get("phase") or "")
    outcome = str(run.get("outcome") or "")
    if status != "completed":
        raise ValueError(f"child status must be completed, got {status!r}")
    if phase != _OUTPUT_VALIDATED:
        raise ValueError(f"child phase must be {_OUTPUT_VALIDATED}, got {phase!r}")
    if outcome != "accepted":
        raise ValueError(f"child outcome must be accepted, got {outcome!r}")

    binding = run.get("package_binding") or {}
    if not isinstance(binding, dict):
        raise ValueError("child package_binding is missing")
    review_id = str(binding.get("whole_output_review_id") or "").strip()
    review_digest = str(binding.get("whole_output_review_digest") or "").strip()
    if not review_id:
        raise ValueError("child whole_output_review_id is missing")
    if not review_digest:
        raise ValueError("child whole_output_review_digest is missing")
    approval = find_whole_output_approval(
        store.list_reviews(child_run_id),
        int(production.get("output_revision") or 0),
    )
    if approval is None:
        raise ValueError("child whole-output approval record missing")
    if str(approval.get("id") or "").strip() != review_id:
        raise ValueError(
            "child whole_output_review_id does not match approved review record"
        )
    if digest_review_record(approval) != review_digest:
        raise ValueError(
            "child whole_output_review_digest does not match approved review record"
        )
    if int(approval.get("target_revision") or -1) != int(
        production.get("output_revision") or 0
    ):
        raise ValueError(
            "child whole-output approval target_revision does not match output_revision"
        )
    claim = production.get("completion_claim")
    if not isinstance(claim, dict) or claim.get("goal_met") is not True:
        raise ValueError("child completion claim must assert goal_met=true")

    live_output_digest = compute_output_digest(production)
    run_output_digest = str((run.get("digests") or {}).get("output") or "").strip()
    if not run_output_digest:
        raise ValueError("child run digests.output is missing")
    if live_output_digest != run_output_digest:
        raise ValueError(
            "child live output digest does not match run digests.output"
        )
    approved_digests = approval.get("approved_digests")
    if not isinstance(approved_digests, dict):
        raise ValueError("child whole-output approval approved_digests is missing")
    approved_output = str(approved_digests.get("output") or "").strip()
    if not approved_output:
        raise ValueError("child whole-output approval output digest is missing")
    if approved_output != run_output_digest:
        raise ValueError(
            "child whole-output approval output digest does not match run digests"
        )
    if not verify_evidence:
        return
    for entry in production.get("output_evidence") or []:
        if not isinstance(entry, dict):
            raise ValueError("child output_evidence entry is invalid")
        if not entry.get("snapshot_ref"):
            continue
        verify_evidence_snapshot(store, child_run_id, entry)


def revalidate_terminal_child_delivery(
    *,
    store: Any,
    child_run_id: str,
    child_run: dict[str, Any],
    verify_evidence: bool = True,
) -> None:
    """Re-check terminal child delivery before reuse."""

    validate_accepted_child_delivery(
        store=store,
        child_run_id=child_run_id,
        child_run=child_run,
        verify_evidence=verify_evidence,
    )


__all__ = [
    "ExecutionLineageValidator",
    "LineageMismatch",
    "accepted_result_digest",
    "accepted_result_record",
    "unwrap_upstream_accepted_result",
    "upstream_accepted_result_binding",
    "validate_attach_dependency_consistency",
    "validate_child_package_bindings",
    "validate_accepted_child_delivery",
    "revalidate_terminal_child_delivery",
    "verify_accepted_result_attestation",
    "verify_upstream_accepted_result_binding",
]
