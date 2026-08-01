"""CLI-discoverable schemas, examples, and agent help for ``tdp agent``."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from core_tools.schema import validate_against_schema

from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.domain.dispositions import TERMINAL_DISPOSITIONS

PUBLIC_SCHEMAS: tuple[str, ...] = (
    "config",
    "plan-transaction",
    "production-apply",
    "review-respond",
    "review-record-finding-actions",
    "focused-review-request",
    "amendment-request",
    "completion-claim",
    "blocker-report",
)

PUBLIC_EXAMPLES: tuple[str, ...] = (
    "expand-branch",
    "batch-result",
    "empty-output",
    "evidence-revision",
    "evidence-revision-focused",
    "review-respond",
    "review-respond-initial",
    "review-respond-initial-approved",
    "review-respond-verification",
    "review-respond-scope",
    "review-record-finding-actions",
    "focused-review-request",
    "amendment-request",
    "completion-claim",
    "blocker-report",
)

_PLAN_ITEM_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["title", "kind"],
    "properties": {
        "title": {"type": "string", "minLength": 1},
        "outcome": {"type": "string"},
        "kind": {"type": "string", "enum": ["aggregate", "work"]},
        "scope": {
            "type": "object",
            "properties": {
                "includes": {"type": "array", "items": {"type": "string"}},
                "excludes": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": False,
        },
        "boundaries": {"type": "array", "items": {"type": "string"}},
        "depends_on": {"type": "array", "items": {"type": "string"}},
        "acceptance": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}

_PLAN_ITEM_PATCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "minProperties": 1,
    "properties": {
        "title": {"type": "string", "minLength": 1},
        "outcome": {"type": "string"},
        "kind": {"type": "string", "enum": ["aggregate", "work"]},
        "scope": _PLAN_ITEM_INPUT_SCHEMA["properties"]["scope"],
        "boundaries": {"type": "array", "items": {"type": "string"}},
        "acceptance": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}

_PLAN_METADATA_PATCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "minProperties": 1,
    "properties": {
        "scope": _PLAN_ITEM_INPUT_SCHEMA["properties"]["scope"],
        "boundaries": {"type": "array", "items": {"type": "string"}},
        "constraints": {"type": "array", "items": {"type": "string"}},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "acceptance": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}

_PLAN_OPERATION_SCHEMA: dict[str, Any] = {
    "oneOf": [
        {
            "type": "object",
            "required": ["op", "temp_id", "parent_id", "item"],
            "properties": {
                "op": {"const": "add_item"},
                "temp_id": {"type": "string"},
                "parent_id": {"type": ["string", "null"]},
                "placement": {"type": "object"},
                "item": _PLAN_ITEM_INPUT_SCHEMA,
            },
            "additionalProperties": True,
        },
        {
            "type": "object",
            "required": ["op", "item_id", "patch"],
            "properties": {
                "op": {"const": "update_item"},
                "item_id": {"type": "string"},
                "patch": _PLAN_ITEM_PATCH_SCHEMA,
            },
            "additionalProperties": True,
        },
        {
            "type": "object",
            "required": ["op", "patch"],
            "properties": {
                "op": {"const": "update_plan"},
                "patch": _PLAN_METADATA_PATCH_SCHEMA,
            },
            "additionalProperties": True,
        },
        {
            "type": "object",
            "required": ["op", "item_id"],
            "properties": {
                "op": {"const": "move_subtree"},
                "item_id": {"type": "string"},
                "new_parent_id": {"type": ["string", "null"]},
                "placement": {"type": "object"},
            },
            "additionalProperties": True,
        },
        {
            "type": "object",
            "required": ["op", "item_id", "replacement"],
            "description": "Replace a leaf item only; items with active children are rejected.",
            "properties": {
                "op": {"const": "supersede_item"},
                "item_id": {"type": "string"},
                "temp_id": {"type": "string"},
                "replacement": _PLAN_ITEM_INPUT_SCHEMA,
            },
            "additionalProperties": True,
        },
        {
            "type": "object",
            "required": ["op", "item_id"],
            "properties": {
                "op": {"const": "remove_item"},
                "item_id": {"type": "string"},
            },
            "additionalProperties": True,
        },
        {
            "type": "object",
            "required": ["op", "item_id", "depends_on"],
            "properties": {
                "op": {"const": "add_dependency"},
                "item_id": {"type": "string"},
                "depends_on": {"type": "string"},
            },
            "additionalProperties": True,
        },
        {
            "type": "object",
            "required": ["op", "item_id", "depends_on"],
            "properties": {
                "op": {"const": "remove_dependency"},
                "item_id": {"type": "string"},
                "depends_on": {"type": "string"},
            },
            "additionalProperties": True,
        },
        {
            "type": "object",
            "required": ["op", "item_id", "depends_on"],
            "properties": {
                "op": {"const": "replace_dependencies"},
                "item_id": {"type": "string"},
                "depends_on": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": True,
        },
    ]
}

_DISPOSITION_RECORD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["disposition"],
    "properties": {
        "disposition": {"type": "string", "enum": sorted(TERMINAL_DISPOSITIONS)},
        "reason": {"type": "string"},
        "replacement_ref": {"type": "string"},
        "evidence": {"type": "string"},
    },
    "additionalProperties": False,
}

_REVIEW_FINDING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "id",
        "severity",
        "category",
        "target_refs",
        "issue",
        "recommended_change",
    ],
    "properties": {
        "id": {"type": "string"},
        "severity": {
            "type": "string",
            "enum": ["suggestion", "minor", "major", "blocker"],
        },
        "category": {"type": "string"},
        "target_refs": {"type": "array", "items": {"type": "string"}},
        "issue": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "recommended_change": {"type": "string"},
        "reopens_finding_id": {"type": "string"},
        "status": {
            "type": "string",
            "enum": [
                "unresolved",
                "partially_resolved",
                "resolved",
                "superseded",
                "invalid",
            ],
        },
    },
    "additionalProperties": False,
}

_FINDING_VERIFICATION_ENTRY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["finding_id", "disposition"],
    "properties": {
        "finding_id": {"type": "string"},
        "disposition": {
            "type": "string",
            "enum": [
                "resolved",
                "partially_resolved",
                "unresolved",
                "superseded",
                "invalid",
            ],
        },
        "evidence": {"type": "array", "items": {"type": "string"}},
        "direct_side_effects": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}

_FOCUSED_REVIEW_SCOPE_SCHEMA = {
    "type": "object",
    "required": ["kind", "item_ids"],
    "properties": {
        "item_ids": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string"},
        },
    },
    "additionalProperties": False,
}

_FOCUSED_REVIEW_BRANCH_SCHEMAS = [
    {
        "type": "object",
        "required": ["type", "scope"],
        "properties": {
            "type": {"const": review_type},
            "scope": {
                **{
                    k: v
                    for k, v in _FOCUSED_REVIEW_SCOPE_SCHEMA.items()
                    if k != "properties"
                },
                "properties": {
                    "kind": {"const": review_type},
                    **(_FOCUSED_REVIEW_SCOPE_SCHEMA["properties"]),
                },
            },
        },
        "additionalProperties": False,
    }
    for review_type in ("focused_plan", "focused_output")
]

_REVIEW_RESPOND_ONE_OF: list[dict[str, Any]] = [
    {
        "title": "FocusedDiscoveryRespond",
        "type": "object",
        "required": [
            "loop_id",
            "target_revision",
            "finding_set_id",
            "reported_findings",
            "review_completed",
            "summary",
        ],
        "properties": {
            "loop_id": {"type": "string"},
            "target_revision": {"type": "integer"},
            "finding_set_id": {"type": "string"},
            "target_digest": {"type": "string"},
            "reported_findings": {
                "type": "array",
                "items": _REVIEW_FINDING_SCHEMA,
            },
            "review_completed": {"type": "boolean"},
            "summary": {"type": "string"},
            "block_review": {
                "type": "boolean",
                "description": (
                    "When true, halt scope review without reporting findings."
                ),
            },
        },
        "additionalProperties": False,
    },
    {
        "title": "MandatoryDiscoveryRespond",
        "type": "object",
        "required": [
            "loop_id",
            "target_revision",
            "stage",
            "finding_set_id",
            "reported_findings",
            "review_completed",
            "summary",
        ],
        "properties": {
            "loop_id": {"type": "string"},
            "target_revision": {"type": "integer"},
            "stage": {
                "type": "string",
                "enum": ["initial_review", "scope_review"],
            },
            "finding_set_id": {"type": "string"},
            "target_digest": {"type": "string"},
            "reported_findings": {
                "type": "array",
                "items": _REVIEW_FINDING_SCHEMA,
            },
            "review_completed": {"type": "boolean"},
            "summary": {"type": "string"},
            "block_review": {
                "type": "boolean",
                "description": (
                    "When true, halt scope review without reporting findings."
                ),
            },
            "scope_id": {"type": "string"},
            "acceptance_criteria_checked": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "additionalProperties": False,
    },
    {
        "title": "MandatoryFindingVerificationRespond",
        "type": "object",
        "required": [
            "loop_id",
            "target_revision",
            "decision",
            "stage",
            "target_digest",
            "finding_set_id",
            "finding_results",
            "new_direct_side_effect_findings",
            "summary",
        ],
        "properties": {
            "loop_id": {"type": "string"},
            "target_revision": {"type": "integer"},
            "stage": {"const": "finding_verification"},
            "decision": {
                "type": "string",
                "enum": ["verified", "needs_revision", "blocked"],
            },
            "target_digest": {
                "type": "string",
                "description": "Artifact digest inspected by this stage.",
            },
            "finding_set_id": {"type": "string"},
            "finding_results": {
                "type": "array",
                "items": _FINDING_VERIFICATION_ENTRY_SCHEMA,
            },
            "new_direct_side_effect_findings": {
                "type": "array",
                "items": _REVIEW_FINDING_SCHEMA,
            },
            "summary": {"type": "string"},
        },
        "additionalProperties": False,
    },
]

SCHEMAS: dict[str, dict[str, Any]] = {
    "config": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "TopDownPlanningConfig",
        "description": "Resolved run configuration.",
        "type": "object",
        "required": ["version", "project", "run", "agent_context", "planning", "review", "provider", "limits"],
        "properties": {
            "version": {"type": "integer"},
            "project": {
                "type": "object",
                "description": (
                    "Project workspace. project.workspace is the canonical "
                    "workspace root for path resolution."
                ),
                "properties": {
                    "workspace": {
                        "type": "string",
                        "description": (
                            "Canonical workspace root. Relative paths resolve "
                            "against the process working directory."
                        ),
                    },
                },
                "additionalProperties": False,
            },
            "agent_context": {
                "type": "object",
                "description": (
                    "Per-role model, advisory guidance, supporting resources, and "
                    "skills. Guidance, resources, and skills are additive with "
                    "agent_context.default. Guidance is advisory only and does not "
                    "change acceptance, enforcement, or lifecycle transitions. "
                    "Run contracts (run.input_refs, run.output_goal / "
                    "run.output_goal_file) are supplied automatically and must not "
                    "be repeated here."
                ),
                "properties": {
                    role: {
                        "type": "object",
                        "properties": {
                            "model": {"type": "string"},
                            "guidance": {
                                "type": "array",
                                "description": (
                                    "Advisory working preferences. Each entry is "
                                    "exactly one of {text: ...} or {file: ...}. "
                                    "Text and file values must be non-empty after "
                                    "trimming whitespace."
                                ),
                                "items": {
                                    "oneOf": [
                                        {
                                            "type": "object",
                                            "required": ["text"],
                                            "properties": {
                                                "text": {
                                                    "type": "string",
                                                    "pattern": "\\S",
                                                    "description": (
                                                        "Inline guidance; must contain "
                                                        "at least one non-whitespace character."
                                                    ),
                                                },
                                            },
                                            "additionalProperties": False,
                                        },
                                        {
                                            "type": "object",
                                            "required": ["file"],
                                            "properties": {
                                                "file": {
                                                    "type": "string",
                                                    "pattern": "\\S",
                                                    "description": (
                                                        "Workspace-relative guidance file path; "
                                                        "must contain at least one non-whitespace "
                                                        "character."
                                                    ),
                                                },
                                            },
                                            "additionalProperties": False,
                                        },
                                    ],
                                },
                            },
                            "resources": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "skills": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "additionalProperties": False,
                    }
                    for role in ("default", "planner", "producer", "reviewer")
                },
                "additionalProperties": False,
            },
            "run": {
                "type": "object",
                "description": (
                    "Run inputs and goals. Relative paths in input_refs and "
                    "output_goal_file resolve against project.workspace. Use either "
                    "output_goal (inline) or output_goal_file (path), not both."
                ),
                "properties": {
                    "input_refs": {"type": "array", "items": {"type": "string"}},
                    "output_goal": {
                        "type": "string",
                        "description": (
                            "Inline output goal text. Mutually exclusive with "
                            "output_goal_file."
                        ),
                    },
                    "output_goal_file": {
                        "type": "string",
                        "description": (
                            "Path to a UTF-8 file containing the output goal. "
                            "Resolved against project.workspace. "
                            "Mutually exclusive with output_goal."
                        ),
                    },
                    "boundaries": {"type": "array", "items": {"type": "string"}},
                    "acceptance": {"type": "array", "items": {"type": "string"}},
                },
                "additionalProperties": False,
            },
            "context_snapshot": {
                "type": "object",
                "description": (
                    "Snapshot exclusion policy for materialized resource bindings. "
                    "Omitting this section is equivalent to excludes.defaults: true "
                    "and excludes.patterns: []. Patterns use gitignore/gitwildmatch "
                    "semantics matched against canonical workspace-relative POSIX "
                    "paths. Built-in defaults are applied before user patterns; "
                    "later patterns override earlier ones. Policy participates in "
                    "context_spec identity. Exclusions do not apply to skills or "
                    "guidance. Direct file resources always bind; discovered "
                    "directory/glob matches are filtered. Do not inherit .gitignore. "
                    "Distinct from run-record schema_version (recreate old runs)."
                ),
                "properties": {
                    "excludes": {
                        "type": "object",
                        "properties": {
                            "defaults": {
                                "type": "boolean",
                                "description": (
                                    "When true, include built-in generated-artifact "
                                    "excludes (__pycache__, *.py[cod], pytest/mypy/ruff "
                                    "caches). An empty patterns list does not disable "
                                    "defaults; set defaults: false to turn built-ins off."
                                ),
                            },
                            "patterns": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": (
                                    "Ordered user exclude patterns (negations, *, **, "
                                    "root anchors, directory-only). Later entries "
                                    "override earlier ones, including built-ins."
                                ),
                            },
                        },
                        "additionalProperties": False,
                    },
                },
                "additionalProperties": False,
            },
            "planning": {
                "type": "object",
                "properties": {
                    "stop_hint": {"type": "string"},
                    "max_depth": {"type": "integer"},
                    "max_expansion_per_item": {"type": "integer"},
                },
                "additionalProperties": False,
            },
            "review": {
                "type": "object",
                "properties": {
                    "revise_at": {
                        "oneOf": [
                            {"type": "null"},
                            {
                                "type": "string",
                                "enum": ["suggestion", "minor", "major", "blocker"],
                            },
                        ],
                        "description": (
                            "Global revision-threshold override; null inherits "
                            "BUILTIN_REVISE_AT per review type."
                        ),
                    },
                    "focused_plan": {
                        "type": "object",
                        "properties": {
                            "enabled": {"type": "boolean"},
                            "revise_at": {
                                "oneOf": [
                                    {"type": "null"},
                                    {
                                        "type": "string",
                                        "enum": [
                                            "suggestion",
                                            "minor",
                                            "major",
                                            "blocker",
                                        ],
                                    },
                                ]
                            },
                        },
                        "additionalProperties": False,
                    },
                    "focused_output": {
                        "type": "object",
                        "properties": {
                            "enabled": {"type": "boolean"},
                            "revise_at": {
                                "oneOf": [
                                    {"type": "null"},
                                    {
                                        "type": "string",
                                        "enum": [
                                            "suggestion",
                                            "minor",
                                            "major",
                                            "blocker",
                                        ],
                                    },
                                ]
                            },
                        },
                        "additionalProperties": False,
                    },
                    "whole_plan": {
                        "type": "object",
                        "properties": {
                            "revise_at": {
                                "oneOf": [
                                    {"type": "null"},
                                    {
                                        "type": "string",
                                        "enum": [
                                            "suggestion",
                                            "minor",
                                            "major",
                                            "blocker",
                                        ],
                                    },
                                ]
                            },
                            "rubric": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "additionalProperties": False,
                    },
                    "whole_output": {
                        "type": "object",
                        "properties": {
                            "revise_at": {
                                "oneOf": [
                                    {"type": "null"},
                                    {
                                        "type": "string",
                                        "enum": [
                                            "suggestion",
                                            "minor",
                                            "major",
                                            "blocker",
                                        ],
                                    },
                                ]
                            },
                            "rubric": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "additionalProperties": False,
                    },
                },
                "additionalProperties": False,
            },
            "provider": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "enum": ["cursor", "stub"]},
                    "binary": {"type": "string"},
                    "skip_probe": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
            "observability": {
                "type": "object",
                "properties": {
                    "log_level": {
                        "type": "string",
                        "enum": ["quiet", "normal", "verbose", "trace"],
                    },
                    "log_format": {
                        "type": "string",
                        "enum": ["console", "jsonl"],
                    },
                    "color": {
                        "type": "string",
                        "enum": ["auto", "always", "never"],
                    },
                    "show_agent_text": {"type": "boolean"},
                    "show_timestamps": {"type": "boolean"},
                    "agent_transcript": {"type": "boolean"},
                    "max_message_length": {
                        "type": ["integer", "null"],
                        "minimum": 1,
                    },
                    "max_tool_summary_length": {
                        "type": ["integer", "null"],
                        "minimum": 1,
                    },
                },
                "additionalProperties": False,
            },
            "limits": {
                "type": "object",
                "properties": {
                    "planning": {
                        "type": "object",
                        "properties": {
                            "max_items_added": {"type": "integer"},
                            "max_agent_turns": {"type": "integer"},
                        },
                        "additionalProperties": False,
                    },
                    "focused_plan_review": {
                        "type": "object",
                        "properties": {
                            "max_loops": {"type": "integer"},
                            "max_revision_cycles_per_loop": {"type": "integer"},
                        },
                        "additionalProperties": False,
                    },
                    "whole_plan_review": {
                        "type": "object",
                        "properties": {
                            "max_revision_cycles": {
                                "type": "integer",
                                "description": (
                                    "Maximum verification/revision cycles per "
                                    "finding set for mandatory whole-plan review."
                                ),
                            },
                            "max_scope_review_rounds": {
                                "type": "integer",
                                "description": (
                                    "Maximum fresh scope-complete review "
                                    "rounds per whole-plan review phase."
                                ),
                            },
                        },
                        "additionalProperties": False,
                    },
                    "production": {
                        "type": "object",
                        "properties": {
                            "max_batches": {"type": "integer"},
                            "max_agent_turns_per_batch": {"type": "integer"},
                        },
                        "additionalProperties": False,
                    },
                    "focused_output_review": {
                        "type": "object",
                        "properties": {
                            "max_loops": {"type": "integer"},
                            "max_revision_cycles_per_loop": {"type": "integer"},
                        },
                        "additionalProperties": False,
                    },
                    "whole_output_review": {
                        "type": "object",
                        "properties": {
                            "max_revision_cycles": {
                                "type": "integer",
                                "description": (
                                    "Maximum verification/revision cycles per "
                                    "finding set for mandatory whole-output review."
                                ),
                            },
                            "max_scope_review_rounds": {
                                "type": "integer",
                                "description": (
                                    "Maximum fresh scope-complete review "
                                    "rounds per whole-output review phase."
                                ),
                            },
                        },
                        "additionalProperties": False,
                    },
                    "amendment": {
                        "type": "object",
                        "properties": {
                            "max_requests": {"type": "integer"},
                            "max_revision_cycles_per_request": {"type": "integer"},
                        },
                        "additionalProperties": False,
                    },
                    "provider": {
                        "type": "object",
                        "properties": {
                            "max_retries_per_call": {"type": "integer"},
                        },
                        "additionalProperties": False,
                    },
                },
                "additionalProperties": False,
            },
            "runtime": {
                "type": "object",
                "description": (
                    "Operational storage settings. runtime.runs_dir is the root "
                    "directory containing all runs; relative paths resolve against "
                    "the process working directory."
                ),
                "properties": {
                    "runs_dir": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "additionalProperties": False,
    },
    "plan-transaction": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "PlanApplyRequest",
        "description": "Atomic plan transaction for `tdp agent plan apply`.",
        "type": "object",
        "required": ["base_revision", "operations"],
        "properties": {
            "base_revision": {"type": "integer"},
            "operations": {
                "type": "array",
                "minItems": 1,
                "items": _PLAN_OPERATION_SCHEMA,
            },
        },
        "additionalProperties": False,
    },
    "production-apply": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ProductionApplyRequest",
        "description": (
            "Production batch request for `tdp agent production apply`. "
            "Output evidence is content-bound at apply time: agents supply only "
            "`id`, `type`, and workspace `ref`; the service captures sha256, "
            "size, media_type, captured_at, and an immutable snapshot under "
            "artifacts/<snapshot-uuid>/<filename>. Evidence IDs are unique "
            "across the full run history. When snapshot-bound workspace paths "
            "drift, every changed workspace path must appear in this batch's "
            "outputs; otherwise apply fails with production_evidence_incomplete "
            "or production_context_mutation_unauthorized before production.json "
            "is updated. Artifact capture runs only after snapshot validation "
            "passes."
        ),
        "type": "object",
        "required": ["production_revision", "plan_items", "dispositions"],
        "properties": {
            "production_revision": {"type": "integer"},
            "batch_id": {"type": "string"},
            "plan_items": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string"},
            },
            "dispositions": {
                "type": "object",
                "additionalProperties": _DISPOSITION_RECORD_SCHEMA,
            },
            "outputs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["id", "type", "ref"],
                    "properties": {
                        "id": {"type": "string"},
                        "type": {"type": "string"},
                        "ref": {"type": "string"},
                    },
                },
            },
            "contributions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["item_id"],
                    "properties": {
                        "item_id": {"type": "string"},
                        "output_refs": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "summary": {"type": "string"},
                    },
                },
            },
            "summary": {"type": "string"},
            "goal_assessment": {"type": "string"},
            "empty_output": {"type": "boolean"},
            "empty_output_reason": {
                "type": "string",
                "description": "Required when empty_output is true.",
            },
            "evidence_revision": {
                "type": "boolean",
                "description": (
                    "Revise outputs for terminal plan_items targeted by unresolved "
                    "required findings without changing dispositions. Allowed during "
                    "whole_output_review, or during production when an active "
                    "focused_output review has status changes_requested."
                ),
            },
            "focused_review_loop_id": {
                "type": "string",
                "description": (
                    "Optional focused_output loop id binding for evidence_revision "
                    "during production."
                ),
            },
            "intent": {"type": "string"},
            "agent_turns": {"type": "integer", "minimum": 1},
        },
        "additionalProperties": False,
    },
    "review-respond": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ReviewRespondRequest",
        "description": (
            "Review findings and decision for `tdp agent review respond`. "
            "Mandatory whole_plan / whole_output loops require `stage` and "
            "stage-native decisions per branch below. Focused reviews omit "
            "`stage` and use approved|changes_requested|blocked."
        ),
        "oneOf": _REVIEW_RESPOND_ONE_OF,
    },
    "review-record-finding-actions": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ReviewRecordFindingActionsRequest",
        "description": (
            "Primary-agent owner actions for `tdp agent review record-actions`. "
            "Required findings may only use fix|challenge; optional findings may "
            "also use defer|accept_as_is. Challenges require challenge_reason, "
            "proposed_disposition, and rationale. Use default_optional_action "
            "(defer|accept_as_is) to batch-apply a default to remaining optional "
            "findings in the current finding set. "
            "Owner/advisory packages expose an active-findings view: "
            "`new_findings`, `carried_open_findings`, `verification_targets`, "
            "`current_finding_actions`, `history_summary` (`total`, `closed`, "
            "`open`, optional `convergence_warning`), and `history_ref` "
            "(structured pointer with kind/loop_id/finding_set_id — not a file path). "
            "Persisted review loops may include `finding_ids_by_set` mapping each "
            "discovery finding_set_id to finding ids introduced in that set."
        ),
        "type": "object",
        "required": ["loop_id"],
        "properties": {
            "loop_id": {"type": "string"},
            "artifact_revision": {"type": "integer"},
            "default_optional_action": {
                "type": "string",
                "enum": ["defer", "accept_as_is"],
                "description": (
                    "Apply this action to optional findings in the current "
                    "finding_set_id that lack an explicit finding_actions entry."
                ),
            },
            "finding_actions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "finding_id",
                        "action",
                        "actor_role",
                        "artifact_revision",
                        "finding_set_id",
                    ],
                    "properties": {
                        "finding_id": {"type": "string"},
                        "action": {
                            "type": "string",
                            "enum": ["fix", "defer", "accept_as_is", "challenge"],
                        },
                        "actor_role": {
                            "type": "string",
                            "enum": ["planner", "producer"],
                        },
                        "artifact_revision": {"type": "integer"},
                        "finding_set_id": {"type": "string"},
                        "rationale": {"type": "string"},
                        "challenge_reason": {
                            "type": "string",
                            "enum": [
                                "invalid",
                                "duplicate",
                                "already_satisfied",
                                "conflicts_with_contract",
                                "conflicts_with_finding",
                                "recommendation_not_viable",
                            ],
                        },
                        "proposed_disposition": {
                            "type": "string",
                            "enum": ["invalid", "superseded"],
                        },
                        "superseded_by_finding_id": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
        },
        "additionalProperties": False,
    },
    "focused-review-request": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "FocusedReviewRequest",
        "description": (
            "Optional focused review request for `tdp agent review request`. "
            "type must match scope.kind."
        ),
        "oneOf": _FOCUSED_REVIEW_BRANCH_SCHEMAS,
    },
    "amendment-request": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "AmendmentRequest",
        "description": "Controlled plan amendment request for `tdp agent production request-amendment`.",
        "type": "object",
        "required": ["evidence", "affected_refs"],
        "properties": {
            "id": {"type": "string"},
            "evidence": {"type": "string", "minLength": 1},
            "affected_refs": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string"},
            },
            "summary": {"type": "string"},
        },
        "additionalProperties": False,
    },
    "completion-claim": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "CompletionClaimRequest",
        "description": "Production completion claim for `tdp agent production submit-completion`.",
        "type": "object",
        "required": ["goal_assessment", "goal_met"],
        "properties": {
            "goal_assessment": {"type": "string", "minLength": 1},
            "goal_met": {"type": "boolean", "const": True},
            "summary": {"type": "string"},
        },
        "additionalProperties": False,
    },
    "blocker-report": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "BlockerReportRequest",
        "description": "Production blocker report for `tdp agent production report-blocked`.",
        "type": "object",
        "required": ["evidence"],
        "properties": {
            "evidence": {"type": "string", "minLength": 1},
            "affected_refs": {
                "type": "array",
                "items": {"type": "string"},
            },
            "summary": {"type": "string"},
        },
        "additionalProperties": False,
    },
}

_SCHEMAS = SCHEMAS

_EXAMPLES: dict[str, dict[str, Any]] = {
    "expand-branch": {
        "schema": "plan-transaction",
        "description": "Expand a plan branch with sibling items and a dependency edge.",
        "payload": {
            "base_revision": 0,
            "operations": [
                {
                    "op": "add_item",
                    "temp_id": "item-api",
                    "parent_id": "item-root",
                    "placement": {"last_child": True},
                    "item": {
                        "kind": "work",
                        "title": "API layer",
                        "outcome": "HTTP API exists with documented endpoints.",
                        "acceptance": ["Endpoints are testable."],
                    },
                },
                {
                    "op": "add_item",
                    "temp_id": "item-ui",
                    "parent_id": "item-root",
                    "placement": {"last_child": True},
                    "item": {
                        "kind": "work",
                        "title": "UI layer",
                        "outcome": "UI consumes the API.",
                    },
                },
                {
                    "op": "add_dependency",
                    "item_id": "item-ui",
                    "depends_on": "item-api",
                },
            ],
        },
    },
    "batch-result": {
        "schema": "production-apply",
        "description": "Record a completed production batch with artifact evidence.",
        "payload": {
            "production_revision": 0,
            "plan_items": ["item-api"],
            "dispositions": {
                "item-api": {
                    "disposition": "completed",
                    "evidence": "Implemented routes in src/api/routes.py.",
                }
            },
            "outputs": [
                {
                    "id": "output-api",
                    "type": "artifact",
                    "ref": "src/api/routes.py",
                }
            ],
            "contributions": [
                {
                    "item_id": "item-api",
                    "output_refs": ["output-api"],
                    "summary": "Added API routes.",
                }
            ],
            "summary": "API batch complete.",
            "goal_assessment": "API item satisfied for this batch.",
            "empty_output": False,
        },
    },
    "empty-output": {
        "schema": "production-apply",
        "description": "Record a batch with no new artifacts when existing output already satisfies the item.",
        "payload": {
            "production_revision": 0,
            "plan_items": ["item-docs"],
            "dispositions": {
                "item-docs": {
                    "disposition": "satisfied_without_change",
                }
            },
            "outputs": [],
            "contributions": [],
            "summary": "No new docs required.",
            "empty_output": True,
            "empty_output_reason": "Existing README already satisfies documentation requirements.",
        },
    },
    "evidence-revision": {
        "schema": "production-apply",
        "description": (
            "During whole_output_review, revise evidence for terminal items targeted "
            "by unresolved required findings."
        ),
        "payload": {
            "production_revision": 3,
            "evidence_revision": True,
            "plan_items": ["item-api"],
            "dispositions": {
                "item-api": {
                    "disposition": "completed",
                    "evidence": "Routes implemented; adding reviewer-requested artifact ref.",
                }
            },
            "outputs": [
                {
                    "id": "output-api-v2",
                    "type": "artifact",
                    "ref": "src/api/routes.py",
                }
            ],
            "contributions": [
                {
                    "item_id": "item-api",
                    "output_refs": ["output-api-v2"],
                    "summary": "Added artifact reference requested by reviewer.",
                }
            ],
            "summary": "Evidence revision for whole-output review finding.",
        },
    },
    "evidence-revision-focused": {
        "schema": "production-apply",
        "description": (
            "During production, revise evidence for terminal items targeted by an "
            "active focused_output review loop. The loop id and target_revision must "
            "match the current output revision."
        ),
        "payload": {
            "production_revision": 1,
            "evidence_revision": True,
            "focused_review_loop_id": "review-focused-output-01",
            "plan_items": ["item-api"],
            "dispositions": {
                "item-api": {
                    "disposition": "completed",
                    "evidence": "Addressed focused reviewer finding.",
                }
            },
            "outputs": [
                {
                    "id": "output-api-v2",
                    "type": "artifact",
                    "ref": "src/api/routes.py",
                }
            ],
            "contributions": [
                {
                    "item_id": "item-api",
                    "output_refs": ["output-api-v2"],
                    "summary": "Focused evidence revision.",
                }
            ],
            "summary": "Evidence revision for focused-output review finding.",
        },
    },
    "review-respond": {
        "schema": "review-respond",
        "description": (
            "Focused plan discovery: report findings with orchestrator-allocated "
            "finding_set_id echo."
        ),
        "payload": {
            "loop_id": "review-focused-plan-01",
            "target_revision": 0,
            "finding_set_id": "review-focused-plan-01-fs-01",
            "reported_findings": [
                {
                    "id": "finding-001",
                    "severity": "blocker",
                    "category": "acceptance",
                    "target_refs": ["item-api"],
                    "issue": "Acceptance criteria are not testable.",
                    "evidence": ["No measurable acceptance checks on item-api."],
                    "recommended_change": "Add concrete acceptance checks for API behavior.",
                    "status": "unresolved",
                }
            ],
            "review_completed": True,
            "summary": "One blocker finding in scope.",
        },
    },
    "review-respond-initial": {
        "schema": "review-respond",
        "description": (
            "Mandatory initial_review discovery: report findings with finding_set_id echo."
        ),
        "payload": {
            "loop_id": "review-whole-plan-01",
            "target_revision": 0,
            "stage": "initial_review",
            "finding_set_id": "review-whole-plan-01-fs-01",
            "target_digest": "plan-digest-placeholder",
            "reported_findings": [
                {
                    "id": "finding-001",
                    "severity": "major",
                    "category": "acceptance",
                    "target_refs": ["item-api"],
                    "issue": "Acceptance criteria are not testable.",
                    "evidence": ["Acceptance text is qualitative only."],
                    "recommended_change": "Add concrete acceptance checks for API behavior.",
                    "status": "unresolved",
                }
            ],
            "review_completed": True,
            "summary": "Material acceptance gap found.",
        },
    },
    "review-respond-initial-approved": {
        "schema": "review-respond",
        "description": (
            "Mandatory initial_review: clear discovery with digest binding "
            "(still requires a fresh scope_review before final gate approval)."
        ),
        "payload": {
            "loop_id": "review-whole-plan-01",
            "target_revision": 0,
            "stage": "initial_review",
            "finding_set_id": "review-whole-plan-01-fs-01",
            "reported_findings": [],
            "review_completed": True,
            "target_digest": "plan-digest-abc",
            "summary": "No material issues in initial discovery.",
        },
    },
    "review-respond-verification": {
        "schema": "review-respond",
        "description": (
            "Stage-1 finding_verification Result Contract: findings closed with "
            "verified decision."
        ),
        "payload": {
            "loop_id": "review-whole-plan-01",
            "target_revision": 1,
            "stage": "finding_verification",
            "target_digest": "plan-digest-abc",
            "finding_set_id": "review-whole-plan-01-fs-01",
            "decision": "verified",
            "finding_results": [
                {
                    "finding_id": "finding-001",
                    "disposition": "resolved",
                    "evidence": ["Updated acceptance on item-api"],
                    "direct_side_effects": [],
                }
            ],
            "new_direct_side_effect_findings": [],
            "summary": "All required findings closed; no direct side effects.",
        },
    },
    "review-respond-scope": {
        "schema": "review-respond",
        "description": (
            "Fresh scope_review discovery: clear approved outcome with empty "
            "reported_findings."
        ),
        "payload": {
            "loop_id": "review-whole-plan-01",
            "target_revision": 1,
            "stage": "scope_review",
            "finding_set_id": "review-whole-plan-01-fs-02",
            "target_digest": "plan-digest-abc",
            "scope_id": "whole_plan",
            "reported_findings": [],
            "review_completed": True,
            "acceptance_criteria_checked": [
                "coverage",
                "dependencies",
                "acceptance",
            ],
            "summary": "No remaining material issues in current scope.",
        },
    },
    "review-record-finding-actions": {
        "schema": "review-record-finding-actions",
        "description": (
            "Primary agent records fix/challenge/defer/accept_as_is owner responses "
            "for open optional findings after an advisory handoff. fix and challenge "
            "route to reviewer verification; defer and accept_as_is proceed without it. "
            "Use default_optional_action to accept or defer remaining optionals in bulk."
        ),
        "payload": {
            "loop_id": "review-focused-plan-01",
            "artifact_revision": 0,
            "default_optional_action": "accept_as_is",
            "finding_actions": [
                {
                    "finding_id": "finding-opt-01",
                    "action": "challenge",
                    "challenge_reason": "conflicts_with_contract",
                    "proposed_disposition": "invalid",
                    "actor_role": "planner",
                    "artifact_revision": 0,
                    "finding_set_id": "review-focused-plan-01-fs-01",
                    "rationale": "Conflicts with acceptance criterion 7.",
                }
            ],
        },
    },
    "focused-review-request": {
        "schema": "focused-review-request",
        "description": "Planner requests a bounded focused plan review on one branch.",
        "payload": {
            "type": "focused_plan",
            "scope": {
                "kind": "focused_plan",
                "item_ids": ["item-api"],
            },
        },
    },
    "amendment-request": {
        "schema": "amendment-request",
        "description": "Producer requests a controlled plan amendment during production.",
        "payload": {
            "evidence": "Plan item item-api omits a dependency required for batch sequencing.",
            "affected_refs": ["item-api", "item-ui"],
            "summary": "Add missing dependency before production can continue.",
        },
    },
    "completion-claim": {
        "schema": "completion-claim",
        "description": "Producer submits a completion claim after all applicable items are terminal.",
        "payload": {
            "goal_assessment": "Every applicable plan item has a terminal disposition or derived satisfaction.",
            "goal_met": True,
            "summary": "Production batches complete; ready for whole-output review.",
        },
    },
    "blocker-report": {
        "schema": "blocker-report",
        "description": "Producer reports a blocker with evidence when production cannot continue.",
        "payload": {
            "evidence": "Upstream credential rotation blocks deployment verification.",
            "affected_refs": ["item-deploy"],
            "summary": "Deployment verification cannot proceed until credentials are restored.",
        },
    },
}

AGENT_HELP_TEXT = """Top Down Planning agent CLI (tdp agent)

