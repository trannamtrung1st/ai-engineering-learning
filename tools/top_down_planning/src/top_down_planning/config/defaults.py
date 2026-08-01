"""Built-in configuration defaults (proposal §13, §14)."""

from __future__ import annotations

from typing import Any

_AGENT_CONTEXT_ROLE_DEFAULT: dict[str, Any] = {
    "guidance": [],
    "resources": [],
    "skills": [],
}

DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
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
        "default": dict(_AGENT_CONTEXT_ROLE_DEFAULT),
        "planner": dict(_AGENT_CONTEXT_ROLE_DEFAULT),
        "producer": dict(_AGENT_CONTEXT_ROLE_DEFAULT),
        "reviewer": dict(_AGENT_CONTEXT_ROLE_DEFAULT),
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
            ],
        },
        "whole_output": {
            "revise_at": None,
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
        "provider": {
            "max_retries_per_call": 2,
        },
    },
}

ALLOWED_AGENT_CONTEXT_ROLES: frozenset[str] = frozenset(
    {"default", "planner", "producer", "reviewer"}
)

ALLOWED_OVERRIDE_PATHS: frozenset[str] = frozenset(
    {
        "version",
        "runtime.runs_dir",
        "project.workspace",
        "run.input_refs",
        "run.output_goal",
        "run.output_goal_file",
        "run.boundaries",
        "run.acceptance",
        "context_snapshot.excludes.defaults",
        "context_snapshot.excludes.patterns",
        "agent_context.default.model",
        "agent_context.default.guidance",
        "agent_context.default.resources",
        "agent_context.default.skills",
        "agent_context.planner.model",
        "agent_context.planner.guidance",
        "agent_context.planner.resources",
        "agent_context.planner.skills",
        "agent_context.producer.model",
        "agent_context.producer.guidance",
        "agent_context.producer.resources",
        "agent_context.producer.skills",
        "agent_context.reviewer.model",
        "agent_context.reviewer.guidance",
        "agent_context.reviewer.resources",
        "agent_context.reviewer.skills",
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
        "limits.provider.max_retries_per_call",
        "observability.log_level",
        "observability.log_format",
        "observability.color",
        "observability.show_agent_text",
        "observability.show_timestamps",
        "observability.agent_transcript",
    }
)
