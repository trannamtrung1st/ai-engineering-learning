"""Shared helpers for top_down_planning tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.domain.approval_digests import (
    OUTPUT_APPROVAL_DIGEST_KEYS,
    PLAN_APPROVAL_DIGEST_KEYS,
)
from top_down_planning.orchestrator.phases import PLANNING, PRODUCTION
from top_down_planning.persistence.capabilities import CAPABILITY_ENV_VAR


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


def sessions_with_primary_session(
    *,
    planner: str | None = None,
    producer: str | None = None,
) -> dict[str, Any]:
    from top_down_planning.persistence.session_bindings import update_primary_binding

    sessions: dict[str, Any] = {}
    if planner is not None:
        sessions = update_primary_binding(
            sessions,
            role="planner",
            provider_session_id=planner,
        )
    if producer is not None:
        sessions = update_primary_binding(
            sessions,
            role="producer",
            provider_session_id=producer,
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
            finding["category"] = "other"
        if "recommended_change" not in finding:
            raise ValueError("test finding fixtures require recommended_change")
        reported.append(finding)
    return reported


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
    if decision == "approved":
        payload["target_digest"] = digest
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
    return {
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
    return {
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
    return {
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
    return {
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


def save_review_payload(store: Any, run_id: str, payload: dict[str, Any]) -> None:
    store.save_review(run_id, review_loop_dict_with_binding(payload))


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
    from top_down_planning.persistence.session_bindings import (
        primary_provider_session_id,
        update_primary_binding,
    )

    if phase is None:
        phase = PLANNING if role == "planner" else PRODUCTION

    run = store.load_run(run_id)
    sessions = dict(run.get("sessions") or {})

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
            run["sessions"] = update_primary_binding(
                sessions,
                role="planner",
                provider_session_id=resolved_session_id,
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
            run["sessions"] = update_primary_binding(
                sessions,
                role="producer",
                provider_session_id=resolved_session_id,
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
            if loop.reviewer_session_id != resolved_session_id:
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


def set_capability_env(monkeypatch: Any, token: str | None) -> None:
    """Set or clear TDP_CAPABILITY_TOKEN for CLI and service tests."""

    if token is None:
        monkeypatch.delenv(CAPABILITY_ENV_VAR, raising=False)
    else:
        monkeypatch.setenv(CAPABILITY_ENV_VAR, token)


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
    loop_payload["lifecycle_status"] = "verification_pending"
    loop_payload["active_stage"] = "finding_verification"
    loop_payload["status"] = "pending"
    loop_payload["target_revision"] = target_revision
    resolved_finding_set_id = finding_set_id or str(
        loop_payload.get("finding_set_id") or f"{loop_id}-fs-01"
    )
    loop_payload["finding_set_id"] = resolved_finding_set_id
    save_review_payload(store, run_id, loop_payload)

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
        token = grant_capability(
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