Discover contracts without reading source:
  tdp agent help
  tdp agent readme
  tdp agent schema [<name>]   # omit name to list published schemas
  tdp agent example [<name>]  # omit name to list published examples

Plan:
  tdp agent plan snapshot --run <run-id> [--view active|audit|ready|issues]
  tdp agent plan apply --run <run-id> --request $TDP_AGENT_REQUESTS_DIR/plan-apply-r<rev>-a01.json
  tdp agent plan check --run <run-id> [--mode draft|approval]

Production:
  tdp agent production snapshot --run <run-id> [--view tree|ready]
  tdp agent production apply --run <run-id> --request $TDP_AGENT_REQUESTS_DIR/production-apply-batch-01-a01.json
  tdp agent production check --run <run-id>
  tdp agent production request-amendment --run <run-id> --request $TDP_AGENT_REQUESTS_DIR/production-amendment-a01.json
  tdp agent production submit-completion --run <run-id> --request $TDP_AGENT_REQUESTS_DIR/production-completion-a01.json
  tdp agent production report-blocked --run <run-id> --request $TDP_AGENT_REQUESTS_DIR/production-blocked-a01.json

Review:
  tdp agent review request --run <run-id> --request $TDP_AGENT_REQUESTS_DIR/review-request-<scope>-a01.json
  tdp agent review respond --run <run-id> --request $TDP_AGENT_REQUESTS_DIR/review-respond-<stage>-r<rev>-a01.json

