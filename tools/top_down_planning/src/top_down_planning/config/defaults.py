"""Built-in configuration defaults (proposal §13, §14)."""

from __future__ import annotations

from typing import Any

from top_down_planning.config.activities import (
    ALLOWED_AGENT_ACTIVITIES,
    ALLOWED_AGENT_ROLES,
    agent_context_override_paths,
)

_AGENT_CONTEXT_OVERLAY_DEFAULT: dict[str, Any] = {
    "guidance": [],
    "resources": [],
    "skills": [],
}


def _default_agent_context_activities() -> dict[str, dict[str, Any]]:
    return {
        name: dict(_AGENT_CONTEXT_OVERLAY_DEFAULT) for name in sorted(ALLOWED_AGENT_ACTIVITIES)
    }


def _default_agent_context_roles() -> dict[str, dict[str, Any]]:
    return {
        name: dict(_AGENT_CONTEXT_OVERLAY_DEFAULT) for name in sorted(ALLOWED_AGENT_ROLES)
    }

DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
    "execution": {
        "mode": "single",
    },
    "project": {},
    "run": {
        "input_refs": [],
        "boundaries": [],
        "acceptance": [],
    },
    "context_snapshot": {
        "excludes": {
            "defaults": True,
            "patterns": [],
        },
    },
    "agent_context": {
        "bundled_skills": True,
        "default": dict(_AGENT_CONTEXT_OVERLAY_DEFAULT),
        "roles": _default_agent_context_roles(),
        "activities": _default_agent_context_activities(),
    },
    "planning": {
        "stop_hint": (
            "Stop when each item has one coherent outcome, clear boundaries, "
            "material dependencies, and acceptance expectations."
        ),
        "max_depth": 4,
        "max_expansion_per_item": 7,
    },
    "review": {
        "revise_at": None,
        "focused_plan": {
            "enabled": True,
            "revise_at": None,
        },
        "focused_output": {
            "enabled": True,
            "revise_at": None,
        },
        "whole_plan": {
            "revise_at": None,
            "rubric": [
                (
                    "Internal consistency: Are parent and child outcomes, acceptance "
                    "criteria, dependencies, and titles mutually consistent with no "
                    "contradictions, impossible ordering, or unverifiable claims?"
                ),
                (
                    "Hierarchy: Is every child a genuine decomposition of its parent "
                    "outcome? Are unrelated enhancements siblings? Are grouping-only "
                    "nodes marked aggregate? Does any executable parent overlap "
                    "executable descendants?"
                ),
                (
                    "Dependencies: Is every dependency a real execution prerequisite? "
                    "Could the dependent item begin correctly without the prerequisite "
                    "completing? Is the edge merely preferred order or integration "
                    "convenience rather than a hard blocker?"
                ),
                (
                    "Granularity: Does each item represent a coherent executable "
                    "outcome? Is any item too broad or an artificial micro-step? Has "
                    "the plan introduced coordination shells with no direct value?"
                ),
                (
                    "Contract ownership: Are acceptance criteria attached to the "
                    "item that implements them? Are cross-feature integration checks "
                    "placed at the root or final-review level when appropriate?"
                ),
                (
                    "Plan cleanliness: Does the active plan contain only current "
                    "work and meaningful aggregates? Are titles, outcomes, and "
                    "scopes distinct enough to avoid overlapping work?"
                ),
                (
                    "Coverage: Does the plan address all material requirements from "
                    "the input references and output goal without obvious gaps?"
                ),
                (
                    "Traceability: Can each acceptance criterion be traced to a "
                    "specific planned outcome and verification path?"
                ),
                (
                    "Field placement: Are acceptance, risks, assumptions, and "
                    "constraints used consistently? Are source-document references in "
                    "source_refs rather than scope.includes? Are non-binding "
                    "suggestions kept out of acceptance?"
                ),
                (
                    "Risk ownership: Are material uncertainties captured as specific "
                    "risks on the lowest owning item? Are plan-level risks reserved "
                    "for cross-cutting threats without duplicating item-level risks?"
                ),
                (
                    "Aggregate purity: Aggregates must not own executable production "
                    "work. Acceptance on aggregates may express roll-up constraints "
                    "but not batch sequencing or owner workflow instructions."
                ),
                (
                    "Behavioral completeness: Testing coverage requires observable "
                    "expected outcomes for every material branch."
                ),
                (
                    "Requirement modality preservation: Preserve mandatory, "
                    "conditional, optional, and library-dependent modality from "
                    "authoritative inputs."
                ),
                (
                    "Per-acceptance dependency closure: Every capability named in "
                    "acceptance must be produced by the item or an active transitive "
                    "dependency."
                ),
            ],
        },
        "whole_output": {
            "revise_at": None,
            "rubric": [
                (
                    "Plan conformance: Does each completed disposition satisfy the "
                    "approved plan item outcome and acceptance criteria?"
                ),
                (
                    "Evidence correctness: Does recorded evidence support the "
                    "claimed disposition for each terminal item?"
                ),
                (
                    "Cross-output consistency: Do deliverables, summaries, and "
                    "references contradict each other or the approved plan?"
                ),
                (
                    "Completion claim: Does the goal assessment align with the "
                    "evidence and remaining open items?"
                ),
                (
                    "Traceability: Can each disposition be traced from plan "
                    "contract through evidence to a verifiable output?"
                ),
                (
                    "Plan risk coverage: Were material plan-level and item-level "
                    "risks addressed or explicitly accepted in the delivered output?"
                ),
            ],
        },
    },
    "provider": {
        "name": "cursor",
        "skip_probe": False,
    },
    "observability": {
        "log_level": "normal",
        "log_format": "console",
        "color": "auto",
        "show_agent_text": True,
        "show_timestamps": False,
        "agent_transcript": False,
    },
    "notifications": {
        "enabled": True,
        "terminal": True,
        "phase": True,
        "progress": False,
    },
    "limits": {
        "planning": {
            "max_items_added": 20,
            "max_agent_turns": 40,
        },
        "focused_plan_review": {
            "max_loops": 5,
            "max_revision_cycles_per_loop": 3,
        },
        "whole_plan_review": {
            # Verification/revision cycles per finding set (Loop Bounds).
            "max_revision_cycles": 5,
            # Fresh scope-complete review rounds per phase.
            "max_scope_review_rounds": 3,
        },
        "production": {
            "max_batches": 50,
            "max_agent_turns_per_batch": 10,
        },
        "focused_output_review": {
            "max_loops": 8,
            "max_revision_cycles_per_loop": 3,
        },
        "whole_output_review": {
            "max_revision_cycles": 5,
            "max_scope_review_rounds": 3,
        },
        "amendment": {
            "max_requests": 3,
            "max_revision_cycles_per_request": 3,
        },
        "review": {
            "max_agent_turns_per_gate": 5,
        },
        "provider": {
            "max_retries_per_call": 2,
            "turn_idle_timeout_seconds": 0,
        },
    },
}

