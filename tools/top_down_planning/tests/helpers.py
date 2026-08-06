"""Shared helpers for top_down_planning tests."""

from __future__ import annotations

import copy
import json
import threading
from pathlib import Path
from typing import Any, Mapping

from core_tools.provider import StubProvider
from core_tools.provider.errors import ProviderSessionNotFoundError
from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.domain.approval_digests import (
    OUTPUT_APPROVAL_DIGEST_KEYS,
    PLAN_APPROVAL_DIGEST_KEYS,
)
from top_down_planning.orchestrator.phases import PLANNING, PRODUCTION
from top_down_planning.persistence.capabilities import (
    CAPABILITY_TOKEN_FILE_ENV_VAR,
    clear_capability_token_file,
    write_capability_token_file,
)


def plan_root_item(
    *,
    title: str = "Deliver the output",
    outcome: str = "Deliver the output.",
) -> Any:
    from top_down_planning.domain.models import PlanItem
    from top_down_planning.domain.plan_tree import PLAN_ROOT_ITEM_ID

    return PlanItem(
        id=PLAN_ROOT_ITEM_ID,
        parent_id=None,
        order_key="0000000000",
        title=title,
        outcome=outcome,
        kind="aggregate",
    )


def ensure_plan_work_scope_contracts(plan: Any) -> Any:
    """Give active work leaves a default item scope for approval-mode tests."""

    from top_down_planning.domain.item_contract import has_item_scope_contract
    from top_down_planning.domain.models import Plan, Scope

    if not isinstance(plan, Plan):
        return plan
    for item in plan.items.values():
        if item.kind != "work" or item.planning_status != "open":
            continue
        if has_item_scope_contract(item):
            continue
        item.scope = Scope(includes=[f"{item.title} test capability"])
    return plan


def work_item_payload(*, title: str, outcome: str, **extra: Any) -> dict[str, Any]:
    """Build a work item payload with a default item-level scope contract."""

    payload: dict[str, Any] = {
        "kind": "work",
        "title": title,
        "outcome": outcome,
        **extra,
    }
    scope = payload.get("scope")
    boundaries = payload.get("boundaries")
    has_scope = isinstance(scope, dict) and (
        any(str(entry).strip() for entry in (scope.get("includes") or []))
        or any(str(entry).strip() for entry in (scope.get("excludes") or []))
    )
    has_boundaries = isinstance(boundaries, list) and any(
        str(entry).strip() for entry in boundaries
    )
    if not has_scope and not has_boundaries:
        payload["scope"] = {"includes": [f"{title} capability"]}
    return payload


def update_plan_root_operation(
    *,
    title: str = "Deliver the output",
    outcome: str = "Deliver the output.",
) -> dict[str, Any]:
    from top_down_planning.domain.plan_tree import PLAN_ROOT_ITEM_ID

    return {
        "op": "update_item",
        "item_id": PLAN_ROOT_ITEM_ID,
        "patch": {"title": title, "outcome": outcome},
    }


def with_root_contract(
    operations: list[dict[str, Any]],
    *,
    title: str = "Deliver the output",
    outcome: str = "Deliver the output.",
) -> list[dict[str, Any]]:
    """Prepend the required root update_item before decomposition operations."""

    return [update_plan_root_operation(title=title, outcome=outcome), *operations]


def bind_primary_session_for_tests(
    sessions: dict[str, Any],
    *,
    role: str,
    provider_session_id: str,
    config: dict[str, Any],
    workspace: Path | str,
    activity: str | None = None,
    provider: str | None = "cursor",
) -> dict[str, Any]:
    """Persist a resumable primary binding with activity metadata for tests."""

    from top_down_planning.config import resolve_effective_activity_context, resolve_workspace
    from top_down_planning.persistence.session_bindings import update_primary_binding

    default_activity = {
        "planner": "initial_plan",
        "producer": "production",
    }
    resolved_activity = activity or default_activity[str(role)]
    resolved_workspace = resolve_workspace(config, cwd=Path(workspace).resolve())
    context = resolve_effective_activity_context(
        config,
        role,  # type: ignore[arg-type]
        resolved_activity,  # type: ignore[arg-type]
        workspace=resolved_workspace,
    )
    return update_primary_binding(
        sessions,
        role=role,
        provider_session_id=provider_session_id,
        provider=provider,
        model=context.model,
        activity=context.activity,
        context_digest=context.context_digest,
    )


def sessions_with_primary_session(
    *,
    planner: str | None = None,
    producer: str | None = None,
    config: dict[str, Any] | None = None,
    workspace: Path | str | None = None,
    planner_activity: str = "initial_plan",
    producer_activity: str = "production",
) -> dict[str, Any]:
    from top_down_planning.config import resolve_effective_activity_context, resolve_workspace
    from top_down_planning.persistence.session_bindings import update_primary_binding

    resolved_workspace = resolve_workspace(config, cwd=Path(workspace or ".").resolve()) if config else Path(workspace or ".").resolve()

    def _binding_fields(role: str, activity: str) -> tuple[str | None, str | None]:
        if config is None:
            return activity, None
        context = resolve_effective_activity_context(
            config,
            role,  # type: ignore[arg-type]
            activity,  # type: ignore[arg-type]
            workspace=resolved_workspace,
        )
        return context.activity, context.context_digest

    sessions: dict[str, Any] = {}
    if planner is not None:
        activity, digest = _binding_fields("planner", planner_activity)
        sessions = update_primary_binding(
            sessions,
            role="planner",
            provider_session_id=planner,
            activity=activity,
            context_digest=digest,
        )
    if producer is not None:
        activity, digest = _binding_fields("producer", producer_activity)
        sessions = update_primary_binding(
            sessions,
            role="producer",
            provider_session_id=producer,
            activity=activity,
            context_digest=digest,
        )
    return sessions


def assert_primary_session_id(
    run: dict[str, Any],
    role: str,
    expected: str | None,
) -> None:
    from top_down_planning.persistence.session_bindings import primary_provider_session_id

    assert primary_provider_session_id(run, role) == expected


def review_loop_dict_with_binding(payload: dict[str, Any]) -> dict[str, Any]:
    from top_down_planning.domain.session_bindings import reviewer_binding_for_provider_session

    data = dict(payload)
    data.setdefault("review_record_schema_version", 2)
    data.setdefault("review_contract_version", 2)
    session_id = data.pop("reviewer_session_id", None)
    if "reviewer_binding" not in data and session_id:
        binding = reviewer_binding_for_provider_session(
            str(session_id),
            instance_seed=str(data.get("id") or ""),
        )
        if binding is not None:
            data["reviewer_binding"] = binding.to_dict()
    return data


def make_review_loop(**kwargs: Any) -> Any:
    """Build a ``ReviewLoop`` from fixture kwargs (maps ``reviewer_session_id`` → binding)."""

    from top_down_planning.domain.reviews import ReviewLoop
    from top_down_planning.domain.session_bindings import SessionBinding

    kwargs = dict(kwargs)
    binding = kwargs.get("reviewer_binding")
    if isinstance(binding, SessionBinding):
        kwargs["reviewer_binding"] = binding.to_dict()
    findings = kwargs.get("findings")
    if isinstance(findings, list) and findings and hasattr(findings[0], "to_dict"):
        kwargs["findings"] = [
            item.to_dict() if hasattr(item, "to_dict") else item for item in findings
        ]
    finding_actions = kwargs.get("finding_actions")
    if (
        isinstance(finding_actions, list)
        and finding_actions
        and hasattr(finding_actions[0], "to_dict")
    ):
        kwargs = dict(kwargs)
        kwargs["finding_actions"] = [
            item.to_dict() if hasattr(item, "to_dict") else item
            for item in finding_actions
        ]
    payload = review_loop_dict_with_binding(dict(kwargs))
    payload.setdefault("status", "pending")
    payload.setdefault("findings", [])
    payload.setdefault("revision_cycles", 0)
    payload.setdefault("revision", 0)
    payload.setdefault("finding_actions", [])
    payload.setdefault("advisory_handoffs_completed", [])
    payload.setdefault("finding_ids_by_set", {})
    loop_type = str(payload.get("type") or "").strip()
    payload.setdefault("review_record_schema_version", 2)
    payload.setdefault("review_contract_version", 2)
    if loop_type and payload.get("revise_at") is None:
        from top_down_planning.domain.review_policy import BUILTIN_REVISE_AT

        if loop_type in BUILTIN_REVISE_AT:
            payload["revise_at"] = "blocker"
    return ReviewLoop.from_dict(payload)