Whole-plan and focused_plan reviewers receive an embedded plan snapshot in the
review package; call `tdp agent plan snapshot --run <run-id> --view active` to
refresh before responding when the plan may have changed.

Run status:
  tdp agent run status --run <run-id>

Run store: agent commands use --runs-dir, $TDP_RUNS_DIR, or ./runs. Run ids use
run-YYYYMMDDTHHMMSS-<6hex> (UTC creation time plus random suffix). Provider
subprocesses receive TDP_RUNS_DIR, TDP_RUN_ID, TDP_AGENT_REQUESTS_DIR, and a
session-scoped TDP_CAPABILITY_TOKEN before turns that may call mutating commands.
Write mutating request payloads only under $TDP_AGENT_REQUESTS_DIR.
Reviewer sessions allocate a provider session id, bind the token, then deliver the
review package on the next turn. Mutating commands require the token; authorization
is bound to run phase and session role, not a self-declared flag.

Published schemas: """ + ", ".join(PUBLIC_SCHEMAS) + """
Published examples: """ + ", ".join(PUBLIC_EXAMPLES) + """

Request bodies are JSON or YAML objects. Use --request under $TDP_AGENT_REQUESTS_DIR
or pipe stdin. Revision fields (base_revision, production_revision) must match the
latest snapshot.
"""

AGENT_README_TEXT = """# Top Down Planning — agent protocol

