"""Built-in configuration defaults (proposal §13, §14)."""

from __future__ import annotations

from typing import Any

_AGENT_CONTEXT_ROLE_DEFAULT: dict[str, Any] = {
    "resources": [],
    "skills": [],
}

DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
    "project": {
        "resources": [],
    },
    "run": {
        "input_refs": [],
        "boundaries": [],
        "acceptance": [],
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
        "focused_plan": {"enabled": True},
        "focused_output": {"enabled": True},
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
        "show_timestamps": True,
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
            "max_revision_cycles": 5,
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
        "project.resources",
        "run.input_refs",
        "run.output_goal",
        "run.output_goal_file",
        "run.boundaries",
        "run.acceptance",
        "agent_context.default.model",
        "agent_context.default.resources",
        "agent_context.default.skills",
        "agent_context.planner.model",
        "agent_context.planner.resources",
        "agent_context.planner.skills",
        "agent_context.producer.model",
        "agent_context.producer.resources",
        "agent_context.producer.skills",
        "agent_context.reviewer.model",
        "agent_context.reviewer.resources",
        "agent_context.reviewer.skills",
        "planning.stop_hint",
        "planning.max_depth",
        "planning.max_expansion_per_item",
        "review.focused_plan.enabled",
        "review.focused_output.enabled",
        "provider.name",
        "provider.binary",
        "provider.skip_probe",
        "limits.planning.max_items_added",
        "limits.planning.max_agent_turns",
        "limits.focused_plan_review.max_loops",
        "limits.focused_plan_review.max_revision_cycles_per_loop",
        "limits.whole_plan_review.max_revision_cycles",
        "limits.production.max_batches",
        "limits.production.max_agent_turns_per_batch",
        "limits.focused_output_review.max_loops",
        "limits.focused_output_review.max_revision_cycles_per_loop",
        "limits.whole_output_review.max_revision_cycles",
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