def test_run_workspace(store: Any) -> str:
    """Workspace path for test runs (required on ``create_run``)."""

    return str(store.root)


def write_config(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def ensure_input_ref_files(workspace: Path, config: dict[str, Any]) -> None:
    """Create stub files for configured input refs when tests reference paths."""

    run_section = config.get("run")
    if not isinstance(run_section, dict):
        return

    for ref in run_section.get("input_refs") or []:
        ref_text = str(ref).strip()
        if not ref_text or any(char in ref_text for char in "*?[]"):
            continue
        target = workspace / ref_text
        if target.is_file():
            continue
        if target.is_dir():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"fixture content for {ref_text}\n", encoding="utf-8")


def _normalize_test_resolved_config(config: dict[str, Any]) -> dict[str, Any]:
    """Default unit tests to stub provider unless a test overrides it explicitly."""

    normalized = copy.deepcopy(config)
    provider = normalized.get("provider")
    if not isinstance(provider, dict):
        normalized["provider"] = {"name": "stub", "skip_probe": True}
        return normalized

    name = str(provider.get("name") or "").strip().lower()
    if not name:
        normalized["provider"] = {"name": "stub", "skip_probe": True}
        return normalized

    if name == "stub":
        merged_provider = dict(provider)
        merged_provider.setdefault("skip_probe", True)
        normalized["provider"] = merged_provider
    return normalized


def minimal_resolved_config(**overrides: Any) -> dict[str, Any]:
    """Return a minimal resolved config snapshot for test runs."""

    config = copy.deepcopy(DEFAULT_CONFIG)
    config["project"]["workspace"] = "."
    config["run"]["output_goal"] = "Goal."
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(config.get(key), dict):
            merged = copy.deepcopy(config[key])
            merged.update(value)
            config[key] = merged
        else:
            config[key] = value
    return _normalize_test_resolved_config(config)


def run_context_digests_for_config(
    workspace: Path,
    config: dict[str, Any],
) -> tuple[str, str, dict[str, Any]]:
    from top_down_planning.config.context_digests import build_initial_context_snapshot_binding

    binding, spec_digest, snapshot_digest = build_initial_context_snapshot_binding(
        config,
        workspace=workspace,
    )
    return spec_digest, snapshot_digest, binding


def run_digests_for_config(
    workspace: Path,
    config: dict[str, Any],
) -> tuple[str, str, str, str, dict[str, Any]]:
    from top_down_planning.config import (
        compute_input_digest,
        compute_output_goal_digest,
    )

    spec_digest, snapshot_digest, binding = run_context_digests_for_config(workspace, config)
    return (
        compute_input_digest(config, base_dir=workspace),
        compute_output_goal_digest(config, base_dir=workspace),
        spec_digest,
        snapshot_digest,
        binding,
    )


def minimal_invocation(
    workspace: Path,
    *,
    source: str = "test",
    command: str | None = None,
    until: str | None = None,
) -> dict[str, Any]:
    """Minimal invocation metadata for test runs."""

    return {
        "observability": copy.deepcopy(DEFAULT_CONFIG["observability"]),
        "runs_dir": {"path": str(workspace.resolve()), "source": source},
        "stream_json": False,
        "until": until,
        "command": command,
    }


def create_run_kwargs(
    workspace: Path,
    *,
    resolved_config: dict[str, Any] | None = None,
) -> dict[str, str | dict[str, Any]]:
    """Return shared ``create_run`` digest/config kwargs for tests."""

    config = _normalize_test_resolved_config(resolved_config or minimal_resolved_config())
    if isinstance(config.get("project"), dict):
        config = copy.deepcopy(config)
        config["project"]["workspace"] = str(workspace.resolve())
    ensure_input_ref_files(workspace, config)
    input_digest, output_goal_digest, context_spec_digest, context_snapshot_digest, binding = (
        run_digests_for_config(workspace, config)
    )
    return {
        "resolved_config": config,
        "input_digest": input_digest,
        "output_goal_digest": output_goal_digest,
        "context_spec_digest": context_spec_digest,
        "context_snapshot_digest": context_snapshot_digest,
        "context_snapshot_binding": binding,
        "workspace": str(workspace.resolve()),
        "invocation": minimal_invocation(workspace),
    }


def approved_digests_from_run(
    store: Any,
    run_id: str,
    *,
    keys: frozenset[str] | None = None,
) -> dict[str, str]:
    from top_down_planning.persistence import FileRunStore

    if not isinstance(store, FileRunStore):
        raise TypeError("store must be a FileRunStore")
    run = store.load_run(run_id)
    allowed = keys or PLAN_APPROVAL_DIGEST_KEYS
    return {
        str(key): str(value)
        for key, value in (run.get("digests") or {}).items()
        if key in allowed and value is not None
    }


def mandatory_plan_digest(store: Any, run_id: str) -> str:
    from top_down_planning.persistence.digests import compute_plan_digest

    return compute_plan_digest(store.load_plan_model(run_id))


def mandatory_output_digest(store: Any, run_id: str) -> str:
    from top_down_planning.persistence.digests import compute_output_digest

    return compute_output_digest(store.load_production(run_id))