`tdp` orchestrates planning and production. Agents interact only through `tdp agent`
shell commands; those commands persist mutations to the run store. The orchestrator
observes store changes after each provider turn, runs pending review loops, and
advances phases when agents emit explicit completion signals (`candidate_plan_ready`,
`batch_complete`, `amendment_revision_ready`, etc.) as the final assistant line or
`done.signal` metadata.

## Session roles and authorization

The orchestrator binds one primary planner, producer, or reviewer session per phase.
Mutating `tdp agent` commands require the session capability token exported as
`TDP_CAPABILITY_TOKEN` on the provider subprocess that runs the turn. Reviewer
sessions allocate a provider session id, bind the token, then deliver the review
package (or a mandatory `finding_verification` recheck) via `send` before the agent may call
`tdp agent review respond`. Authorization checks phase, allowed operations, the bound
provider session, and (for reviewers) the review loop. Capability records store
only a `secret_hash`; tokens are revoked when turns, loops, or phases end. Agents
do not pass `--role` on the CLI.

- planner — mutate the plan during planning or amendment
- producer — record production batches, completion claims, blockers, amendment requests
- reviewer — submit review findings and decisions

## Agent request inputs (`agent-requests/`)

Mutating `tdp agent` commands accept JSON or YAML via `--request` under
`$TDP_AGENT_REQUESTS_DIR` or via stdin. The orchestrator exports
`TDP_AGENT_REQUESTS_DIR` (absolute path to `<run-id>/agent-requests/`) as the
designated write surface for agent-authored request files. Request files are
durable but non-canonical: retained for debugging and postmortems, included when
the run folder is copied or archived, never required for resume or recovery, and
outside commit transactions. Payloads may contain sensitive workspace or review
content — treat exported run directories accordingly.

