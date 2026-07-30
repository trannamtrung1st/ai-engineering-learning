"""Built-in configuration defaults (proposal §13, §14)."""

from __future__ import annotations

from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
    "run": {
        "input_refs": [],
        "boundaries": [],
        "acceptance": [],
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
        "whole_plan": {"required": True},
        "focused_output": {"enabled": True},
        "whole_output": {"required": True},
    },
    "provider": {
        "name": "cursor",
        "skip_probe": False,
    },
    "limits": {
        "planning": {
            "max_expansion_iterations": 20,
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

ALLOWED_OVERRIDE_PATHS: frozenset[str] = frozenset(
    {
        "version",
        "runtime.runs_dir",
        "run.workspace",
        "run.input_refs",
        "run.output_goal",
        "run.output_goal_file",
        "run.boundaries",
        "run.acceptance",
        "planning.stop_hint",
        "planning.max_depth",
        "planning.max_expansion_per_item",
        "review.focused_plan.enabled",
        "review.whole_plan.required",
        "review.focused_output.enabled",
        "review.whole_output.required",
        "provider.name",
        "provider.model",
        "provider.binary",
        "provider.skip_probe",
        "limits.planning.max_expansion_iterations",
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
    }
)