def _normalize_reported_findings(
    findings: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    reported: list[dict[str, Any]] = []
    for item in findings or []:
        finding = dict(item)
        if not str(finding.get("severity") or "").strip():
            raise ValueError("test finding fixtures require severity")
        if not str(finding.get("category") or "").strip():
            raise ValueError("test finding fixtures require category")
        if "recommended_change" not in finding:
            raise ValueError("test finding fixtures require recommended_change")
        reported.append(finding)
    return reported


def _loop_uses_family_protocol(loop: Mapping[str, Any]) -> bool:
    version = loop.get("review_contract_version")
    if version is None:
        return False
    return int(version) == 2


def _synthetic_whole_plan_families(
    reported_findings: list[dict[str, Any]],
    *,
    finding_set_id: str,
    review_completed: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build minimal finding families for whole-plan discovery test payloads."""

    if not reported_findings:
        return reported_findings, []

    from top_down_planning.domain.artifact_refs import digest_field_value
    from top_down_planning.domain.finding_families import compute_family_fingerprint

    family_id = "family-test-default"
    rule_id = "coverage.traceability_gap"
    subject_key = "test-subject"
    fingerprint = compute_family_fingerprint(
        rule_id=rule_id,
        subject_key=subject_key,
        scope_kind="active-plan",
    )
    confirmed_ids: list[str] = []
    enriched: list[dict[str, Any]] = []
    for index, raw in enumerate(reported_findings):
        finding = dict(raw)
        finding_id = str(finding.get("id") or f"finding-{index + 1:02d}")
        finding["id"] = finding_id
        finding.setdefault("family_id", family_id)
        target_refs = finding.get("target_refs") or ["item-root"]
        item_id = str(target_refs[0]) if target_refs else "item-root"
        if finding.get("instance_ref") is None:
            finding["instance_ref"] = {
                "kind": "plan_item_field",
                "item_id": item_id,
                "field": "acceptance",
                "value_digest": digest_field_value(str(finding.get("issue") or "test")),
                "duplicate_ordinal": 0,
            }
        enriched.append(finding)
        confirmed_ids.append(finding_id)

    seed_id = confirmed_ids[0]
    family = {
        "id": family_id,
        "rule_id": rule_id,
        "subject_key": subject_key,
        "scope_kind": "active-plan",
        "title": "Synthetic test family",
        "seed_finding_id": seed_id,
        "confirmed_finding_ids": confirmed_ids,
        "candidate_refs": [],
        "recommended_change": str(enriched[0].get("recommended_change") or "Fix"),
        "discovery_sweep": {
            "searched_refs": ["active-items:*"],
            "search_dimensions": ["acceptance"],
            "completed": review_completed,
            "summary": "Synthetic discovery sweep.",
        },
    }
    return enriched, [family]


def _mandatory_plan_discovery_extras(
    store: Any,
    run_id: str,
    *,
    loop_id: str,
    target_revision: int,
    review_completed: bool,
    reported_findings: list[dict[str, Any]],
    finding_set_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        loop = store.load_review(run_id, loop_id)
    except Exception:
        return {}, reported_findings
    if loop.get("type") != "whole_plan":
        return {}, reported_findings
    if not _loop_uses_family_protocol(loop):
        return {}, reported_findings

    from top_down_planning.config.defaults import DEFAULT_CONFIG
    from top_down_planning.domain.mandatory_audit_passes import WHOLE_PLAN_AUDIT_PASS_IDS
    from top_down_planning.orchestrator.review_analysis_context import rubric_items_with_ids

    digest = mandatory_plan_digest(store, run_id)
    rubric_items = rubric_items_with_ids(
        [
            str(item)
            for item in DEFAULT_CONFIG["review"]["whole_plan"]["rubric"]
        ]
    )
    rubric_ids = [item["id"] for item in rubric_items]
    passes = [
        {
            "pass_id": pass_id,
            "completed": review_completed,
            "scope_id": "whole-plan-active-v1",
            "search_dimensions": ["acceptance"],
            "inspected_refs": ["active-items:*"],
            "rubric_item_ids": rubric_ids,
            "summary": f"Completed {pass_id}.",
        }
        for pass_id in WHOLE_PLAN_AUDIT_PASS_IDS
    ]
    enriched_findings, families = _synthetic_whole_plan_families(
        reported_findings,
        finding_set_id=finding_set_id,
        review_completed=review_completed,
    )
    extras: dict[str, Any] = {
        "audit_attestation": {
            "passes": passes,
        },
        "finding_families": families,
    }
    return extras, enriched_findings


def _synthetic_whole_output_families(
    reported_findings: list[dict[str, Any]],
    *,
    finding_set_id: str,
    review_completed: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not reported_findings:
        return reported_findings, []

    from top_down_planning.domain.artifact_refs import digest_field_value
    from top_down_planning.domain.finding_families import compute_family_fingerprint

    family_id = "family-test-output-default"
    rule_id = "custom.evidence-gap"
    rule_definition = "output evidence completeness gap"
    subject_key = "test-output-subject"
    fingerprint = compute_family_fingerprint(
        rule_id=rule_id,
        subject_key=subject_key,
        scope_kind="whole-output",
        rule_definition=rule_definition,
    )
    confirmed_ids: list[str] = []
    enriched: list[dict[str, Any]] = []
    for index, raw in enumerate(reported_findings):
        finding = dict(raw)
        finding_id = str(finding.get("id") or f"finding-{index + 1:02d}")
        finding["id"] = finding_id
        finding.setdefault("family_id", family_id)
        if finding.get("instance_ref") is None:
            finding["instance_ref"] = {
                "kind": "output_record",
                "record_kind": "evidence",
                "record_key": f"evidence-{index + 1:02d}",
                "field": "summary",
                "value_digest": digest_field_value(str(finding.get("issue") or "test")),
            }
        enriched.append(finding)
        confirmed_ids.append(finding_id)

    seed_id = confirmed_ids[0]
    family = {
        "id": family_id,
        "rule_id": rule_id,
        "subject_key": subject_key,
        "scope_kind": "whole-output",
        "rule_definition": rule_definition,
        "title": "Synthetic output test family",
        "seed_finding_id": seed_id,
        "confirmed_finding_ids": confirmed_ids,
        "candidate_refs": [],
        "recommended_change": str(enriched[0].get("recommended_change") or "Fix"),
        "discovery_sweep": {
            "searched_refs": ["production:*"],
            "search_dimensions": ["evidence"],
            "completed": review_completed,
            "summary": "Synthetic output discovery sweep.",
        },
    }
    return enriched, [family]


def _mandatory_output_discovery_extras(
    store: Any,
    run_id: str,
    *,
    loop_id: str,
    target_revision: int,
    review_completed: bool,
    reported_findings: list[dict[str, Any]],
    finding_set_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        loop = store.load_review(run_id, loop_id)
    except Exception:
        return {}, reported_findings
    if loop.get("type") != "whole_output":
        return {}, reported_findings
    if not _loop_uses_family_protocol(loop):
        return {}, reported_findings

    from top_down_planning.config.defaults import DEFAULT_CONFIG
    from top_down_planning.domain.mandatory_audit_passes import WHOLE_OUTPUT_AUDIT_PASS_IDS
    from top_down_planning.orchestrator.review_analysis_context import rubric_items_with_ids

    digest = mandatory_output_digest(store, run_id)
    rubric_items = rubric_items_with_ids(
        [
            str(item)
            for item in DEFAULT_CONFIG["review"]["whole_output"]["rubric"]
        ]
    )
    rubric_ids = [item["id"] for item in rubric_items]
    passes = [
        {
            "pass_id": pass_id,
            "completed": review_completed,
            "scope_id": "whole-output-active-v1",
            "search_dimensions": ["evidence"],
            "inspected_refs": ["production:*"],
            "rubric_item_ids": rubric_ids,
            "summary": f"Completed {pass_id}.",
        }
        for pass_id in WHOLE_OUTPUT_AUDIT_PASS_IDS
    ]
    enriched_findings, families = _synthetic_whole_output_families(
        reported_findings,
        finding_set_id=finding_set_id,
        review_completed=review_completed,
    )
    extras: dict[str, Any] = {
        "audit_attestation": {
            "passes": passes,
        },
        "finding_families": families,
    }
    return extras, enriched_findings


def mandatory_initial_respond_request(
    store: Any,
    run_id: str,
    *,
    loop_id: str,
    target_revision: int,
    review_type: str,
    decision: str = "approved",
    findings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    digest = (
        mandatory_plan_digest(store, run_id)
        if review_type == "whole_plan"
        else mandatory_output_digest(store, run_id)
    )
    try:
        loop = store.load_review(run_id, loop_id)
    except Exception:
        loop = {}
    finding_set_id = str(loop.get("finding_set_id") or "").strip()
    if not finding_set_id:
        finding_set_id = f"{loop_id}-fs-01"
    reported = _normalize_reported_findings(findings)
    payload: dict[str, Any] = {
        "loop_id": loop_id,
        "target_revision": target_revision,
        "stage": "initial_review",
        "finding_set_id": finding_set_id,
        "reported_findings": reported,
        "review_completed": decision != "blocked",
        "summary": (
            "Initial review clear."
            if decision == "approved" and not reported
            else "Initial review findings reported."
        ),
    }
    if decision == "blocked":
        payload["block_review"] = True
    if review_type == "whole_plan":
        payload["target_digest"] = digest
    elif decision == "approved" or review_type == "whole_output":
        payload["target_digest"] = digest
    if review_type == "whole_plan":
        extras, reported = _mandatory_plan_discovery_extras(
            store,
            run_id,
            loop_id=loop_id,
            target_revision=target_revision,
            review_completed=decision != "blocked",
            reported_findings=reported,
            finding_set_id=finding_set_id,
        )
        payload.update(extras)
        payload["reported_findings"] = reported
    elif review_type == "whole_output":
        extras, reported = _mandatory_output_discovery_extras(
            store,
            run_id,
            loop_id=loop_id,
            target_revision=target_revision,
            review_completed=decision != "blocked",
            reported_findings=reported,
            finding_set_id=finding_set_id,
        )
        payload.update(extras)
        payload["reported_findings"] = reported
    return payload


def mandatory_scope_review_respond_request(
    store: Any,
    run_id: str,
    *,
    loop_id: str,
    target_revision: int,
    review_type: str,
    findings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    digest = (
        mandatory_plan_digest(store, run_id)
        if review_type == "whole_plan"
        else mandatory_output_digest(store, run_id)
    )
    scope_id = "whole_plan" if review_type == "whole_plan" else "whole_output"
    try:
        loop = store.load_review(run_id, loop_id)
    except Exception:
        loop = {}
    finding_set_id = str(loop.get("finding_set_id") or "").strip()
    if not finding_set_id:
        finding_set_id = f"{loop_id}-fs-01"
    payload = {
        "loop_id": loop_id,
        "target_revision": target_revision,
        "stage": "scope_review",
        "finding_set_id": finding_set_id,
        "reported_findings": _normalize_reported_findings(findings),
        "review_completed": True,
        "target_digest": digest,
        "scope_id": scope_id,
        "acceptance_criteria_checked": ["Core Invariant"],
        "summary": "No remaining required findings.",
    }
    if review_type == "whole_plan":
        extras, reported = _mandatory_plan_discovery_extras(
            store,
            run_id,
            loop_id=loop_id,
            target_revision=target_revision,
            review_completed=True,
            reported_findings=payload["reported_findings"],
            finding_set_id=finding_set_id,
        )
        payload.update(extras)
        payload["reported_findings"] = reported
    elif review_type == "whole_output":
        extras, reported = _mandatory_output_discovery_extras(
            store,
            run_id,
            loop_id=loop_id,
            target_revision=target_revision,
            review_completed=True,
            reported_findings=payload["reported_findings"],
            finding_set_id=finding_set_id,
        )
        payload.update(extras)
        payload["reported_findings"] = reported
    return payload


def mandatory_scope_review_found_respond_request(
    store: Any,
    run_id: str,
    *,
    loop_id: str,
    target_revision: int,
    review_type: str,
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    digest = (
        mandatory_plan_digest(store, run_id)
        if review_type == "whole_plan"
        else mandatory_output_digest(store, run_id)
    )
    scope_id = "whole_plan" if review_type == "whole_plan" else "whole_output"
    try:
        loop = store.load_review(run_id, loop_id)
    except Exception:
        loop = {}
    finding_set_id = str(loop.get("finding_set_id") or "").strip()
    if not finding_set_id:
        finding_set_id = f"{loop_id}-fs-01"
    reported = _normalize_reported_findings(findings)
    payload: dict[str, Any] = {
        "loop_id": loop_id,
        "target_revision": target_revision,
        "stage": "scope_review",
        "finding_set_id": finding_set_id,
        "reported_findings": reported,
        "review_completed": True,
        "target_digest": digest,
        "scope_id": scope_id,
        "summary": "Required findings remain.",
    }
    if review_type == "whole_plan":
        extras, reported = _mandatory_plan_discovery_extras(
            store,
            run_id,
            loop_id=loop_id,
            target_revision=target_revision,
            review_completed=True,
            reported_findings=reported,
            finding_set_id=finding_set_id,
        )
        payload.update(extras)
        payload["reported_findings"] = reported
    elif review_type == "whole_output":
        extras, reported = _mandatory_output_discovery_extras(
            store,
            run_id,
            loop_id=loop_id,
            target_revision=target_revision,
            review_completed=True,
            reported_findings=reported,
            finding_set_id=finding_set_id,
        )
        payload.update(extras)
        payload["reported_findings"] = reported
    return payload


def _synthetic_family_verification_results(
    store: Any,
    run_id: str,
    *,
    loop_id: str,
    target_revision: int,
    review_type: str,
    disposition: str = "closed",
) -> list[dict[str, Any]]:
    try:
        loop = store.load_review(run_id, loop_id)
    except Exception:
        return []
    if not _loop_uses_family_protocol(loop):
        return []
    families = loop.get("finding_families") or []
    if not families:
        return []
    digest = (
        mandatory_plan_digest(store, run_id)
        if review_type == "whole_plan"
        else mandatory_output_digest(store, run_id)
    )
    if review_type == "whole_plan":
        searched_refs = ["active-items:*"]
        search_dimensions = ["acceptance"]
    else:
        searched_refs = ["production:*"]
        search_dimensions = ["evidence"]
    results: list[dict[str, Any]] = []
    for family in families:
        family_id = str(family.get("id") or "").strip()
        if not family_id:
            continue
        results.append(
            {
                "family_id": family_id,
                "disposition": disposition,
                "verification_sweep": {
                    "completed": True,
                    "searched_refs": searched_refs,
                    "search_dimensions": search_dimensions,
                    "remaining_instance_refs": [],
                    "summary": "No remaining policy-relevant instances.",
                },
                "remaining_instance_findings": [],
            }
        )
    return results


def mandatory_verification_respond_request(
    store: Any,
    run_id: str,
    *,
    loop_id: str,
    target_revision: int,
    review_type: str,
    finding_set_id: str,
    finding_results: list[dict[str, Any]],
) -> dict[str, Any]:
    digest = (
        mandatory_plan_digest(store, run_id)
        if review_type == "whole_plan"
        else mandatory_output_digest(store, run_id)
    )
    payload: dict[str, Any] = {
        "loop_id": loop_id,
        "target_revision": target_revision,
        "stage": "finding_verification",
        "decision": "verified",
        "finding_set_id": finding_set_id,
        "finding_results": finding_results,
        "new_direct_side_effect_findings": [],
        "target_digest": digest,
        "summary": "Findings verified.",
    }
    family_results = _synthetic_family_verification_results(
        store,
        run_id,
        loop_id=loop_id,
        target_revision=target_revision,
        review_type=review_type,
    )
    if family_results:
        payload["family_results"] = family_results
    return payload


def mandatory_verification_needs_revision_request(
    store: Any,
    run_id: str,
    *,
    loop_id: str,
    target_revision: int,
    review_type: str,
    finding_set_id: str,
    finding_results: list[dict[str, Any]],
) -> dict[str, Any]:
    digest = (
        mandatory_plan_digest(store, run_id)
        if review_type == "whole_plan"
        else mandatory_output_digest(store, run_id)
    )
    payload: dict[str, Any] = {
        "loop_id": loop_id,
        "target_revision": target_revision,
        "stage": "finding_verification",
        "decision": "needs_revision",
        "finding_set_id": finding_set_id,
        "finding_results": finding_results,
        "new_direct_side_effect_findings": [],
        "target_digest": digest,
        "summary": "Findings still need revision.",
    }
    family_results = _synthetic_family_verification_results(
        store,
        run_id,
        loop_id=loop_id,
        target_revision=target_revision,
        review_type=review_type,
        disposition="open",
    )
    if family_results:
        payload["family_results"] = family_results
    return payload


def whole_plan_approval_record(store: Any, run_id: str, **fields: Any) -> dict[str, Any]:
    from top_down_planning.domain.session_bindings import reviewer_binding_for_provider_session
    from top_down_planning.persistence.digests import compute_plan_digest

    digests = approved_digests_from_run(store, run_id)
    plan_digest = mandatory_plan_digest(store, run_id)
    digests["plan"] = plan_digest
    scope_review_result_payload = {
        "stage": "scope_review",
        "target_digest": plan_digest,
        "scope_id": "whole_plan",
        "decision": "approved",
        "reported_findings": [],
        "acceptance_criteria_checked": ["Core Invariant"],
        "summary": "Approved.",
    }
    binding = reviewer_binding_for_provider_session(
        "stub-session-reviewer",
        instance_seed="review-whole-plan-01",
    )
    payload: dict[str, Any] = {
        "id": "review-whole-plan-01",
        "type": "whole_plan",
        "revise_at": "blocker",
        "review_record_schema_version": 2,
        "review_contract_version": 2,
        "reviewer_binding": binding.to_dict() if binding is not None else None,
        "target_revision": 0,
        "scope": {"kind": "whole_plan"},
        "status": "approved",
        "findings": [],
        "revision_cycles": 0,
        "approved_digests": digests,
        "lifecycle_status": "approved",
        "active_stage": "scope_review",
        "scope_review_rounds": 1,
        "revise_at": "blocker",
        "scope_review_result": scope_review_result_payload,
    }
    payload.update(fields)
    if "reviewer_session_id" in payload:
        session_id = str(payload.pop("reviewer_session_id") or "").strip() or None
        if session_id and "reviewer_binding" not in payload:
            binding = reviewer_binding_for_provider_session(
                session_id,
                instance_seed=str(payload.get("id") or ""),
            )
            if binding is not None:
                payload["reviewer_binding"] = binding.to_dict()
    return payload


def whole_output_approval_record(store: Any, run_id: str, **fields: Any) -> dict[str, Any]:
    from top_down_planning.persistence.digests import compute_output_digest

    digests = approved_digests_from_run(store, run_id, keys=OUTPUT_APPROVAL_DIGEST_KEYS)
    production = store.load_production(run_id)
    digests["output"] = compute_output_digest(production)
    from top_down_planning.domain.session_bindings import reviewer_binding_for_provider_session

    binding = reviewer_binding_for_provider_session(
        "stub-session-output-reviewer",
        instance_seed="review-whole-output-01",
    )
    payload: dict[str, Any] = {
        "id": "review-whole-output-01",
        "type": "whole_output",
        "revise_at": "blocker",
        "reviewer_binding": binding.to_dict() if binding is not None else None,
        "target_revision": int(production["output_revision"]),
        "scope": {"kind": "whole_output"},
        "status": "approved",
        "findings": [],
        "revision_cycles": 0,
        "approved_digests": digests,
        "lifecycle_status": "approved",
        "active_stage": "scope_review",
        "scope_review_rounds": 1,
        "revise_at": "blocker",
        "scope_review_result": {
            "stage": "scope_review",
            "target_digest": digests["output"],
            "scope_id": "whole_output",
            "decision": "approved",
            "reported_findings": [],
            "acceptance_criteria_checked": ["Core Invariant"],
            "summary": "Approved.",
        },
    }
    payload.update(fields)
    if "reviewer_session_id" in payload:
        session_id = str(payload.pop("reviewer_session_id") or "").strip() or None
        if session_id and "reviewer_binding" not in payload:
            binding = reviewer_binding_for_provider_session(
                session_id,
                instance_seed=str(payload.get("id") or ""),
            )
            if binding is not None:
                payload["reviewer_binding"] = binding.to_dict()
    return payload


def accept_child_run(
    store: Any,
    child_run_id: str,
    *,
    outputs: list[dict[str, Any]] | None = None,
    contributions: list[dict[str, Any]] | None = None,
    claim_assessment: str = "Unit goal met.",
) -> dict[str, Any]:
    """Finalize a prepared child through production apply and whole-output approval."""

    from top_down_planning.orchestrator.phases import OUTPUT_VALIDATED, PRODUCTION
    from top_down_planning.package.builder import digest_review_record
    from top_down_planning.persistence.digests import compute_output_digest
    from top_down_planning.workspace import run_workspace

    plan = store.load_plan_model(child_run_id)
    workspace = run_workspace(store.load_run(child_run_id))
    work_item_ids = [
        item_id for item_id, item in plan.items.items() if item.kind == "work"
    ]
    run = store.load_run(child_run_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["phase"] = PRODUCTION
    store.save_run(child_run_id, run, expected)

    output_id = f"output-{child_run_id[-6:]}"
    batch_outputs = outputs or [
        {"id": output_id, "type": "artifact", "ref": "temp/out.md"},
    ]
    for item in batch_outputs:
        ref = str(item.get("ref") or "")
        if ref:
            artifact_path = workspace / ref
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            if not artifact_path.is_file():
                artifact_path.write_text("accepted child output\n", encoding="utf-8")
    batch_contributions = contributions
    if batch_contributions is None:
        root_item = work_item_ids[0] if work_item_ids else next(iter(plan.items))
        batch_contributions = [
            {
                "item_id": root_item,
                "output_refs": [str(item.get("id") or output_id) for item in batch_outputs],
                "summary": claim_assessment,
            }
        ]

    apply_production(
        store,
        child_run_id,
        {
            "production_revision": int(store.load_production(child_run_id)["revision"]),
            "plan_items": work_item_ids,
            "dispositions": {
                item_id: {"disposition": "completed", "evidence": "done"}
                for item_id in work_item_ids
            },
            "outputs": batch_outputs,
            "contributions": batch_contributions,
            "summary": "batch complete",
            "empty_output": False,
        },
        handler="apply",
    )()
    apply_production(
        store,
        child_run_id,
        {"goal_assessment": claim_assessment},
        handler="submit_completion",
    )()

    from top_down_planning.config import recompute_context_snapshot_binding

    config = store.load_resolved_config(child_run_id)
    new_binding, new_snapshot_digest = recompute_context_snapshot_binding(
        config,
        workspace=workspace,
    )
    run = store.load_run(child_run_id)
    expected = int(run["revision"])
    run = dict(run)
    digests = dict(run.get("digests") or {})
    digests["context_snapshot"] = new_snapshot_digest
    run["digests"] = digests
    run["context_snapshot_binding"] = new_binding
    run["revision"] = expected + 1
    store.save_run(child_run_id, run, expected)

    approval = whole_output_approval_record(store, child_run_id)
    store.save_review(child_run_id, approval)
    production = store.load_production(child_run_id)
    output_digest = compute_output_digest(production)
    run = store.load_run(child_run_id)
    expected = int(run["revision"])
    run = dict(run)
    digests = dict(run.get("digests") or {})
    digests["output"] = output_digest
    run["digests"] = digests
    binding = dict(run.get("package_binding") or {})
    binding["whole_output_review_id"] = str(approval.get("id") or "")
    binding["whole_output_review_digest"] = digest_review_record(approval)
    run["package_binding"] = binding
    run["revision"] = expected + 1
    run["status"] = "completed"
    run["phase"] = OUTPUT_VALIDATED
    run["outcome"] = "accepted"
    store.save_run(child_run_id, run, expected)
    return store.load_run(child_run_id)


def save_review_payload(store: Any, run_id: str, payload: dict[str, Any]) -> None:
    data = dict(payload)
    loop_type = str(data.get("type") or "")
    if loop_type in {"whole_plan", "whole_output"}:
        if data.get("review_contract_version") is None:
            data["review_contract_version"] = 2
        if data.get("review_record_schema_version") is None:
            data["review_record_schema_version"] = 2
    store.save_review(run_id, review_loop_dict_with_binding(data))


def grant_capability(
    store: Any,
    run_id: str,
    *,
    role: str,
    phase: str | None = None,
    session_kind: str = "primary",
    session_id: str | None = None,
    loop_id: str | None = None,
) -> str:
    """Issue a session capability token and return its serialized value."""

    from top_down_planning.orchestrator.capability import issue_session_capability
    from top_down_planning.persistence.session_bindings import primary_provider_session_id

    if phase is None:
        phase = PLANNING if role == "planner" else PRODUCTION

    run = store.load_run(run_id)
    sessions = dict(run.get("sessions") or {})
    config = store.load_resolved_config(run_id)
    workspace = store.root

    if role == "planner":
        if session_id is not None:
            resolved_session_id = session_id
        else:
            resolved_session_id = (
                primary_provider_session_id(run, "planner") or "test-planner-session"
            )
        if primary_provider_session_id(run, "planner") is None:
            expected = int(run["revision"])
            run = dict(run)
            run["revision"] = expected + 1
            run["sessions"] = bind_primary_session_for_tests(
                sessions,
                role="planner",
                provider_session_id=resolved_session_id,
                config=config,
                workspace=workspace,
            )
            store.save_run(run_id, run, expected)
    elif role == "producer":
        if session_id is not None:
            resolved_session_id = session_id
        else:
            resolved_session_id = (
                primary_provider_session_id(run, "producer") or "test-producer-session"
            )
        if primary_provider_session_id(run, "producer") is None:
            expected = int(run["revision"])
            run = dict(run)
            run["revision"] = expected + 1
            run["sessions"] = bind_primary_session_for_tests(
                sessions,
                role="producer",
                provider_session_id=resolved_session_id,
                config=config,
                workspace=workspace,
            )
            store.save_run(run_id, run, expected)
    else:
        resolved_session_id = session_id or "test-reviewer-session"

    resolved_loop_id: str | None = None
    if session_kind == "reviewer" or role == "reviewer":
        resolved_loop_id = loop_id or "review-test-loop"
        from top_down_planning.domain.reviews import ReviewLoop

        try:
            loop = ReviewLoop.from_dict(store.load_review(run_id, resolved_loop_id))
        except Exception:
            loop = make_review_loop(
                id=resolved_loop_id,
                type="focused_output",
                target_revision=0,
                scope={"kind": "focused_output"},
                revise_at="blocker",
                reviewer_session_id=resolved_session_id,
            )
            save_review_payload(store, run_id, loop.to_dict())
        else:
            from top_down_planning.domain.session_bindings import (
                is_transient_provider_session_id,
            )
            from top_down_planning.persistence.session_bindings import (
                primary_provider_session_id,
            )

            current_session_id = loop.reviewer_session_id
            if (
                current_session_id
                and not is_transient_provider_session_id(current_session_id)
                and is_transient_provider_session_id(resolved_session_id)
            ):
                resolved_session_id = current_session_id
            elif loop.reviewer_session_id != resolved_session_id:
                run = store.load_run(run_id)
                primary_ids = {
                    sid
                    for sid in (
                        primary_provider_session_id(run, "planner"),
                        primary_provider_session_id(run, "producer"),
                    )
                    if sid
                }
                if resolved_session_id not in primary_ids:
                    updated = loop.with_reviewer_provider_session_id(resolved_session_id)
                    save_review_payload(store, run_id, updated.to_dict())

    return issue_session_capability(
        store,
        run_id,
        role=role,
        phase=phase,
        session_id=resolved_session_id,
        session_kind=session_kind,
        loop_id=resolved_loop_id,
    )


def set_capability_token_file(
    monkeypatch: Any,
    store: Any,
    run_id: str,
    token: str | None,
) -> Path | None:
    """Write the active capability token file and export its path for CLI tests."""

    if token is None:
        monkeypatch.delenv(CAPABILITY_TOKEN_FILE_ENV_VAR, raising=False)
        clear_capability_token_file(store, run_id)
        return None
    path = write_capability_token_file(store, run_id, token)
    monkeypatch.setenv(CAPABILITY_TOKEN_FILE_ENV_VAR, str(path))
    return path


def write_agent_request_file(
    store: Any,
    run_id: str,
    filename: str,
    payload: dict[str, Any],
) -> Path:
    """Write a mutating agent request under the run's agent-requests/ directory."""

    path = store.agent_requests_dir(run_id) / filename
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def enter_mandatory_verification_pending(
    store: Any,
    run_id: str,
    loop_id: str,
    *,
    target_revision: int,
    finding_set_id: str | None = None,
) -> None:
    """Enter finding_verification using mandatory lifecycle domain transitions."""

    from dataclasses import replace

    from top_down_planning.domain.reviews import ReviewLoop
    from top_down_planning.orchestrator.mandatory_review_stages import (
        mark_findings_open,
        mark_revision_in_progress,
        mark_verification_pending,
    )

    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    if int(loop.target_revision) != target_revision:
        loop = replace(loop, target_revision=target_revision)
    if finding_set_id is not None:
        loop = replace(loop, finding_set_id=finding_set_id)

    current = loop.lifecycle_status or "review_pending"
    if current == "verification_pending":
        loop = mark_verification_pending(loop, target_revision=target_revision)
    elif current == "revision_in_progress":
        loop = mark_verification_pending(loop, target_revision=target_revision)
    elif current == "findings_open":
        loop = mark_revision_in_progress(loop)
        loop = mark_verification_pending(loop, target_revision=target_revision)
    elif current == "scope_review_pending":
        loop = mark_findings_open(loop)
        loop = mark_revision_in_progress(loop)
        loop = mark_verification_pending(loop, target_revision=target_revision)
    elif current == "review_pending":
        loop = mark_findings_open(loop)
        loop = mark_revision_in_progress(loop)
        loop = mark_verification_pending(loop, target_revision=target_revision)
    else:
        raise ValueError(
            f"cannot enter mandatory verification from lifecycle {current!r}"
        )
    save_review_payload(store, run_id, loop.to_dict())


def set_loop_revise_at(
    store: Any,
    run_id: str,
    loop_id: str,
    *,
    revise_at: str,
) -> ReviewLoop:
    """Update persisted ``revise_at`` on a review loop."""

    from dataclasses import replace

    from top_down_planning.domain.reviews import ReviewLoop

    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    loop = replace(loop, revise_at=revise_at)
    save_review_payload(store, run_id, loop.to_dict())
    return loop


def seed_mandatory_scope_review_decision_loop(
    store: Any,
    run_id: str,
    loop_id: str,
    *,
    decision: str = "approved",
    target_revision: int | None = None,
) -> ReviewLoop:
    """Seed a scope-review loop with a recorded decision (orchestration branch tests)."""

    from dataclasses import replace

    from top_down_planning.domain.reviews import ReviewLoop, SCOPE_REVIEW_STAGE

    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    if target_revision is not None:
        loop = replace(loop, target_revision=target_revision)
    loop = replace(
        loop,
        status="approved",
        lifecycle_status="scope_review_pending",
        active_stage=SCOPE_REVIEW_STAGE,
        scope_review_result={"decision": decision, "summary": "seeded scope decision"},
    )
    save_review_payload(store, run_id, loop.to_dict())
    return loop


def seed_mandatory_interrupted_owner_revision_loop(
    store: Any,
    run_id: str,
    loop_id: str,
) -> ReviewLoop:
    """Seed an owner revision cycle that started but never consumed a primary turn."""

    from dataclasses import replace

    from top_down_planning.domain.reviews import ReviewLoop
    from top_down_planning.orchestrator.mandatory_review_stages import (
        enter_owner_revision_cycle,
        mark_findings_open,
    )

    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    loop = mark_findings_open(loop)
    loop = enter_owner_revision_cycle(replace(loop, revision_cycles=1))
    save_review_payload(store, run_id, loop.to_dict())
    return loop


def script_verification_then_scope_review_approval(
    provider: Any,
    store: Any,
    run_id: str,
    *,
    loop_id: str,
    phase: str,
    target_revision: int,
    findings: list[dict[str, Any]] | None = None,
    finding_set_id: str | None = None,
    finding_results: list[dict[str, Any]] | None = None,
) -> None:
    """After a recheck delivery, script verification approve then fresh scope_review approve."""

    review_type = "whole_plan" if "plan" in phase else "whole_output"
    loop_payload = dict(store.load_review(run_id, loop_id))
    resolved_finding_set_id = finding_set_id or str(
        loop_payload.get("finding_set_id") or f"{loop_id}-fs-01"
    )
    enter_mandatory_verification_pending(
        store,
        run_id,
        loop_id,
        target_revision=target_revision,
        finding_set_id=resolved_finding_set_id,
    )
    loop_payload = dict(store.load_review(run_id, loop_id))

    resolved_results = finding_results
    if resolved_results is None:
        resolved_results = [
            {
                "finding_id": finding["id"],
                "disposition": "resolved",
                "evidence": ["verified"],
                "direct_side_effects": [],
            }
            for finding in (loop_payload.get("findings") or [])
            if finding.get("severity") == "blocker"
            and finding.get("status") in {"unresolved", "partially_resolved"}
        ]
    respond_review(
        store,
        run_id,
        mandatory_verification_respond_request(
            store,
            run_id,
            loop_id=loop_id,
            target_revision=target_revision,
            review_type=review_type,
            finding_set_id=resolved_finding_set_id,
            finding_results=resolved_results,
        ),
        phase=phase,
        loop_id=loop_id,
    )()
    prepare_loop_for_scope_review_respond(
        store,
        run_id,
        loop_id,
        target_revision=target_revision,
    )
    respond_review(
        store,
        run_id,
        mandatory_scope_review_respond_request(
            store,
            run_id,
            loop_id=loop_id,
            target_revision=target_revision,
            review_type=review_type,
            findings=findings,
        ),
        phase=phase,
        loop_id=loop_id,
    )()


def prepare_loop_for_scope_review_respond(
    store: Any,
    run_id: str,
    loop_id: str,
    *,
    target_revision: int,
) -> None:
    """Align loop state for a scope_review respond (orchestrator-equivalent)."""

    from dataclasses import replace

    from top_down_planning.domain.reviews import ReviewLoop
    from top_down_planning.orchestrator.mandatory_review_stages import (
        prepare_scope_review_loop,
    )

    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    if loop.target_revision != target_revision:
        loop = replace(loop, target_revision=target_revision)
    loop = prepare_scope_review_loop(loop)
    save_review_payload(store, run_id, loop.to_dict())


def script_mandatory_clear_approval(
    provider: Any,
    store: Any,
    run_id: str,
    *,
    loop_id: str,
    phase: str,
    target_revision: int,
    findings: list[dict[str, Any]] | None = None,
) -> None:
    """Script initial approve plus fresh scope_review approve (clear path)."""

    review_type = "whole_plan" if "plan" in phase else "whole_output"
    respond_review(
        store,
        run_id,
        mandatory_initial_respond_request(
            store,
            run_id,
            loop_id=loop_id,
            target_revision=target_revision,
            review_type=review_type,
            findings=findings,
        ),
        phase=phase,
        loop_id=loop_id,
    )()
    prepare_loop_for_scope_review_respond(
        store,
        run_id,
        loop_id,
        target_revision=target_revision,
    )
    respond_review(
        store,
        run_id,
        mandatory_scope_review_respond_request(
            store,
            run_id,
            loop_id=loop_id,
            target_revision=target_revision,
            review_type=review_type,
        ),
        phase=phase,
        loop_id=loop_id,
    )()


class StallingAfterEventsProvider(StubProvider):
    """Simulate a provider turn that stalls after scripted events (no done)."""

    def __init__(self, *, stall_timeout_seconds: float = 0.5) -> None:
        super().__init__()
        self._stall_timeout_seconds = stall_timeout_seconds
        self._stream_started = threading.Event()
        self._active_abort_release: threading.Event | None = None

    def stream_events(self, session_id: str):
        if session_id in self._not_found_sessions:
            raise ProviderSessionNotFoundError(
                f"provider session not found: {session_id}",
                provider="stub",
                session_id=session_id,
            )
        session = self._require_session(session_id)
        abort_release = threading.Event()
        self._active_abort_release = abort_release
        self._stream_started.set()
        saw_done = False
        if session.pending_hook is not None:
            hook = session.pending_hook
            session.pending_hook = None
            hook()
        while session.pending_events:
            event = session.pending_events.popleft()
            if event.get("type") == "done":
                saw_done = True
            yield event
        if not saw_done:
            try:
                if not abort_release.wait(timeout=self._stall_timeout_seconds):
                    raise AssertionError(
                        "StallingAfterEventsProvider stalled without abort_turn "
                        f"(timeout={self._stall_timeout_seconds}s)"
                    )
            finally:
                if self._active_abort_release is abort_release:
                    self._active_abort_release = None

    def abort_turn(self, session_id: str) -> None:
        if self._active_abort_release is not None:
            self._active_abort_release.set()
        super().abort_turn(session_id)


def done_events(*, signal: str | None = None, text: str = "ok") -> list[dict]:
    events = [
        {"type": "assistant", "text": text},
        {"type": "done", "subtype": "success", "text": text, "is_error": False},
    ]
    if signal is not None:
        events[-1]["signal"] = signal
    return events


def script_planning_candidate_ready(
    provider: Any,
    *,
    signal: str | None = "candidate_plan_ready",
    text: str = "ready",
) -> None:
    """Script a provider turn that signals planning completion."""

    provider.script_turn(done_events(signal=signal, text=text))


def apply_plan(
    store: Any,
    run_id: str,
    *,
    base_revision: int,
    operations: list[dict],
    role: str = "planner",
    phase: str | None = None,
) -> Any:
    from top_down_planning.agent_tool import PlanAgentService

    resolved_phase = phase or (PLANNING if role == "planner" else PRODUCTION)

    def mutate() -> None:
        token = grant_capability(store, run_id, role=role, phase=resolved_phase)
        PlanAgentService(store, run_id).apply(
            {"base_revision": base_revision, "operations": operations},
            capability_token=token,
        )

    return mutate


def request_focused_review(
    store: Any,
    run_id: str,
    request: dict[str, Any],
    *,
    role: str = "planner",
    phase: str = PLANNING,
) -> Any:
    from top_down_planning.agent_tool import ReviewAgentService

    def mutate() -> None:
        token = grant_capability(store, run_id, role=role, phase=phase)
        ReviewAgentService(store, run_id).request(request, capability_token=token)

    return mutate


def enrich_mandatory_review_respond_payload(
    store: Any,
    run_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Add audit attestation and finding families to mandatory discovery responds."""

    enriched = dict(payload)
    loop_id = str(enriched.get("loop_id") or "").strip()
    if not loop_id:
        return enriched
    try:
        loop = store.load_review(run_id, loop_id)
    except Exception:
        return enriched
    loop_type = str(loop.get("type") or "")
    if loop_type not in {"whole_plan", "whole_output"}:
        return enriched
    if not _loop_uses_family_protocol(loop):
        return enriched
    stage = str(enriched.get("stage") or "").strip()
    finding_set_id = str(enriched.get("finding_set_id") or loop.get("finding_set_id") or "").strip()
    if not finding_set_id:
        finding_set_id = f"{loop_id}-fs-01"
        enriched["finding_set_id"] = finding_set_id
    target_revision = int(enriched.get("target_revision") or 0)
    review_completed = bool(enriched.get("review_completed"))
    if stage in {"initial_review", "scope_review"} and "reported_findings" in enriched:
        reported_findings = list(enriched.get("reported_findings") or [])
        if loop_type == "whole_plan":
            extras, reported = _mandatory_plan_discovery_extras(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=target_revision,
                review_completed=review_completed,
                reported_findings=reported_findings,
                finding_set_id=finding_set_id,
            )
        else:
            extras, reported = _mandatory_output_discovery_extras(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=target_revision,
                review_completed=review_completed,
                reported_findings=reported_findings,
                finding_set_id=finding_set_id,
            )
        enriched.update(extras)
        enriched["reported_findings"] = reported
    elif stage == "finding_verification" and "family_results" not in enriched:
        decision = str(enriched.get("decision") or "").strip()
        disposition = "open" if decision == "needs_revision" else "closed"
        family_results = _synthetic_family_verification_results(
            store,
            run_id,
            loop_id=loop_id,
            target_revision=target_revision,
            review_type=loop_type,
            disposition=disposition,
        )
        if family_results:
            enriched["family_results"] = family_results
    return enriched


def enrich_whole_plan_review_respond_payload(
    store: Any,
    run_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Add audit attestation and finding families to whole-plan discovery responds."""

    return enrich_mandatory_review_respond_payload(store, run_id, payload)


def respond_review(
    store: Any,
    run_id: str,
    request: dict[str, Any],
    *,
    role: str = "reviewer",
    phase: str = PLANNING,
    loop_id: str | None = None,
    session_id: str | None = None,
) -> Any:
    from top_down_planning.agent_tool import ReviewAgentService
    from top_down_planning.persistence.capabilities import (
        capability_token_file_path,
        read_capability_token_file,
    )

    resolved_loop_id = loop_id or str(request.get("loop_id") or "")

    def mutate() -> None:
        from top_down_planning.domain.session_bindings import binding_provider_session_id

        resolved_session_id = session_id
        if resolved_session_id is None and resolved_loop_id:
            try:
                loop = store.load_review(run_id, resolved_loop_id)
                loop_session = binding_provider_session_id(loop.get("reviewer_binding"))
                if isinstance(loop_session, str) and loop_session:
                    resolved_session_id = loop_session
            except Exception:
                pass
        if role == "reviewer":
            # Orchestrator persists planner/producer tokens to the shared file during
            # active turns; never reuse that token for reviewer respond mutations.
            token = grant_capability(
                store,
                run_id,
                role=role,
                phase=phase,
                loop_id=resolved_loop_id,
                session_id=resolved_session_id,
            )
        else:
            token_path = capability_token_file_path(store, run_id)
            file_token = (
                read_capability_token_file(token_path) if token_path.exists() else None
            )
            token = file_token or grant_capability(
                store,
                run_id,
                role=role,
                phase=phase,
                loop_id=resolved_loop_id,
                session_id=resolved_session_id,
            )
        payload = dict(request)
        if resolved_loop_id and (
            "reported_findings" in payload or "review_completed" in payload
        ):
            try:
                from top_down_planning.domain.reviews import (
                    ReviewLoop,
                    allocate_discovery_finding_set_id,
                )

                loop = store.load_review(run_id, resolved_loop_id)
                finding_set_id = str(loop.get("finding_set_id") or "").strip()
                if not finding_set_id:
                    loop_model, finding_set_id = allocate_discovery_finding_set_id(
                        ReviewLoop.from_dict(loop)
                    )
                    save_review_payload(store, run_id, loop_model.to_dict())
                payload["finding_set_id"] = finding_set_id
            except Exception:
                pass
        payload = enrich_mandatory_review_respond_payload(store, run_id, payload)
        ReviewAgentService(store, run_id).respond(payload, capability_token=token)

    return mutate


def apply_production(
    store: Any,
    run_id: str,
    request: dict[str, Any],
    *,
    handler: str,
    role: str = "producer",
    phase: str = PRODUCTION,
) -> Any:
    from top_down_planning.agent_tool import ProductionAgentService

    def mutate() -> None:
        token = grant_capability(store, run_id, role=role, phase=phase)
        ProductionAgentService(store, run_id).__getattribute__(handler)(
            request,
            capability_token=token,
        )

    return mutate


def enrich_record_finding_actions_request(
    store: Any,
    run_id: str,
    request: dict[str, Any],
) -> dict[str, Any]:
    enriched = dict(request)
    loop_id = str(enriched.get("loop_id") or "").strip()
    if not loop_id:
        return enriched
    try:
        loop = store.load_review(run_id, loop_id)
    except Exception:
        return enriched
    loop_type = str(loop.get("type") or "")
    if loop_type in {"whole_output", "focused_output"}:
        production = store.load_production(run_id)
        target_revision = int(production["output_revision"])
        from top_down_planning.persistence.digests import compute_output_digest

        target_digest = compute_output_digest(production)
    else:
        plan = store.load_plan(run_id)
        target_revision = int(plan["revision"])
        from top_down_planning.persistence.digests import compute_plan_digest

        target_digest = compute_plan_digest(plan)
    enriched.setdefault("target_revision", target_revision)
    enriched.setdefault("target_digest", target_digest)
    finding_set_id = str(
        enriched.get("finding_set_id") or loop.get("finding_set_id") or ""
    ).strip()
    if finding_set_id:
        enriched.setdefault("finding_set_id", finding_set_id)
    return enriched


def record_finding_actions(
    store: Any,
    run_id: str,
    request: dict[str, Any],
    *,
    role: str = "planner",
    phase: str = PLANNING,
    loop_id: str | None = None,
) -> Any:
    from top_down_planning.agent_tool import ReviewAgentService

    resolved_loop_id = loop_id or str(request.get("loop_id") or "")

    def mutate() -> None:
        token = grant_capability(
            store,
            run_id,
            role=role,
            phase=phase,
            loop_id=resolved_loop_id,
        )
        ReviewAgentService(store, run_id).record_finding_actions(
            enrich_record_finding_actions_request(store, run_id, request),
            capability_token=token,
        )

    return mutate


def only_run_id(store: Any) -> str:
    """Return the sole run directory id under a test store root."""

    run_dirs = sorted(
        path.name
        for path in store.root.iterdir()
        if path.is_dir() and path.name.startswith("run-")
    )
    if len(run_dirs) != 1:
        raise AssertionError(f"expected exactly one run in store, found {run_dirs}")
    return run_dirs[0]


def request_amendment(
    store: Any,
    run_id: str,
    request: dict[str, Any],
    *,
    role: str = "producer",
    phase: str = PRODUCTION,
) -> Any:
    from top_down_planning.agent_tool import ProductionAgentService

    def mutate() -> None:
        token = grant_capability(store, run_id, role=role, phase=phase)
        ProductionAgentService(store, run_id).request_amendment(
            request,
            capability_token=token,
        )

    return mutate


def plan_apply_turn(
    *,
    base_revision: int = 0,
    operations: list[dict],
    signal: str = "candidate_plan_ready",
    assistant_text: str = "planning turn",
) -> list[dict]:
    """Return provider events for a planning turn that signals completion only."""

    del base_revision, operations
    return done_events(signal=signal, text=assistant_text)