Provider subprocesses also receive `TDP_RUNS_DIR`, `TDP_RUN_ID`, and
`TDP_CAPABILITY_TOKEN`. When capability context is active, `TDP_RUN_ID` must match
`--run`. All `--request` file paths must resolve inside `agent-requests/`.

Each mutating invocation emits two correlated audit events in `events.jsonl`,
linked by `request_id`:

- `agent_request_read` — immediately after raw bytes are read and hashed (before
  JSON parse), with `source_kind` (`agent_requests` or `stdin`) and normalized
  `source`
- `agent_request_completed` — when the command finishes, with `result`:
  `applied` (mutation committed), `rejected` (expected refusal including malformed
  JSON or schema errors), or `failed` (unexpected technical failure)

An `agent_request_read` without a matching `agent_request_completed` indicates the
process was interrupted after consuming the request. Request audit events are
append-only observability records and are not rolled back when plan, production,
or review commits fail. Canonical mutation events (`plan_applied`,
`review_responded`, etc.) include `request_id` when emitted from a request path.

Discover `agent_requests_dir` via `tdp status --stream-json` or
`tdp agent run status --run <run-id>`.

## Provider session packages

Fresh planner and producer sessions receive a context manifest. Reviewer sessions
receive a review package on the first turn (and on cold resume). Each package may
include:

