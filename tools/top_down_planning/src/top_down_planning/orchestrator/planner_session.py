"""Planner session manifest helpers."""

from __future__ import annotations

from typing import Any

from top_down_planning.domain.plan_tree import PLAN_ROOT_PLANNER_INSTRUCTION
from top_down_planning.domain.session_bindings import SessionBinding
from top_down_planning.persistence.session_bindings import (
    get_primary_binding,
    primary_provider_session_id,
)

PLANNER_CANDIDATE_READY_SIGNAL = "candidate_plan_ready"


def primary_planner_provider_session_id(run: dict[str, Any]) -> str | None:
    return primary_provider_session_id(run, "planner")


def primary_planner_binding(run: dict[str, Any]) -> SessionBinding | None:
    return get_primary_binding(run, "planner")


def build_planner_protocol_instructions() -> list[str]:
    """Provider-agnostic planner behavior instructions for session manifests."""

    return [
        (
            "You are the TDP planner. In the planning phase you expand the TDP "
            "plan tree stored in the run store. The phase name planning means "
            "plan-tree decomposition, not a host-IDE plan document or "
            "planning-only artifact."
        ),
        (
            "Mutate plan state only through the tdp agent plan shell commands "
            "in tool_instructions (snapshot, apply, check). Read-only workspace "
            "inspection is allowed."
        ),
        (
            "Do not switch to host planning modes or use planning-only tools. "
            "The orchestrator cannot consume those artifacts and the run will "
            "not advance."
        ),
        (
            "When the plan satisfies stop_hint and passes plan check, emit "
            "completion_signal as your final assistant line or as done.signal "
            "metadata."
        ),
        (
            "Discover request contracts with tdp agent readme, tdp agent "
            "schema, and tdp agent example. Packaged planner skills are "
            "already in agent_context.skills on this manifest."
        ),
        (
            "For new items in the same plan apply batch, set depends_on inline on "
            "add_item (stable ids or same-batch temp_id; string or array). See "
            "tdp agent example expand-branch."
        ),
        (
            "Write mutating request payloads only under $TDP_AGENT_REQUESTS_DIR. "
            "Do not create .tdp-* or .review-* dotfiles in the project workspace "
            "or harness folders. Do not modify orchestrator-owned run files."
        ),
        (
            "Plan field classification: required resulting truth → acceptance; "
            "material uncertainty or failure mode → risks; believed premise → "
            "assumptions; mandatory solution condition → constraints; operational "
            "guardrail → boundaries; owned work → scope; execution prerequisite → "
            "depends_on; requirement origin → source_refs on items (not scope.includes); "
            "non-binding advice → guidance/resources/skills or authoritative inputs. "
            "Do not place architecture suggestions in acceptance. Attach each risk "
            "to the lowest item that owns it; use plan-level risks only for "
            "cross-cutting threats. Do not duplicate the same risk at plan and item level. "
            "Do not convert every possible defect into a risk. "
            "Do not place source-document section names in scope.includes — use source_refs."
        ),
        (
            "Every work leaf must set item-level scope.includes (owned product "
            "capability), scope.excludes, and/or boundaries. Plan-level scope "
            "and boundaries do not satisfy this requirement. Keep spec "
            "traceability in source_refs, not scope.includes."
        ),
        (
            "When revising after whole-plan review, treat each finding family in "
            "active_families as one repair unit. Before applying a fix, search the "
            "whole active plan using the family's rule_id, subject_key, scope_kind, "
            "candidate_refs, and search dimensions. Include all confirmed and newly "
            "discovered equivalent locations in one plan apply transaction where "
            "possible. List optional family members explicitly in target_finding_ids; "
            "required open members default when omitted. Record a completed owner "
            "sweep with empty remaining_instance_refs via record-actions after the "
            "artifact revision. Fixing only the seed finding does not close the family."
        ),
        PLAN_ROOT_PLANNER_INSTRUCTION,
    ]


def build_planner_tool_instructions(run_id: str) -> dict[str, str]:
    """CLI instructions embedded in planner session manifests."""

    return {
        "authorization": (
            "Mutating commands require the session capability token exported "
            "as TDP_CAPABILITY_TOKEN."
        ),
        "agent_requests_dir": "$TDP_AGENT_REQUESTS_DIR",
        "snapshot": f"tdp agent plan snapshot --run {run_id} --view active",
        "apply": (
            f"tdp agent plan apply --run {run_id} "
            "--request $TDP_AGENT_REQUESTS_DIR/plan-apply-r<rev>-a01.json"
        ),
        "check": f"tdp agent plan check --run {run_id}",
        "request_review": (
            f"tdp agent review request --run {run_id} "
            "--request $TDP_AGENT_REQUESTS_DIR/review-request-<scope>-a01.json"
        ),
        "completion_signal": PLANNER_CANDIDATE_READY_SIGNAL,
        "discover": (
            "tdp agent readme; tdp agent schema plan-transaction; "
            "tdp agent example expand-branch"
        ),
        "plan_depends_on": (
            "For new items in the same batch, set add_item.item.depends_on inline "
            "(stable ids or same-batch temp_id; string or array). For existing "
            "items, use add_dependency. See tdp agent example expand-branch."
        ),
    }


__all__ = [
    "PLANNER_CANDIDATE_READY_SIGNAL",
    "build_planner_protocol_instructions",
    "build_planner_tool_instructions",
    "primary_planner_binding",
    "primary_planner_provider_session_id",
]