# Re-exported for resume policy and config validation.
ALLOWED_AGENT_CONTEXT_ROLES: frozenset[str] = ALLOWED_AGENT_ROLES

ALLOWED_OVERRIDE_PATHS: frozenset[str] = frozenset(
    {
        "version",
        "execution.mode",
        "execution.state_file",
        "runtime.runs_dir",
        "project.workspace",
        "run.input_refs",
        "run.output_goal",
        "run.output_goal_file",
        "run.boundaries",
        "run.acceptance",
        "context_snapshot.excludes.defaults",
        "context_snapshot.excludes.patterns",
        *agent_context_override_paths(),
        "planning.stop_hint",
        "planning.max_depth",
        "planning.max_expansion_per_item",
        "review.revise_at",
        "review.focused_plan.enabled",
        "review.focused_plan.revise_at",
        "review.focused_output.enabled",
        "review.focused_output.revise_at",
        "review.whole_plan.revise_at",
        "review.whole_plan.rubric",
        "review.whole_output.revise_at",
        "review.whole_output.rubric",
        "provider.name",
        "provider.binary",
        "provider.skip_probe",
        "limits.planning.max_items_added",
        "limits.planning.max_agent_turns",
        "limits.focused_plan_review.max_loops",
        "limits.focused_plan_review.max_revision_cycles_per_loop",
        "limits.whole_plan_review.max_revision_cycles",
        "limits.whole_plan_review.max_scope_review_rounds",
        "limits.production.max_batches",
        "limits.production.max_agent_turns_per_batch",
        "limits.focused_output_review.max_loops",
        "limits.focused_output_review.max_revision_cycles_per_loop",
        "limits.whole_output_review.max_revision_cycles",
        "limits.whole_output_review.max_scope_review_rounds",
        "limits.amendment.max_requests",
        "limits.amendment.max_revision_cycles_per_request",
        "limits.review.max_agent_turns_per_gate",
        "limits.provider.max_retries_per_call",
        "limits.provider.turn_idle_timeout_seconds",
        "observability.log_level",
        "observability.log_format",
        "observability.color",
        "observability.show_agent_text",
        "observability.show_timestamps",
        "observability.agent_transcript",
        "observability.max_message_length",
        "observability.max_tool_summary_length",
        "notifications.enabled",
        "notifications.terminal",
        "notifications.phase",
        "notifications.progress",
    }
)