- `input_refs` — resolved authoritative input paths (from `run.input_refs`)
- `output_goal` — frozen deliverable contract text (from `plan.output_goal`)
- `protocol_instructions` — role behavior rules surfaced at the top of the
  provider prompt (for example: mutate run state only through `tdp agent` commands;
  do not use host planning modes or planning-only artifacts)
- `tool_instructions` — concrete `tdp agent` command templates for the active role
- `agent_context` — supporting `guidance`, `resources`, and optional `skills`
  (do not repeat `run.input_refs` or the output-goal file under `resources`;
  overlaps are rejected). Guidance is advisory and not merged into
  `protocol_instructions`.
- Producer packages include `approved_plan` (compact plan metadata + items with `kind`)
- Review packages include `plan_scope`, `boundaries`, and `acceptance` from persisted
  plan metadata (not static run config)

The provider adapter formats these payloads for the agent. Follow
`protocol_instructions` and `tool_instructions`; host IDE planning artifacts are
not consumed by the orchestrator.

## Workflow

1. Planner expands the plan with `plan apply` until `candidate_plan_ready`.
   Each `add_item` requires `kind`: `work` for batchable leaves, `aggregate` for
   grouping-only parents. The seeded root is `aggregate`. Use `update_plan` to
   revise plan-level `scope`, `boundaries`, `constraints`, `assumptions`, and
   `acceptance` (seeded from `run.boundaries` / `run.acceptance` at run creation).
2. Mandatory whole-plan review (`review respond`) must complete the gate before production.
   Stages: `initial_review` (discovery), optional `finding_verification` (close known
   findings after revisions), then fresh `scope_review` (complete-scope discovery).
   Each stage requires `stage` plus Result Contract fields — see
   `review-respond-initial`, `review-respond-initial-approved`, `review-respond-verification`, and `review-respond-scope`.
   Review packages include an embedded plan tree and optional `rubric` on initial
   review only; refresh with `plan snapshot --view active` when revising after
   `needs_revision` or initial `changes_requested`. Reviewers prioritize plan
   correctness and internal consistency. Approval requires a clear
   fresh `scope_review` against the current artifact digest — finding closure alone is not
   enough.
3. Producer records batches with `production apply`, then `submit-completion` with
   `goal_met: true` and a `goal_assessment` rationale. Production `ready` snapshots
   expose `ready_items` (contracts per ready leaf) alongside `ready_item_ids`.
4. Mandatory whole-output review must complete the gate before `outcome: accepted`.
   Same mandatory gate as whole-plan review (`initial_review`, then
   repeatable verification and fresh `scope_review` rounds). Review packages include
   production traceability, an optional `rubric` on initial review only, and
   reviewer guidance that prioritizes output correctness and cross-artifact
   consistency. After `needs_revision` or initial
   `changes_requested`, the producer must use `production apply` with
   `evidence_revision: true` and **new** output evidence IDs on terminal items
   targeted by unresolved required findings (dispositions unchanged), then
   re-submit completion with `goal_met: true`. During production, focused-output
   evidence revision also requires `focused_review_loop_id` bound to the loop's
   `target_revision`. Plan amendment is not available during whole-output review.
5. Optional focused reviews use `review request` with bounded `scope.item_ids`.
   Focused plan reviewers receive the same embedded plan snapshot guidance as
   whole-plan review.

## Run store

Agent commands locate runs via `--runs-dir`, `$TDP_RUNS_DIR`, or `./runs` (in that
precedence). Provider subprocesses receive `TDP_RUNS_DIR`, `TDP_RUN_ID`,
`TDP_AGENT_REQUESTS_DIR`, and a session-scoped `TDP_CAPABILITY_TOKEN`, so in-agent
commands typically need only `--run <run-id>`. Run ids use
`run-YYYYMMDDTHHMMSS-<6hex>` (UTC creation time plus random suffix).

`plan.json` items include `depth` (0-based from the tree root, derived from
`parent_id`). Depth is required on load and recomputed on save.

`digests.context_spec` binds agent-context **declarations** at run creation: role models,
configured guidance entries, resource path selection, skill paths, and the resolved
`context_snapshot` exclusion policy (defaults, ordered patterns, built-in policy version).
`digests.context_snapshot` binds materialized resource bytes, skill contents, and guidance
text/file digests via `context_snapshot_binding` (compact relative-path → bare SHA-256 hex
maps; guidance remains a list of digest entries). Exclusions apply to resource collection
only — skills and guidance stay bound. Direct file resources always bind; directory/glob
discoveries are filtered. Each `production apply` validates cumulative snapshot drift
against the candidate batch outputs; production completion re-validates and rebases the
snapshot when drift is attributable to production evidence (same canonical relative paths
as evidence `ref`); unauthorized drift blocks apply retry, completion, or resume. Resource paths and evidence refs must
resolve inside the workspace; escapes and absolute refs fail explicitly. Invalid
persisted evidence refs fail rebase validation rather than masquerading as unauthorized
drift. `.gitignore` is not inherited. Omitting
`context_snapshot` equals `excludes.defaults: true` with empty user patterns.

Run records carry top-level `schema_version` (currently `3`), distinct from config document
`version`. Old absolute-path or list-shaped bindings and unsupported schema versions are
rejected — recreate the run; there is no migrator. Prefer snapshot excludes over
`PYTHONDONTWRITEBYTECODE=1` as the durable fix for bytecode false positives.

`digests.config_contract` binds approval-meaning configuration (input/output goal semantics,
boundaries, acceptance, review policy, context declarations). `digests.config_execution`
binds operational limits and execution budgets. Approvals bind to `config_contract`, not
`config_execution`. The monolithic `digests.config` field is not accepted on schema v3.

Run lifecycle fields on `run.json`: `status` (`running`, `paused`, `completed`, `failed`);
`outcome` (non-null only when `status` is `completed`); `stop` (structured stop record
when paused or failed, otherwise null); `phase_action_id` (stable logical action id for
the current provider step, or null). Paused stops use `category: operational` with
`code` in `limit_exhausted`, `review_incomplete`, `provider_unavailable`,
`provider_turn_failed`, `user_cancelled`, or `amendment_pending` (internal amendment
checkpoint); failed stops use `category: invariant` with
`code` in `state_integrity_failure`, `evidence_integrity_failure`,
`unsupported_phase_state`, `orchestrator_invariant_failure`, or
`session_recovery_exhausted`. Each stop record includes `phase`, `message`, `role`
(null when unset), and optional `details`.

## Resume

Paused runs resume through `prepare_resume()` (read-only) and
`apply_resume_plan_atomically()` (config + status transition). The CLI wraps both:

- `tdp resume --run <id> --config <yaml>` — apply candidate config and continue
- `tdp resume --run <id> --set limits.planning.max_agent_turns=40` — limit-only override
- `tdp resume --run <id> --check ...` — print the resume plan; no writes or provider calls
- `tdp resume --run <id> --until plan|validated|completed` — loop `RunEngine` after apply
  (default: one orchestrator step)

Limit-only increases update `digests.config_execution` only; approvals remain bound to
`digests.config_contract`. Failed runs cannot be resumed. Replacement exhausted for the
current `phase_action_id` blocks resume until the action completes or the run fails.

Production `outputs` in apply requests need only `id`, `type`, and workspace `ref`.
The service captures content hashes and stores immutable snapshots under
`artifacts/<snapshot-uuid>/<filename>` in the run store. Reusing an evidence ID
across batches is rejected. When snapshot-bound paths drift during production,
every changed path must be declared in the batch `outputs`; otherwise apply
returns `production_evidence_incomplete` (workspace paths — add to outputs and
retry) or `production_context_mutation_unauthorized` (skills, file or inline
guidance, and similar non-output binding keys). Snapshot validation runs before artifact capture
and before `production.json` is updated. Production completion re-validates the
same authorization model before rebasing the context snapshot.

## Discoverability

- `tdp agent schema [<name>]` — JSON Schema for request/config contracts
- `tdp agent example [<name>]` — minimal valid example payloads
- `tdp agent help` — command summary

## Revision safety

Plan apply requires `base_revision` from `plan snapshot`. Production apply requires
`production_revision` from `production snapshot`. Stale revisions return a conflict
error with instructions to refresh the snapshot.

Completion claims require `goal_met: true` plus non-empty `goal_assessment`. During
`whole_output_review`, set `evidence_revision: true` on `production apply` with new
output evidence IDs when revising terminal items after reviewer `changes_requested`.
During `production`, focused-output evidence revision requires `focused_review_loop_id`
and matches the loop `target_revision` to the current `output_revision`.

Plan `snapshot` and `check` responses separate validation `issues` (errors with
`code`, `message`, optional `path`) from `warnings` (human-readable strings).
`apply` returns the same split plus mutation budget warnings and sets
`applied: true` only when the batch was persisted. Mutations that would introduce
new hard validation errors are rejected before persistence with `operation_error`
and leave the plan revision unchanged. `ok` is true only when validation has no
error-severity issues after a persisted apply (inspect `issues` after apply even
when `applied: true` for pre-existing draft issues). Production `snapshot` uses the same plan validation shape;
use `production check` for batch/disposition-specific checks. Tree item
snapshots include `scope`, `boundaries`, and `acceptance` alongside core
planning fields. Plan `ready` views exclude items blocked by unresolved
`focused_plan` / `whole_plan` findings; production `ready` views exclude items
blocked by unresolved `focused_output` / `whole_output` findings. Plans carry
`schema_version` (currently 1). `check --mode approval` always runs
approval-mode soft limits; digest and whole-plan review hooks compare against a
stored approval when one exists for the current revision, otherwise surface
`*_not_checked` warnings. Prefer dependency edges on the narrowest meaningful
plan item when a more specific descendant already captures the prerequisite.

`plan snapshot`, `plan apply`, and `plan check` exit 0 only when `ok` is true.
`production snapshot` and `production check` follow the same rule. A persisted
`plan apply` may return `applied: true` with exit 1 only when post-apply validation
reports pre-existing error-severity issues that the mutation did not introduce.
`production apply` returns `ok: true` when the batch was persisted;
use `production snapshot` or `production check` for plan validation.

## Further reading

Package README: tools/top_down_planning/README.md
"""


def list_schema_names() -> list[str]:
    return list(PUBLIC_SCHEMAS)


def list_example_names() -> list[str]:
    return list(PUBLIC_EXAMPLES)


def show_schema(name: str) -> dict[str, Any]:
    if name not in _SCHEMAS:
        raise KeyError(name)
    return deepcopy(_SCHEMAS[name])


def show_example(name: str) -> dict[str, Any]:
    if name not in _EXAMPLES:
        raise KeyError(name)
    entry = deepcopy(_EXAMPLES[name])
    return {
        "name": name,
        "schema": entry["schema"],
        "description": entry["description"],
        "payload": entry["payload"],
    }


def unknown_schema_response(name: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "code": "unknown_schema",
            "message": f"unknown schema: {name!r}",
        },
        "available": list_schema_names(),
    }


def unknown_example_response(name: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "code": "unknown_example",
            "message": f"unknown example: {name!r}",
        },
        "available": list_example_names(),
    }


def schema_list_payload() -> dict[str, Any]:
    return {
        "ok": True,
        "schemas": [
            {
                "name": name,
                "title": _SCHEMAS[name].get("title", name),
                "description": _SCHEMAS[name].get("description", ""),
            }
            for name in PUBLIC_SCHEMAS
        ],
    }


def example_list_payload() -> dict[str, Any]:
    return {
        "ok": True,
        "examples": [
            {
                "name": name,
                "schema": _EXAMPLES[name]["schema"],
                "description": _EXAMPLES[name]["description"],
            }
            for name in PUBLIC_EXAMPLES
        ],
    }


def validate_example(name: str) -> list[str]:
    """Validate an example payload against its schema; return issue messages."""

    entry = _EXAMPLES.get(name)
    if entry is None:
        raise KeyError(name)
    schema_name = str(entry["schema"])
    schema = _SCHEMAS.get(schema_name)
    if schema is None:
        return [f"missing schema for example: {schema_name}"]
    return validate_against_schema(entry["payload"], schema)


def default_config_example() -> dict[str, Any]:
    """Return a copy of built-in defaults for schema smoke tests."""

    return deepcopy(DEFAULT_CONFIG)
