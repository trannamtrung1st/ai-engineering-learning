"""CLI-discoverable schemas, examples, and agent help for ``tdp agent``."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from core_tools.schema import validate_against_schema

from top_down_planning.config.activities import ALLOWED_AGENT_ACTIVITIES, ALLOWED_AGENT_ROLES
from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.domain.dispositions import TERMINAL_DISPOSITIONS
from top_down_planning.domain.mandatory_audit_passes import (
    WHOLE_OUTPUT_AUDIT_PASS_IDS,
    WHOLE_PLAN_AUDIT_PASS_IDS,
)
from top_down_planning.domain.review_policy import (
    CATEGORY_DEFINITIONS,
    FINDING_CATEGORY_ORDER,
    SEVERITY_ORDER,
)
from top_down_planning.domain.review_rule_registry import BUILTIN_RULE_DESCRIPTIONS
from top_down_planning.orchestrator.review_analysis_context import rubric_items_with_ids

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
    "agent-error",
    "plan-apply-response",
    "plan-snapshot-response",
    "plan-check-response",
    "production-apply-response",
    "production-snapshot-response",
    "production-check-response",
    "production-amendment-response",
    "production-completion-response",
    "production-blocker-response",
    "run-status-response",
    "focused-review-request-response",
    "review-respond-response",
    "review-record-finding-actions-response",
)

PUBLIC_EXAMPLES: tuple[str, ...] = (
    "expand-branch",
    "batch-result",
    "empty-output",
    "evidence-revision",
    "evidence-revision-focused",
    "review-respond",
    "review-respond-focused-with-instance-ref",
    "review-respond-family-discovery-focused-plan",
    "review-respond-family-discovery-focused-output",
    "review-respond-verification",
    "review-respond-scope",
    "review-respond-family-discovery",
    "review-respond-family-discovery-output",
    "review-respond-family-verification",
    "review-respond-family-verification-output",
    "review-record-finding-actions",
    "review-record-family-fix",
    "review-record-family-fix-output",
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
        "depends_on": {
            "description": (
                "Execution prerequisites: stable item ids or temp_id values from "
                "other add_item ops in the same transaction. Accepts a string or "
                "array at runtime (coerced to array)."
            ),
            "oneOf": [
                {"type": "string"},
                {"type": "array", "items": {"type": "string"}},
            ],
        },
        "acceptance": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "source_refs": {"type": "array", "items": {"type": "string", "minLength": 1}},
    },
    "additionalProperties": False,
}

_SINGLE_DEPENDENCY_EDGE_SCHEMA: dict[str, Any] = {
    "description": (
        "One dependency target: stable item id or temp_id. Accepts a string or "
        "single-element array at runtime."
    ),
    "oneOf": [
        {"type": "string"},
        {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 1,
        },
    ],
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
        "risks": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "source_refs": {"type": "array", "items": {"type": "string", "minLength": 1}},
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
        "risks": {"type": "array", "items": {"type": "string", "minLength": 1}},
    },
    "additionalProperties": False,
}

_PLACEMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "first_child": {"type": "boolean"},
        "last_child": {"type": "boolean"},
        "before": {"type": "string"},
        "after": {"type": "string"},
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
                "parent_id": {"type": "string"},
                "placement": _PLACEMENT_SCHEMA,
                "item": _PLAN_ITEM_INPUT_SCHEMA,
            },
            "additionalProperties": False,
        },
        {
            "type": "object",
            "required": ["op", "item_id", "patch"],
            "properties": {
                "op": {"const": "update_item"},
                "item_id": {"type": "string"},
                "patch": _PLAN_ITEM_PATCH_SCHEMA,
            },
            "additionalProperties": False,
        },
        {
            "type": "object",
            "required": ["op", "patch"],
            "properties": {
                "op": {"const": "update_plan"},
                "patch": _PLAN_METADATA_PATCH_SCHEMA,
            },
            "additionalProperties": False,
        },
        {
            "type": "object",
            "required": ["op", "item_id", "new_parent_id"],
            "properties": {
                "op": {"const": "move_subtree"},
                "item_id": {"type": "string"},
                "new_parent_id": {"type": "string"},
                "placement": _PLACEMENT_SCHEMA,
            },
            "additionalProperties": False,
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
            "additionalProperties": False,
        },
        {
            "type": "object",
            "required": ["op", "item_id"],
            "properties": {
                "op": {"const": "remove_item"},
                "item_id": {"type": "string"},
            },
            "additionalProperties": False,
        },
        {
            "type": "object",
            "required": ["op", "item_id", "depends_on"],
            "description": (
                "Add one dependency edge to an existing item. For new items in the "
                "same batch, prefer inline add_item.item.depends_on."
            ),
            "properties": {
                "op": {"const": "add_dependency"},
                "item_id": {"type": "string"},
                "depends_on": _SINGLE_DEPENDENCY_EDGE_SCHEMA,
            },
            "additionalProperties": False,
        },
        {
            "type": "object",
            "required": ["op", "item_id", "depends_on"],
            "properties": {
                "op": {"const": "remove_dependency"},
                "item_id": {"type": "string"},
                "depends_on": _SINGLE_DEPENDENCY_EDGE_SCHEMA,
            },
            "additionalProperties": False,
        },
        {
            "type": "object",
            "required": ["op", "item_id", "depends_on"],
            "properties": {
                "op": {"const": "replace_dependencies"},
                "item_id": {"type": "string"},
                "depends_on": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": False,
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
            "enum": list(SEVERITY_ORDER),
        },
        "category": {
            "type": "string",
            "enum": list(FINDING_CATEGORY_ORDER),
        },
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
        "instance_ref": {
            "type": "object",
            "description": (
                "Optional structured artifact reference for focused reviews "
                "(must stay within scope.item_ids when present)."
            ),
        },
    },
    "additionalProperties": False,
}

_FAMILY_PROTOCOL_FINDING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "id",
        "family_id",
        "instance_ref",
        "severity",
        "category",
        "target_refs",
        "issue",
        "recommended_change",
    ],
    "properties": {
        "id": {"type": "string", "maxLength": 128},
        "family_id": {"type": "string", "maxLength": 128},
        "instance_ref": {"type": "object"},
        "severity": {
            "type": "string",
            "enum": list(SEVERITY_ORDER),
        },
        "category": {
            "type": "string",
            "enum": list(FINDING_CATEGORY_ORDER),
        },
        "target_refs": {
            "type": "array",
            "items": {"type": "string", "maxLength": 128},
        },
        "issue": {"type": "string", "maxLength": 4000},
        "evidence": {
            "type": "array",
            "items": {"type": "string", "maxLength": 512},
        },
        "recommended_change": {"type": "string", "maxLength": 4000},
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

_DISCOVERY_SWEEP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["completed"],
    "properties": {
        "searched_refs": {
            "type": "array",
            "items": {"type": "string", "maxLength": 256},
        },
        "search_dimensions": {
            "type": "array",
            "items": {"type": "string", "maxLength": 128},
        },
        "completed": {"type": "boolean"},
        "summary": {"type": "string", "maxLength": 4000},
        "evidence": {
            "type": "array",
            "items": {"type": "string", "maxLength": 512},
        },
    },
    "additionalProperties": False,
}

_VERIFICATION_SWEEP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["completed"],
    "properties": {
        "searched_refs": {
            "type": "array",
            "items": {"type": "string", "maxLength": 256},
        },
        "search_dimensions": {
            "type": "array",
            "items": {"type": "string", "maxLength": 128},
        },
        "remaining_instance_refs": {
            "type": "array",
            "items": {"type": "object"},
        },
        "completed": {"type": "boolean"},
        "summary": {"type": "string", "maxLength": 4000},
        "evidence": {
            "type": "array",
            "items": {"type": "string", "maxLength": 512},
        },
    },
    "additionalProperties": False,
}

_OWNER_SWEEP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["completed"],
    "properties": {
        "searched_refs": {
            "type": "array",
            "items": {"type": "string", "maxLength": 256},
        },
        "search_dimensions": {
            "type": "array",
            "items": {"type": "string", "maxLength": 128},
        },
        "additional_fixed_refs": {
            "type": "array",
            "items": {"type": "object"},
        },
        "remaining_instance_refs": {
            "type": "array",
            "items": {"type": "object"},
        },
        "completed": {"type": "boolean"},
        "summary": {"type": "string", "maxLength": 4000},
        "evidence": {
            "type": "array",
            "items": {"type": "string", "maxLength": 512},
        },
    },
    "additionalProperties": False,
}

_FAMILY_FIX_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["family_id", "owner_sweep"],
    "properties": {
        "family_id": {"type": "string", "maxLength": 128},
        "target_finding_ids": {
            "type": "array",
            "items": {"type": "string", "maxLength": 128},
        },
        "rationale": {"type": "string", "maxLength": 4000},
        "changed_refs": {
            "type": "array",
            "items": {"type": "string", "maxLength": 128},
        },
        "owner_sweep": _OWNER_SWEEP_SCHEMA,
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
    "required": ["item_ids"],
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
        "required": ["type", "scope", "target_revision", "target_digest"],
        "properties": {
            "type": {"const": review_type},
            "scope": _FOCUSED_REVIEW_SCOPE_SCHEMA,
            "target_revision": {"type": "integer"},
            "target_digest": {"type": "string", "minLength": 1},
        },
        "additionalProperties": False,
    }
    for review_type in ("focused_plan", "focused_output")
]

_FAMILY_RULE_ID_PROPERTY: dict[str, Any] = {
    "type": "string",
    "maxLength": 128,
    "description": (
        "Built-in rule from `tdp agent readme` (section Built-in finding-family "
        "rule_id values) or custom.<slug> (lowercase slug, hyphens) with "
        "rule_definition. Built-in rules must not include rule_definition."
    ),
}

_FAMILY_DISCOVERY_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "id",
        "rule_id",
        "subject_key",
        "title",
        "confirmed_finding_ids",
        "discovery_sweep",
    ],
    "properties": {
        "id": {"type": "string", "maxLength": 128},
        "rule_id": _FAMILY_RULE_ID_PROPERTY,
        "subject_key": {"type": "string", "maxLength": 256},
        "scope_kind": {
            "type": "string",
            "enum": [
                "active-plan",
                "focused-plan",
                "whole-output",
                "focused-output",
            ],
            "description": (
                "Optional; service may derive scope_kind from review context when omitted."
            ),
        },
        "rule_definition": {"type": "string", "maxLength": 4000},
        "title": {"type": "string", "maxLength": 512},
        "seed_finding_id": {"type": "string", "maxLength": 128},
        "confirmed_finding_ids": {
            "type": "array",
            "items": {"type": "string", "maxLength": 128},
        },
        "candidate_refs": {
            "type": "array",
            "items": {"type": "object"},
        },
        "recommended_change": {"type": "string", "maxLength": 4000},
        "discovery_sweep": _DISCOVERY_SWEEP_SCHEMA,
    },
    "additionalProperties": False,
}

_AUDIT_PASS_RUBRIC_ITEM_IDS_PROPERTY: dict[str, Any] = {
    "type": "array",
    "items": {"type": "string", "maxLength": 128},
    "description": (
        "Ids from the delivered review package `rubric_items` (union across passes "
        "must equal the set of every rubric_items[].id when review_completed is "
        "true; no missing or extra ids). Do not copy ids from static examples."
    ),
}

_MANDATORY_FAMILY_ADAPTATION = (
    "Adapt before submit: rubric_item_ids from review package rubric_items "
    "(union across passes must equal every rubric_items[].id); pass_id from "
    "required_audit_passes; rule_id from tdp agent readme built-ins or "
    "custom.<slug>; instance_ref shape from the matching example."
)

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
        "title": "FocusedFamilyDiscoveryRespond",
        "type": "object",
        "required": [
            "loop_id",
            "target_revision",
            "finding_set_id",
            "finding_families",
            "reported_findings",
            "review_completed",
            "summary",
        ],
        "properties": {
            "loop_id": {"type": "string"},
            "target_revision": {"type": "integer"},
            "finding_set_id": {"type": "string"},
            "target_digest": {"type": "string"},
            "finding_families": {
                "type": "array",
                "items": _FAMILY_DISCOVERY_ITEM_SCHEMA,
            },
            "reported_findings": {
                "type": "array",
                "items": _FAMILY_PROTOCOL_FINDING_SCHEMA,
            },
            "review_completed": {"type": "boolean"},
            "summary": {"type": "string"},
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
        "title": "MandatoryFamilyDiscoveryRespond",
        "type": "object",
        "required": [
            "loop_id",
            "target_revision",
            "stage",
            "finding_set_id",
            "target_digest",
            "reported_findings",
            "finding_families",
            "audit_attestation",
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
            "target_digest": {"type": "string", "minLength": 1},
            "reported_findings": {
                "type": "array",
                "items": _FAMILY_PROTOCOL_FINDING_SCHEMA,
            },
            "finding_families": {
                "type": "array",
                "items": _FAMILY_DISCOVERY_ITEM_SCHEMA,
            },
            "audit_attestation": {
                "type": "object",
                "description": (
                    "Mandatory discovery attestation. pass_id values must match "
                    "delivered required_audit_passes; rubric_item_ids union must "
                    "equal every rubric_items[].id when review_completed is true. "
                    "See `tdp agent readme`, section Audit attestation."
                ),
                "required": ["passes"],
                "properties": {
                    "passes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["pass_id", "completed"],
                            "properties": {
                                "pass_id": {
                                    "type": "string",
                                    "maxLength": 128,
                                    "description": (
                                        "Must match a pass from delivered "
                                        "required_audit_passes."
                                    ),
                                },
                                "completed": {"type": "boolean"},
                                "scope_id": {"type": "string", "maxLength": 128},
                                "search_dimensions": {
                                    "type": "array",
                                    "items": {"type": "string", "maxLength": 128},
                                },
                                "inspected_refs": {
                                    "type": "array",
                                    "items": {"type": "string", "maxLength": 256},
                                },
                                "rubric_item_ids": _AUDIT_PASS_RUBRIC_ITEM_IDS_PROPERTY,
                                "summary": {"type": "string", "maxLength": 4000},
                            },
                            "additionalProperties": False,
                        },
                    },
                },
                "additionalProperties": False,
            },
            "review_completed": {"type": "boolean"},
            "summary": {"type": "string"},
            "block_review": {"type": "boolean"},
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
            "family_results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["family_id", "disposition", "verification_sweep"],
                    "properties": {
                        "family_id": {"type": "string", "maxLength": 128},
                        "disposition": {
                            "type": "string",
                            "enum": ["closed", "open"],
                        },
                        "verification_sweep": _VERIFICATION_SWEEP_SCHEMA,
                        "remaining_instance_findings": {
                            "type": "array",
                            "items": _FAMILY_PROTOCOL_FINDING_SCHEMA,
                        },
                    },
                    "additionalProperties": False,
                },
            },
            "summary": {"type": "string"},
        },
        "additionalProperties": False,
    },
]

_AGENT_CONTEXT_OVERLAY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "model": {"type": "string"},
        "guidance": {
            "type": "array",
            "description": (
                "Advisory working preferences. Each entry is exactly one of "
                "{text: ...} or {file: ...}. Text and file values must be "
                "non-empty after trimming whitespace."
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
                                    "Inline guidance; must contain at least one "
                                    "non-whitespace character."
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
                                    "Workspace-relative guidance file path; must "
                                    "contain at least one non-whitespace character."
                                ),
                            },
                        },
                        "additionalProperties": False,
                    },
                ],
            },
        },
        "resources": {"type": "array", "items": {"type": "string"}},
        "skills": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}


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
                    "Activity-aware agent overlays. Effective context merges "
                    "agent_context.default, agent_context.roles.<role>, and "
                    "agent_context.activities.<activity> for each orchestrator "
                    "turn. Packaged TDP agent skills are auto-injected for every "
                    "role unless agent_context.bundled_skills is false. Guidance, "
                    "resources, and configured skills are additive with "
                    "agent_context.default; duplicate resource paths between "
                    "layers are deduped at resolve time. Guidance is advisory only "
                    "and does not change acceptance, enforcement, or lifecycle "
                    "transitions. Run contracts (run.input_refs, run.output_goal / "
                    "run.output_goal_file) are supplied automatically and must not "
                    "be repeated under resources."
                ),
                "properties": {
                    "bundled_skills": {
                        "type": "boolean",
                        "description": (
                            "When true (default), inject packaged TDP agent skills "
                            "(shared + role-specific) into every session without "
                            "listing them under agent_context.*.skills."
                        ),
                        "default": True,
                    },
                    "default": deepcopy(_AGENT_CONTEXT_OVERLAY_SCHEMA),
                    "roles": {
                        "type": "object",
                        "description": (
                            "Role-level overlays merged before the activity layer."
                        ),
                        "properties": {
                            role: deepcopy(_AGENT_CONTEXT_OVERLAY_SCHEMA)
                            for role in sorted(ALLOWED_AGENT_ROLES)
                        },
                        "additionalProperties": False,
                    },
                    "activities": {
                        "type": "object",
                        "description": (
                            "Per-activity overlays for orchestrator turns. Activity "
                            "names are fixed; role bindings are code-owned."
                        ),
                        "properties": {
                            activity: deepcopy(_AGENT_CONTEXT_OVERLAY_SCHEMA)
                            for activity in sorted(ALLOWED_AGENT_ACTIVITIES)
                        },
                        "additionalProperties": False,
                    },
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
            "notifications": {
                "type": "object",
                "properties": {
                    "enabled": {"type": "boolean"},
                    "terminal": {"type": "boolean"},
                    "phase": {"type": "boolean"},
                    "progress": {"type": "boolean"},
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
                            "max_revision_cycles_per_loop": {
                                "type": "integer",
                                "description": (
                                    "Maximum owner revision attempts per focused "
                                    "plan review loop (exact N semantics; same as "
                                    "limits.whole_plan_review.max_revision_cycles)."
                                ),
                            },
                        },
                        "additionalProperties": False,
                    },
                    "whole_plan_review": {
                        "type": "object",
                        "properties": {
                            "max_revision_cycles": {
                                "type": "integer",
                                "description": (
                                    "Maximum owner revision attempts per mandatory "
                                    "whole-plan review loop (exact N: limit 1 allows "
                                    "one owner revision; the next revision trigger "
                                    "pauses with limit_exhausted)."
                                ),
                            },
                            "max_scope_review_rounds": {
                                "type": "integer",
                                "description": (
                                    "Maximum fresh scope-complete review "
                                    "rounds per whole-plan review phase. "
                                    "Resuming after limit_exhausted with a "
                                    "higher value continues the same review "
                                    "loop and preserved scope_review_rounds "
                                    "counter (does not open a new loop)."
                                ),
                            },
                        },
                        "additionalProperties": False,
                    },
                    "production": {
                        "type": "object",
                        "properties": {
                            "max_batches": {"type": "integer"},
                            "max_agent_turns_per_batch": {
                                "type": "integer",
                                "description": (
                                    "Maximum unfinished producer turns per batch "
                                    "(exact N: turn N+1 is not started when count "
                                    "reaches this limit)."
                                ),
                            },
                        },
                        "additionalProperties": False,
                    },
                    "focused_output_review": {
                        "type": "object",
                        "properties": {
                            "max_loops": {"type": "integer"},
                            "max_revision_cycles_per_loop": {
                                "type": "integer",
                                "description": (
                                    "Maximum owner revision attempts per focused "
                                    "output review loop (exact N semantics; same as "
                                    "limits.whole_output_review.max_revision_cycles)."
                                ),
                            },
                        },
                        "additionalProperties": False,
                    },
                    "whole_output_review": {
                        "type": "object",
                        "properties": {
                            "max_revision_cycles": {
                                "type": "integer",
                                "description": (
                                    "Maximum owner revision attempts per mandatory "
                                    "whole-output review loop (exact N: limit 1 allows "
                                    "one owner revision; the next revision trigger "
                                    "pauses with limit_exhausted)."
                                ),
                            },
                            "max_scope_review_rounds": {
                                "type": "integer",
                                "description": (
                                    "Maximum fresh scope-complete review "
                                    "rounds per whole-output review phase. "
                                    "Resuming after limit_exhausted with a "
                                    "higher value continues the same review "
                                    "loop and preserved scope_review_rounds "
                                    "counter (does not open a new loop)."
                                ),
                            },
                        },
                        "additionalProperties": False,
                    },
                    "amendment": {
                        "type": "object",
                        "properties": {
                            "max_requests": {"type": "integer"},
                            "max_revision_cycles_per_request": {
                                "type": "integer",
                                "description": (
                                    "Maximum planner turns per plan-amendment "
                                    "request (exact N: pause before turn N+1)."
                                ),
                            },
                        },
                        "additionalProperties": False,
                    },
                    "review": {
                        "type": "object",
                        "properties": {
                            "max_agent_turns_per_gate": {
                                "type": "integer",
                                "description": (
                                    "Maximum reviewer provider turns per review "
                                    "gate (initial_review, finding_verification, "
                                    "scope_review) before pausing with "
                                    "limit_exhausted when review respond was not "
                                    "persisted."
                                ),
                            },
                        },
                        "additionalProperties": False,
                    },
                    "provider": {
                        "type": "object",
                        "properties": {
                            "max_retries_per_call": {
                                "type": "integer",
                                "description": (
                                    "Transient Cursor CLI failures retried on the same "
                                    "argv before the turn fails. Does not apply to "
                                    "ProviderTurnStalledError, ProviderTurnCleanupError, "
                                    "or a turn that already observed a durable session id "
                                    "on the current attempt (including on a type:error "
                                    "event) or a result event."
                                ),
                            },
                            "turn_idle_timeout_seconds": {
                                "type": "number",
                                "default": 300,
                                "description": (
                                    "Seconds without Cursor stream-json stdout before "
                                    "the provider ends the turn. 0 disables idle timeout "
                                    "and is an explicit opt-out; the default is 300."
                                ),
                            },
                            "max_stream_json_record_bytes": {
                                "type": "integer",
                                "minimum": 1,
                                "default": 1048576,
                                "description": (
                                    "Maximum assembled Cursor stream-json line size "
                                    "(including the terminating newline) before the "
                                    "adapter fails the turn with provider_turn_failed. "
                                    "TDP default 1048576 (1 MiB). If the key is omitted "
                                    "from a raw CursorProvider config, or the value is "
                                    "invalid or non-positive, the adapter fallback is "
                                    "262144 (256 KiB). TDP configuration requires an "
                                    "integer >= 1."
                                ),
                            },
                        },
                        "additionalProperties": False,
                    },
                },
                "additionalProperties": False,
            },
            "execution": {
                "type": "object",
                "description": (
                    "Parent production strategy. Use tdp prepare and tdp execute "
                    "for Sub-TDP work; single is the only supported mode here. "
                    "Prepared parent/unit execution uses `tdp prepare` / `tdp execute` "
                    "packages (manifest.json), not this config leaf."
                ),
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["single"],
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
                    "additionalProperties": False,
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
                    "additionalProperties": False,
                },
            },
            "summary": {"type": "string"},
            "goal_assessment": {"type": "string"},
            "empty_output": {"type": "boolean"},
            "empty_output_reason": {
                "type": ["string", "null"],
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
        },
        "additionalProperties": False,
    },
    "review-respond": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ReviewRespondRequest",
        "description": (
            "Review findings and decision for `tdp agent review respond`. "
            "Each reported finding requires `severity` and `category` from "
            "the built-in taxonomy (see `tdp agent readme`, section Review "
            "finding categories). Mandatory whole_plan / whole_output loops "
            "require `stage`, audit attestation (see readme section Audit "
            "attestation), finding families with valid `rule_id` (see readme "
            "section Built-in finding-family rule_id values), and stage-native "
            "decisions per branch below. Focused reviews omit `stage` and use "
            "approved|changes_requested|blocked."
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
            "When family_fixes is present, target_revision and target_digest must "
            "match the current artifact revision and digest (same rule as review "
            "respond). Repeat record-actions at the current digest rebinds owner "
            "sweeps without duplicating existing owner fix actions. "
            "Owner/advisory packages expose an active-findings view: "
            "`new_findings`, `carried_open_findings`, `verification_targets`, "
            "`current_finding_actions`, `history_summary` (`total`, `closed`, "
            "`open`, optional `convergence_warning`), `history_ref` "
            "(structured pointer with kind/loop_id/finding_set_id — not a file path), "
            "and `review_budget` (`revision_cycles` and, for whole_* reviews, "
            "`scope_review_rounds` with consumed/max/remaining). "
            "Primary resume handoffs also include `tool_instructions.notes` with "
            "budget-aware owner guidance (prefer defer/accept_as_is for optional "
            "findings; use default_optional_action to bulk-close). "
            "Successful responses also include lifecycle_status, active_stage, and "
            "for mandatory whole_* loops mandatory_gate_pending plus "
            "next_required_actor (planner during advisory handoff, reviewer when "
            "scope_review approval is still required; status reflects finding "
            "disposition policy, not gate clearance). "
            "Persisted review loops may include `finding_ids_by_set` mapping each "
            "discovery finding_set_id to finding ids introduced in that set. "
            "Mandatory whole_* loops may also persist `pending_revision_cycle_entry` "
            "when a verification_revision limit pause blocked the next owner cycle "
            "before it was charged to `revision_cycles`."
        ),
        "type": "object",
        "required": ["loop_id", "target_revision", "target_digest", "finding_set_id"],
        "properties": {
            "loop_id": {"type": "string"},
            "target_revision": {"type": "integer"},
            "target_digest": {"type": "string", "minLength": 1},
            "finding_set_id": {"type": "string"},
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
                    "required": ["finding_id", "action", "actor_role"],
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
            "family_fixes": {
                "type": "array",
                "items": _FAMILY_FIX_SCHEMA,
                "description": (
                    "Family-level owner fix sweeps bound to target_revision and "
                    "target_digest. The service expands required open members into "
                    "finding_actions on the first sweep. When owner fix actions "
                    "already exist, a repeat call at the current target_digest "
                    "records a new owner sweep without duplicating fix actions "
                    "(sweep rebind after digest correction)."
                ),
            },
        },
        "additionalProperties": False,
    },
    "focused-review-request": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "FocusedReviewRequest",
        "description": (
            "Optional focused review request for `tdp agent review request`. "
            "Review kind is determined by type; scope lists item_ids only. "
            "Copy `target_revision` and `target_digest` from public snapshots: "
            "`plan_digest` on `tdp agent plan snapshot` for focused_plan, and "
            "`output_revision` plus `output_digest` on `tdp agent production snapshot` "
            "for focused_output."
        ),
        "oneOf": _FOCUSED_REVIEW_BRANCH_SCHEMAS,
    },
    "amendment-request": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "AmendmentRequest",
        "description": "Controlled plan amendment request for `tdp agent production request-amendment`.",
        "type": "object",
        "required": ["production_revision", "evidence", "affected_refs"],
        "properties": {
            "production_revision": {"type": "integer"},
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
        "required": ["production_revision", "goal_assessment"],
        "properties": {
            "production_revision": {"type": "integer"},
            "goal_assessment": {"type": "string", "minLength": 1},
            "summary": {"type": "string"},
        },
        "additionalProperties": False,
    },
    "blocker-report": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "BlockerReportRequest",
        "description": "Production blocker report for `tdp agent production report-blocked`. Use this for genuine terminal blockers (external outages, missing credentials), not as the normal wait for a pending focused review.",
        "type": "object",
        "required": ["production_revision", "evidence"],
        "properties": {
            "production_revision": {"type": "integer"},
            "evidence": {"type": "string", "minLength": 1},
            "affected_refs": {
                "type": "array",
                "items": {"type": "string"},
            },
            "summary": {"type": "string"},
            "kind": {
                "type": "string",
                "enum": ["external", "focused_review_wait"],
            },
            "review_loop_id": {"type": "string"},
            "package_item_id": {"type": "string"},
            "target_revision": {"type": "integer"},
            "target_digest": {"type": "string"},
        },
        "additionalProperties": False,
    },
    "agent-error": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "AgentErrorResponse",
        "type": "object",
        "required": ["ok", "error"],
        "properties": {
            "ok": {"const": False},
            "error": {
                "type": "object",
                "required": ["code", "message"],
                "properties": {
                    "code": {"type": "string"},
                    "message": {"type": "string"},
                    "action": {"type": "string"},
                    "hint": {"type": "string"},
                    "expected_revision": {"type": "integer"},
                    "actual_revision": {"type": "integer"},
                },
                "additionalProperties": True,
            },
        },
        "additionalProperties": False,
    },
    "plan-apply-response": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "PlanApplyResponse",
        "type": "object",
        "required": ["ok", "applied", "revision"],
        "properties": {
            "ok": {"type": "boolean"},
            "applied": {"type": "boolean"},
            "revision": {"type": "integer"},
            "id_map": {"type": "object"},
            "changed_item_ids": {"type": "array", "items": {"type": "string"}},
            "warnings": {"type": "array"},
            "issues": {"type": "array"},
            "ready_changes": {"type": "object"},
            "audit_degraded": {"type": "boolean"},
        },
        "additionalProperties": False,
    },
    "production-apply-response": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ProductionApplyResponse",
        "type": "object",
        "required": ["ok", "production_revision"],
        "properties": {
            "ok": {"type": "boolean"},
            "batch_id": {"type": "string"},
            "production_revision": {"type": "integer"},
            "output_revision": {"type": "integer"},
            "changed_disposition_count": {"type": "integer"},
            "changed_dispositions": {"type": "object"},
            "all_applicable_items_processed": {"type": "boolean"},
            "audit_degraded": {"type": "boolean"},
        },
        "additionalProperties": False,
    },
    "run-status-response": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "RunStatusResponse",
        "type": "object",
        "required": ["ok", "run"],
        "properties": {
            "ok": {"type": "boolean"},
            "run_path": {"type": "string"},
            "agent_requests_dir": {"type": "string"},
            "run": {
                "type": "object",
                "required": ["id", "revision"],
                "properties": {
                    "id": {"type": "string"},
                    "revision": {"type": "integer"},
                    "plan_revision": {"type": "integer"},
                    "status": {"type": "string"},
                    "phase": {"type": "string"},
                },
                "additionalProperties": True,
            },
        },
        "additionalProperties": True,
    },
    "focused-review-request-response": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "FocusedReviewRequestResponse",
        "type": "object",
        "required": ["ok", "loop_id", "type", "target_revision"],
        "properties": {
            "ok": {"type": "boolean"},
            "loop_id": {"type": "string"},
            "type": {"type": "string"},
            "scope": {"type": "object"},
            "target_revision": {"type": "integer"},
            "status": {"type": "string"},
            "audit_degraded": {"type": "boolean"},
        },
        "additionalProperties": False,
    },
    "plan-snapshot-response": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "PlanSnapshotResponse",
        "type": "object",
        "required": ["ok", "revision", "plan_digest"],
        "properties": {
            "ok": {"type": "boolean"},
            "revision": {"type": "integer"},
            "plan_digest": {"type": "string"},
            "view": {"type": "string"},
            "mode": {"type": "string"},
            "issues": {"type": "array"},
            "warnings": {"type": "array"},
        },
        "additionalProperties": True,
    },
    "plan-check-response": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "PlanCheckResponse",
        "type": "object",
        "required": ["ok", "revision", "mode"],
        "properties": {
            "ok": {"type": "boolean"},
            "revision": {"type": "integer"},
            "mode": {"type": "string"},
            "issues": {"type": "array"},
            "warnings": {"type": "array"},
            "plan_digest": {"type": "string"},
        },
        "additionalProperties": True,
    },
    "production-snapshot-response": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ProductionSnapshotResponse",
        "type": "object",
        "required": ["ok", "production_revision", "output_revision", "output_digest"],
        "properties": {
            "ok": {"type": "boolean"},
            "production_revision": {"type": "integer"},
            "output_revision": {"type": "integer"},
            "output_digest": {"type": "string"},
            "plan_digest": {"type": "string"},
            "batch_count": {"type": "integer"},
            "view": {"type": "string"},
            "issues": {"type": "array"},
            "warnings": {"type": "array"},
        },
        "additionalProperties": True,
    },
    "production-check-response": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ProductionCheckResponse",
        "type": "object",
        "required": ["ok", "production_revision", "output_revision"],
        "properties": {
            "ok": {"type": "boolean"},
            "revision": {"type": "integer"},
            "production_revision": {"type": "integer"},
            "output_revision": {"type": "integer"},
            "output_digest": {"type": "string"},
            "all_applicable_items_processed": {"type": "boolean"},
            "issues": {"type": "array"},
        },
        "additionalProperties": True,
    },
    "production-amendment-response": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ProductionAmendmentResponse",
        "type": "object",
        "required": ["ok", "amendment_id", "production_revision"],
        "properties": {
            "ok": {"type": "boolean"},
            "amendment_id": {"type": "string"},
            "status": {"type": "string"},
            "production_revision": {"type": "integer"},
            "signal": {"type": "string"},
            "audit_degraded": {"type": "boolean"},
        },
        "additionalProperties": False,
    },
    "production-completion-response": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ProductionCompletionResponse",
        "type": "object",
        "required": ["ok", "production_revision"],
        "properties": {
            "ok": {"type": "boolean"},
            "production_revision": {"type": "integer"},
            "completion_claim": {"type": "object"},
            "run_outcome": {},
            "audit_degraded": {"type": "boolean"},
        },
        "additionalProperties": False,
    },
    "production-blocker-response": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ProductionBlockerResponse",
        "type": "object",
        "required": ["ok", "production_revision"],
        "properties": {
            "ok": {"type": "boolean"},
            "production_revision": {"type": "integer"},
            "blocker_report": {"type": "object"},
            "run_outcome": {},
            "audit_degraded": {"type": "boolean"},
        },
        "additionalProperties": False,
    },
    "review-respond-response": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ReviewRespondResponse",
        "type": "object",
        "required": ["ok", "loop_id", "target_revision", "status"],
        "properties": {
            "ok": {"type": "boolean"},
            "loop_id": {"type": "string"},
            "decision": {},
            "target_revision": {"type": "integer"},
            "status": {"type": "string"},
            "findings": {"type": "array"},
            "stage": {"type": "string"},
            "derived_outcome": {"type": "string"},
            "audit_degraded": {"type": "boolean"},
            "revise_at": {"type": "string"},
            "finding_count": {"type": "integer"},
            "required_open_finding_count": {"type": "integer"},
            "optional_open_finding_count": {"type": "integer"},
            "required_open_finding_ids": {"type": "array", "items": {"type": "string"}},
            "optional_open_finding_ids": {"type": "array", "items": {"type": "string"}},
            "optional_finding_ids_missing_owner_response": {
                "type": "array",
                "items": {"type": "string"},
            },
            "optional_finding_ids_requiring_verification": {
                "type": "array",
                "items": {"type": "string"},
            },
            "family_count": {"type": "integer"},
            "required_open_family_count": {"type": "integer"},
            "required_open_family_ids": {"type": "array", "items": {"type": "string"}},
            "families_awaiting_owner_sweep": {"type": "array", "items": {"type": "string"}},
            "families_awaiting_verification": {
                "type": "array",
                "items": {"type": "string"},
            },
            "regressed_family_count": {"type": "integer"},
            "audit_passes_completed": {},
            "audit_passes_required": {"type": "integer"},
        },
        "additionalProperties": False,
    },
    "review-record-finding-actions-response": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ReviewRecordFindingActionsResponse",
        "type": "object",
        "required": ["ok", "loop_id", "status"],
        "properties": {
            "ok": {"type": "boolean"},
            "loop_id": {"type": "string"},
            "status": {"type": "string"},
            "recorded_actions": {"type": "array"},
            "audit_degraded": {"type": "boolean"},
            "revise_at": {"type": "string"},
            "finding_count": {"type": "integer"},
            "required_open_finding_count": {"type": "integer"},
            "optional_open_finding_count": {"type": "integer"},
            "required_open_finding_ids": {"type": "array", "items": {"type": "string"}},
            "optional_open_finding_ids": {"type": "array", "items": {"type": "string"}},
            "optional_finding_ids_missing_owner_response": {
                "type": "array",
                "items": {"type": "string"},
            },
            "optional_finding_ids_requiring_verification": {
                "type": "array",
                "items": {"type": "string"},
            },
            "lifecycle_status": {},
            "active_stage": {},
            "mandatory_gate_pending": {"type": "boolean"},
            "next_required_actor": {"type": "string"},
        },
        "additionalProperties": False,
    },
}

_SCHEMAS = SCHEMAS


def _example_rubric_ids(review_type: str) -> list[str]:
    rubric = DEFAULT_CONFIG["review"][review_type]["rubric"]
    return [
        item["id"]
        for item in rubric_items_with_ids([str(entry) for entry in rubric])
    ]


def _example_whole_plan_audit_passes() -> list[dict[str, Any]]:
    rubric_ids = _example_rubric_ids("whole_plan")
    return [
        {
            "pass_id": pass_id,
            "completed": True,
            "search_dimensions": ["acceptance"],
            "inspected_refs": ["active-items:*"],
            "rubric_item_ids": rubric_ids,
            "summary": f"Completed {pass_id}.",
        }
        for pass_id in WHOLE_PLAN_AUDIT_PASS_IDS
    ]


def _example_whole_output_audit_passes() -> list[dict[str, Any]]:
    rubric_ids = _example_rubric_ids("whole_output")
    return [
        {
            "pass_id": pass_id,
            "completed": True,
            "search_dimensions": ["evidence"],
            "inspected_refs": ["production:*"],
            "rubric_item_ids": rubric_ids,
            "summary": f"Completed {pass_id}.",
        }
        for pass_id in WHOLE_OUTPUT_AUDIT_PASS_IDS
    ]


_EXAMPLES: dict[str, dict[str, Any]] = {
    "expand-branch": {
        "schema": "plan-transaction",
        "description": (
            "Set plan-level contract, populate the seeded root, and expand a branch. "
            "UI depends on API via inline add_item.item.depends_on with temp_id "
            "resolution in the same transaction."
        ),
        "payload": {
            "base_revision": 0,
            "operations": [
                {
                    "op": "update_plan",
                    "patch": {
                        "scope": {
                            "includes": ["src/api/", "src/ui/"],
                            "excludes": [],
                        },
                        "acceptance": ["API and UI layers are testable end to end."],
                    },
                },
                {
                    "op": "update_item",
                    "item_id": "item-root",
                    "patch": {
                        "title": "Deliver API and UI layers",
                        "outcome": "HTTP API and consuming UI exist with documented contracts.",
                    },
                },
                {
                    "op": "add_item",
                    "temp_id": "item-api",
                    "parent_id": "item-root",
                    "placement": {"last_child": True},
                    "item": {
                        "kind": "work",
                        "title": "API layer",
                        "outcome": "HTTP API exists with documented endpoints.",
                        "acceptance": [
                            "Endpoints are testable from a clean checkout."
                        ],
                        "risks": [
                            "Route registration order may shadow existing handlers."
                        ],
                        "source_refs": ["spec.md → API endpoints"],
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
                        "depends_on": ["item-api"],
                    },
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
    "review-respond-focused-with-instance-ref": {
        "schema": "review-respond",
        "description": (
            "Focused plan discovery with optional structured instance_ref "
            "(item_id must stay within scope.item_ids)."
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
                    "instance_ref": {
                        "kind": "plan_item_field",
                        "item_id": "item-api",
                        "field": "acceptance",
                        "value_digest": "abc123",
                    },
                    "issue": "Acceptance criteria are not testable.",
                    "recommended_change": "Add concrete acceptance checks.",
                    "status": "unresolved",
                }
            ],
            "review_completed": True,
            "summary": "Structured instance ref within scope.",
        },
    },
    "review-respond-family-discovery-focused-plan": {
        "schema": "review-respond",
        "description": (
            "Optional focused_plan family discovery (no audit attestation; "
            "no scope_review stage). rule_id from tdp agent readme built-ins "
            "or custom.<slug> with rule_definition."
        ),
        "payload": {
            "loop_id": "review-focused-plan-01",
            "target_revision": 0,
            "finding_set_id": "review-focused-plan-01-fs-01",
            "target_digest": "<plan-digest>",
            "finding_families": [
                {
                    "id": "family-001",
                    "rule_id": "dependency.acceptance_capability_available",
                    "subject_key": "item-api acceptance",
                    "scope_kind": "focused-plan",
                    "title": "Acceptance gaps on API item",
                    "seed_finding_id": "finding-001",
                    "confirmed_finding_ids": ["finding-001"],
                    "candidate_refs": [],
                    "recommended_change": "Add measurable acceptance checks.",
                    "discovery_sweep": {
                        "searched_refs": ["active-items:*"],
                        "search_dimensions": ["acceptance"],
                        "completed": True,
                        "summary": "Scoped sweep complete.",
                    },
                }
            ],
            "reported_findings": [
                {
                    "id": "finding-001",
                    "family_id": "family-001",
                    "instance_ref": {
                        "kind": "plan_item_field",
                        "item_id": "item-api",
                        "field": "acceptance",
                        "value_digest": "abc123",
                    },
                    "severity": "blocker",
                    "category": "acceptance",
                    "target_refs": ["item-api"],
                    "issue": "Acceptance criteria are not testable.",
                    "recommended_change": "Add concrete acceptance checks.",
                    "status": "unresolved",
                }
            ],
            "review_completed": True,
            "summary": "One family in focused plan scope.",
        },
    },
    "review-respond-family-discovery-focused-output": {
        "schema": "review-respond",
        "description": (
            "Optional focused_output family discovery within scope.item_ids. "
            "rule_id from tdp agent readme built-ins or custom.<slug> with "
            "rule_definition."
        ),
        "payload": {
            "loop_id": "review-focused-output-01",
            "target_revision": 1,
            "finding_set_id": "review-focused-output-01-fs-01",
            "target_digest": "<output-digest>",
            "finding_families": [
                {
                    "id": "family-001",
                    "rule_id": "custom.evidence-gap",
                    "subject_key": "item-api evidence",
                    "scope_kind": "focused-output",
                    "title": "Missing evidence on scoped item",
                    "seed_finding_id": "finding-001",
                    "confirmed_finding_ids": ["finding-001"],
                    "candidate_refs": [],
                    "recommended_change": "Attach evidence for item-api.",
                    "discovery_sweep": {
                        "searched_refs": ["production:*"],
                        "search_dimensions": ["evidence"],
                        "completed": True,
                        "summary": "Scoped output sweep complete.",
                    },
                }
            ],
            "reported_findings": [
                {
                    "id": "finding-001",
                    "family_id": "family-001",
                    "instance_ref": {
                        "kind": "output_record",
                        "record_kind": "disposition",
                        "record_key": "item-api",
                    },
                    "severity": "major",
                    "category": "correctness",
                    "target_refs": ["item-api"],
                    "issue": "Terminal disposition lacks supporting evidence.",
                    "recommended_change": "Attach new evidence for item-api.",
                    "status": "unresolved",
                }
            ],
            "review_completed": True,
            "summary": "One family in focused output scope.",
        },
    },
    "review-respond-verification": {
        "schema": "review-respond",
        "description": (
            "Focused finding_verification (focused_plan / focused_output). "
            "Mandatory whole_plan and whole_output use "
            "review-respond-family-verification."
        ),
        "payload": {
            "loop_id": "review-focused-output-01",
            "target_revision": 1,
            "stage": "finding_verification",
            "target_digest": "<output-digest>",
            "finding_set_id": "review-focused-output-01-fs-01",
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
            "Mandatory whole_plan or whole_output contract v2 fresh scope_review: "
            "clear approved outcome with audit attestation and finding families "
            "(empty when clear). " + _MANDATORY_FAMILY_ADAPTATION
        ),
        "payload": {
            "loop_id": "review-whole-plan-01",
            "target_revision": 1,
            "stage": "scope_review",
            "finding_set_id": "review-whole-plan-01-fs-02",
            "target_digest": "<plan-digest>",
            "reported_findings": [],
            "finding_families": [],
            "audit_attestation": {
                "passes": _example_whole_plan_audit_passes(),
            },
            "review_completed": True,
            "summary": "No remaining material issues in current scope.",
        },
    },
    "review-respond-family-discovery": {
        "schema": "review-respond",
        "description": (
            "Mandatory whole_plan discovery with audit attestation and finding "
            "families (see review-respond-family-discovery-output for whole_output). "
            + _MANDATORY_FAMILY_ADAPTATION
        ),
        "payload": {
            "loop_id": "review-whole-plan-01",
            "target_revision": 1,
            "stage": "initial_review",
            "finding_set_id": "review-whole-plan-01-fs-01",
            "review_completed": True,
            "summary": "Reported dependency capability family.",
            "target_digest": "<plan-digest>",
            "audit_attestation": {
                "passes": _example_whole_plan_audit_passes(),
            },
            "finding_families": [
                {
                    "id": "family-dependency-capability-reset",
                    "rule_id": "dependency.acceptance_capability_available",
                    "subject_key": "reset-control",
                    "scope_kind": "active-plan",
                    "title": "Acceptance references unavailable capability",
                    "seed_finding_id": "sf-001",
                    "confirmed_finding_ids": ["sf-001"],
                    "candidate_refs": [],
                    "recommended_change": "Move concrete integration to the owning leaf.",
                    "discovery_sweep": {
                        "searched_refs": ["active-items:*"],
                        "search_dimensions": ["acceptance", "depends_on"],
                        "completed": True,
                        "summary": "Searched active plan for equivalent references.",
                        "evidence": [],
                    },
                }
            ],
            "reported_findings": [
                {
                    "id": "sf-001",
                    "family_id": "family-dependency-capability-reset",
                    "instance_ref": {
                        "kind": "plan_item_field",
                        "item_id": "item-write",
                        "field": "acceptance",
                        "value_digest": "<opaque>",
                        "duplicate_ordinal": 0,
                    },
                    "severity": "major",
                    "category": "architecture",
                    "target_refs": ["item-write"],
                    "issue": "Acceptance tests Reset before Reset exists.",
                    "recommended_change": "Test only the reserved shell action slot.",
                }
            ],
        },
    },
    "review-respond-family-discovery-output": {
        "schema": "review-respond",
        "description": (
            "Mandatory whole_output discovery with audit attestation and finding "
            "families. Shows custom rule_id pattern (custom.evidence-gap). "
            + _MANDATORY_FAMILY_ADAPTATION
        ),
        "payload": {
            "loop_id": "review-whole-output-01",
            "target_revision": 1,
            "stage": "initial_review",
            "finding_set_id": "review-whole-output-01-fs-01",
            "review_completed": True,
            "summary": "Reported output evidence gap family.",
            "target_digest": "<output-digest>",
            "audit_attestation": {
                "passes": _example_whole_output_audit_passes(),
            },
            "finding_families": [
                {
                    "id": "family-evidence-gap-leaf",
                    "rule_id": "custom.evidence-gap",
                    "rule_definition": "output evidence completeness gap",
                    "subject_key": "item-leaf",
                    "scope_kind": "whole-output",
                    "title": "Missing output evidence for leaf item",
                    "seed_finding_id": "sf-001",
                    "confirmed_finding_ids": ["sf-001"],
                    "candidate_refs": [],
                    "recommended_change": "Attach artifact evidence for item-leaf.",
                    "discovery_sweep": {
                        "searched_refs": ["production:*"],
                        "search_dimensions": ["evidence"],
                        "completed": True,
                        "summary": "Searched production for evidence gaps.",
                        "evidence": [],
                    },
                }
            ],
            "reported_findings": [
                {
                    "id": "sf-001",
                    "family_id": "family-evidence-gap-leaf",
                    "instance_ref": {
                        "kind": "output_record",
                        "record_kind": "evidence",
                        "record_key": "evidence-01",
                        "field": "summary",
                        "value_digest": "<opaque>",
                    },
                    "severity": "blocker",
                    "category": "correctness",
                    "target_refs": ["item-leaf"],
                    "issue": "Output evidence is missing for item-leaf.",
                    "recommended_change": "Attach artifact evidence for item-leaf.",
                }
            ],
        },
    },
    "review-respond-family-verification": {
        "schema": "review-respond",
        "description": (
            "Mandatory whole_plan finding_verification with family_results and "
            "verified decision (see review-respond-family-verification-output for "
            "whole_output). Adapt target_digest and loop ids from the review package."
        ),
        "payload": {
            "loop_id": "review-whole-plan-01",
            "target_revision": 2,
            "stage": "finding_verification",
            "target_digest": "<plan-digest>",
            "finding_set_id": "review-whole-plan-01-fs-01",
            "decision": "verified",
            "finding_results": [
                {
                    "finding_id": "sf-001",
                    "disposition": "resolved",
                    "evidence": ["Normalized Reset references"],
                    "direct_side_effects": [],
                }
            ],
            "family_results": [
                {
                    "family_id": "family-dependency-capability-reset",
                    "disposition": "closed",
                    "verification_sweep": {
                        "searched_refs": ["active-items:*"],
                        "search_dimensions": ["acceptance", "depends_on"],
                        "remaining_instance_refs": [],
                        "completed": True,
                        "summary": "No equivalent active instance remains.",
                        "evidence": [],
                    },
                    "remaining_instance_findings": [],
                }
            ],
            "new_direct_side_effect_findings": [],
            "summary": "Families verified; no remaining instances.",
        },
    },
    "review-respond-family-verification-output": {
        "schema": "review-respond",
        "description": (
            "Mandatory whole_output finding_verification with family_results and "
            "verified decision. Adapt target_digest and loop ids from the review "
            "package."
        ),
        "payload": {
            "loop_id": "review-whole-output-01",
            "target_revision": 2,
            "stage": "finding_verification",
            "target_digest": "<output-digest>",
            "finding_set_id": "review-whole-output-01-fs-01",
            "decision": "verified",
            "finding_results": [
                {
                    "finding_id": "sf-001",
                    "disposition": "resolved",
                    "evidence": ["Artifact evidence attached"],
                    "direct_side_effects": [],
                }
            ],
            "family_results": [
                {
                    "family_id": "family-evidence-gap-leaf",
                    "disposition": "closed",
                    "verification_sweep": {
                        "searched_refs": ["production:*"],
                        "search_dimensions": ["evidence"],
                        "remaining_instance_refs": [],
                        "completed": True,
                        "summary": "No remaining evidence gaps.",
                        "evidence": [],
                    },
                    "remaining_instance_findings": [],
                }
            ],
            "new_direct_side_effect_findings": [],
            "summary": "Output families verified; no remaining instances.",
        },
    },
    "review-record-family-fix": {
        "schema": "review-record-finding-actions",
        "description": (
            "Whole-plan owner family fix sweep with generated fix actions for "
            "required members on the first sweep. Repeat at the current "
            "target_digest to rebind an owner sweep without duplicating fix "
            "actions (see review-record-family-fix-output for producer)."
        ),
        "payload": {
            "loop_id": "review-whole-plan-01",
            "target_revision": 2,
            "target_digest": "<plan-digest>",
            "finding_set_id": "review-whole-plan-01-fs-02",
            "family_fixes": [
                {
                    "family_id": "family-reset",
                    "target_finding_ids": [],
                    "rationale": "Normalized all instances",
                    "changed_refs": ["item-a", "item-b"],
                    "owner_sweep": {
                        "searched_refs": ["active-items:*"],
                        "search_dimensions": ["acceptance"],
                        "additional_fixed_refs": [],
                        "remaining_instance_refs": [],
                        "completed": True,
                        "summary": "No remaining instances",
                    },
                }
            ],
            "finding_actions": [],
        },
    },
    "review-record-family-fix-output": {
        "schema": "review-record-finding-actions",
        "description": (
            "Whole-output producer family fix sweep after evidence revision. "
            "First call generates fix actions for required members. Repeat at "
            "the current target_digest to rebind an owner sweep without "
            "duplicating fix actions."
        ),
        "payload": {
            "loop_id": "review-whole-output-01",
            "target_revision": 2,
            "target_digest": "<output-digest>",
            "finding_set_id": "review-whole-output-01-fs-02",
            "family_fixes": [
                {
                    "family_id": "family-evidence-gap-leaf",
                    "target_finding_ids": [],
                    "rationale": "Attached missing artifact evidence",
                    "changed_refs": ["item-leaf"],
                    "owner_sweep": {
                        "searched_refs": ["production:*"],
                        "search_dimensions": ["evidence"],
                        "additional_fixed_refs": [],
                        "remaining_instance_refs": [],
                        "completed": True,
                        "summary": "No remaining evidence gaps",
                    },
                }
            ],
            "finding_actions": [],
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
            "target_revision": 0,
            "target_digest": "<plan-digest>",
            "finding_set_id": "review-focused-plan-01-fs-01",
            "default_optional_action": "accept_as_is",
            "finding_actions": [
                {
                    "finding_id": "finding-opt-01",
                    "action": "challenge",
                    "challenge_reason": "conflicts_with_contract",
                    "proposed_disposition": "invalid",
                    "actor_role": "planner",
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
                "item_ids": ["item-api"],
            },
            "target_revision": 0,
            "target_digest": "plan-digest-placeholder",
        },
    },
    "amendment-request": {
        "schema": "amendment-request",
        "description": "Producer requests a controlled plan amendment during production.",
        "payload": {
            "production_revision": 0,
            "evidence": "Plan item item-api omits a dependency required for batch sequencing.",
            "affected_refs": ["item-api", "item-ui"],
            "summary": "Add missing dependency before production can continue.",
        },
    },
    "completion-claim": {
        "schema": "completion-claim",
        "description": "Producer submits a completion claim after all applicable items are terminal.",
        "payload": {
            "production_revision": 0,
            "goal_assessment": "Every applicable plan item has a terminal disposition or derived satisfaction.",
            "summary": "Production batches complete; ready for whole-output review.",
        },
    },
    "blocker-report": {
        "schema": "blocker-report",
        "description": "Producer reports a blocker with evidence when production cannot continue.",
        "payload": {
            "production_revision": 0,
            "evidence": "Upstream credential rotation blocks deployment verification.",
            "affected_refs": ["item-deploy"],
            "summary": "Deployment verification cannot proceed until credentials are restored.",
        },
    },
}

AGENT_HELP_TEXT = """Top Down Planning agent CLI (tdp agent)

Start here:
  1. tdp agent readme
  2. tdp agent schema <name>  /  tdp agent example <name>
  3. Packaged role skills are auto-injected into agent_context.skills (agent_context.bundled_skills, default true)
     Agent hub: tools/top_down_planning/docs/README.md

Discover contracts without reading source:
  tdp agent help
  tdp agent readme
  tdp agent schema [<name>]   # omit name to list published schemas
  tdp agent example [<name>]  # omit name to list published examples

Plan:
  tdp agent plan snapshot --run <run-id> [--view active|audit|ready|issues|budget]
  tdp agent plan apply --run <run-id> --request $TDP_AGENT_REQUESTS_DIR/plan-apply-r<rev>-a01.json
  tdp agent plan check --run <run-id> [--mode draft|approval]

Production:
  tdp agent production snapshot --run <run-id> [--view tree|ready|dispositions]
  tdp agent production apply --run <run-id> --request $TDP_AGENT_REQUESTS_DIR/production-apply-batch-01-a01.json
  tdp agent production check --run <run-id>
  tdp agent production request-amendment --run <run-id> --request $TDP_AGENT_REQUESTS_DIR/production-amendment-a01.json
  tdp agent production submit-completion --run <run-id> --request $TDP_AGENT_REQUESTS_DIR/production-completion-a01.json
  tdp agent production report-blocked --run <run-id> --request $TDP_AGENT_REQUESTS_DIR/production-blocked-a01.json

Review:
  tdp agent review request --run <run-id> --request $TDP_AGENT_REQUESTS_DIR/review-request-<scope>-a01.json
  tdp agent review respond --run <run-id> --request $TDP_AGENT_REQUESTS_DIR/review-respond-<stage>-r<rev>-a01.json
  Finding categories: review_policy.category_definitions in reviewer packages;
  tdp agent readme (Review finding categories); tdp agent schema review-respond
  Mandatory reviewers: rubric_items and required_audit_passes in the review
  package; built-in rule_id list in tdp agent readme (Built-in finding-family
  rule_id values)

Whole-plan and focused_plan reviewers receive an embedded plan snapshot in the
review package; call `tdp agent plan snapshot --run <run-id> --view active` to
refresh before responding when the plan may have changed.

Run status:
  tdp agent run status --run <run-id>

Run store: agent commands use --runs-dir, $TDP_RUNS_DIR, or ./runs. Run ids use
run-YYYYMMDDTHHMMSS-<6hex> (UTC creation time plus random suffix). Provider
subprocesses receive TDP_RUNS_DIR, TDP_RUN_ID, TDP_AGENT_REQUESTS_DIR, and a
session-scoped TDP_CAPABILITY_TOKEN_FILE before turns that may call mutating commands.
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

AGENT_README_PREFIX = """# Top Down Planning — agent protocol

`tdp` orchestrates planning and production. Agents interact only through `tdp agent`
shell commands; those commands persist mutations to the run store. The orchestrator
observes store changes after each provider turn, runs pending review loops, and
advances phases when agents emit explicit completion signals (`candidate_plan_ready`,
`amendment_revision_ready`, etc.) as the final assistant line or `done.signal`
metadata. Producer batch turns close when `production apply` persists a batch;
completion turns close when `submit-completion` persists a valid completion claim;
requesting focused output review also closes the current producer turn so the
focused reviewer can run before the producer resumes. Do not call
`production report-blocked` merely because that review is pending. In those cases
the orchestrator aborts the in-flight provider turn, waits for the
session collector to settle, then queues the next turn on the same session.
Reviewer
turns close when `review respond` persists a decision: the orchestrator aborts
the in-flight provider turn, waits for the session collector to settle, then
releases the bounded reviewer session before owner revision or the next gate. Owner
advisory turns close when `review record-actions` persists. A
turn that ends without `review respond` queues another reviewer turn with a nudge
(bounded by `limits.review.max_agent_turns_per_gate`) before pausing with
`limit_exhausted`. A background poll watches for persisted batches, completion
claims, focused-review requests, owner record-actions, or review decisions while the
turn is open so a stalled agent subprocess cannot block progress after apply,
submit-completion, review request, record-actions, or respond.

## Session roles and authorization

The orchestrator binds one primary planner, producer, or reviewer session per phase.
Mutating `tdp agent` commands read the session capability token from
`TDP_CAPABILITY_TOKEN_FILE` on the provider subprocess that runs the turn. Reviewer
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
`TDP_CAPABILITY_TOKEN_FILE`. When capability context is active, `TDP_RUN_ID` must match
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
- `protocol_instructions` — rendered Markdown string from package-owned Jinja
  templates under `top_down_planning/prompts/templates/`; role behavior rules
  surfaced at the top of the provider prompt (for example: mutate run state only
  through `tdp agent` commands; do not use host planning modes or planning-only
  artifacts). Stage-specific reviewer guidance in review packages defers to
  `protocol_instructions`; dimensional checklists such as `scope_review_guidance`
  are search dimensions, not a second behavioral contract.
- `tool_instructions` — concrete `tdp agent` command templates for the active role
- `agent_context` — supporting `guidance`, `resources`, and `skills`
  (packaged TDP agent skills are auto-injected when agent_context.bundled_skills
  is true; configured skills inherit `agent_context.default`; duplicate resource
  paths between default and role are deduped; do not repeat `run.input_refs` or
  the output-goal file under `resources`). Guidance is advisory and not merged into
  `protocol_instructions`.
- Producer packages include `approved_plan` (plan metadata plus canonical item
  contracts from `build_item_production_contract`)
- Review packages include `plan_scope`, `boundaries`, `acceptance`, and `risks` from persisted
  plan metadata (not static run config), plus `review_policy` with
  `severity_definitions` and `category_definitions` for classifying findings.
  Mandatory whole_plan and whole_output packages also include `rubric_items`,
  `required_audit_passes`, and `analysis_context` for discovery attestation.
  Use `tdp agent readme` (sections Audit attestation and Built-in finding-family
  rule_id values) and stage examples — not TDP Python source — to shape
  `review respond` payloads.

The provider adapter formats these payloads for the agent. Follow
`protocol_instructions` and `tool_instructions`; host IDE planning artifacts are
not consumed by the orchestrator.

## Plan field semantics

Required resulting truth → `acceptance`. Material uncertainty or failure mode →
`risks` (plan-level for cross-cutting threats; item-level for owned outcomes).
Believed premise → `assumptions`. Mandatory solution condition → `constraints`.
Operational guardrail → `boundaries`. Owned work → `scope` (`includes` /
`excludes`). Execution prerequisite → `depends_on`. Requirement origin →
`source_refs` on items (plan-level inputs stay in `input_refs`). Non-binding
advice stays in guidance, resources, skills, or authoritative inputs — not plan
fields.

Do not place architecture suggestions in `acceptance`. Do not place source-document
section names in `scope.includes` — use item-level `source_refs` for requirement
traceability when needed. Do not convert every possible defect into a risk. Attach
each risk to the lowest item that owns it; avoid duplicating the same risk
at plan and item level.

Every active `work` leaf must set item-level `scope.includes`, `scope.excludes`,
and/or `boundaries` (plan-level fields do not satisfy this). Draft validation
warns (`missing_work_item_scope_contract`); approval mode errors.

Production item contracts (`ready_items`, `approved_plan.items`, output-review
`plan_contracts`) share one canonical shape from `build_item_production_contract`:
item-owned `scope`/`boundaries`, merged `effective_scope`/`effective_boundaries`
(plan-level ∪ item-level, deduped), plus acceptance, risks, source_refs, and
depends_on. Producers enforce batch boundaries from `effective_*`; approved work
leaves must already declare item-level scope or boundaries.

"""


def _finding_category_readme_section() -> str:
    lines = [
        "## Review finding categories",
        "",
        "Discovery findings require `severity` and `category`. Reviewer packages "
        "expose `review_policy.severity_definitions` and "
        "`review_policy.category_definitions` (same enum as "
        "`tdp agent schema review-respond`).",
        "",
        "The configured review `rubric` names inspection themes (dependencies, "
        "coverage, risk ownership, root contract). Rubric themes are not finding "
        "categories — classify each issue with the nearest category below:",
        "",
    ]
    for category in FINDING_CATEGORY_ORDER:
        lines.append(f"- **{category}** — {CATEGORY_DEFINITIONS[category]}")
    lines.append("")
    return "\n".join(lines)


def _finding_family_readme_section() -> str:
    return """## Finding families (mandatory whole-plan and whole-output contract v2)

Mandatory `whole_plan` and `whole_output` loops with `review_contract_version` 2
group related defects into **finding families**. Optional `focused_plan` and
`focused_output` loops may also submit `finding_families` when multiple related
defects appear within `scope.item_ids` (no audit attestation or scope_review).
A family is one repair unit; each **finding** is one confirmed instance with a
structured `instance_ref`.

- **Confirmed instance** — reported in `reported_findings` and listed in the
  family's `confirmed_finding_ids`.
- **Candidate instance** — uncertain match kept in `candidate_refs`; does not
  affect derived severity until promoted to a finding.
- **Owner blast-radius sweep** — after revising the artifact, the planner or
  producer records one `family_fix` with `owner_sweep.completed: true` and empty
  `remaining_instance_refs`. Required open members are included automatically;
  list optional members in `target_finding_ids`. Bind `target_revision` and
  `target_digest` to the current artifact snapshot; `record-actions` rejects a
  stale `target_digest`. After the artifact revision advances, call
  `record-actions` again at the new revision and digest to rebind owner sweeps
  without duplicating existing owner fix actions.
- **Family closure** — a policy-relevant family is `closed` only after owner
  sweep (when required) and reviewer `verification_sweep` when verification
  members remain. Fixing only the seed finding does not close the family.
- **Scope-review regression** — do not submit `reopens_family_id` or
  `reopens_finding_id`; the service links regressions from fingerprint and
  `instance_ref` match after a fresh scope review.
- **`rule_id`** — each family requires a built-in id or `custom.<slug>` with
  `rule_definition` (see readme section Built-in finding-family rule_id values).
- **Audit attestation** — mandatory discovery also requires attestation bound to
  `rubric_items` and `required_audit_passes` from the review package (see readme
  section Audit attestation).

Whole-plan examples: `review-respond-family-discovery`,
`review-respond-family-verification`, `review-record-family-fix`,
`review-respond-scope`.

Whole-output examples: `review-respond-family-discovery-output`,
`review-respond-family-verification-output`, `review-record-family-fix-output`,
`review-respond-scope`.

Focused examples: `review-respond`, `review-respond-focused-with-instance-ref`,
`review-respond-family-discovery-focused-plan`,
`review-respond-family-discovery-focused-output`, `review-respond-verification`.

Record schema version 2 carries persisted family state; contract version 2
governs mandatory discovery and verification payloads.

"""


def _audit_attestation_readme_section() -> str:
    return """## Audit attestation (mandatory whole_plan and whole_output discovery)

On `initial_review` and `scope_review` with `review_completed: true`, contract v2
payloads require `audit_attestation`:

- **`passes[].pass_id`** — must include every id from the delivered review package
  `required_audit_passes` at the package root.
- **`passes[].rubric_item_ids`** — union across all passes must equal the set of
  every `id` from the delivered `rubric_items` (no missing or extra ids). Do not
  copy rubric ids from static `tdp agent example` payloads; they reflect default
  config only.

Workflow: read the delivered review package → `tdp agent example
review-respond-family-discovery` (or `-output`) for **structure** → substitute
`loop_id`, `finding_set_id`, `target_digest`, and all `rubric_item_ids` from the
package before `tdp agent review respond`.

"""


def _builtin_rule_readme_section() -> str:
    lines = [
        "## Built-in finding-family rule_id values",
        "",
        "Each `finding_families[]` entry requires a valid `rule_id`. Use a built-in "
        "id below or `custom.<slug>` (lowercase slug, hyphens) with `rule_definition`. "
        "Built-in rules must **not** include `rule_definition`. Custom rules **require** "
        "`rule_definition`.",
        "",
        "Built-in ids (same enum as runtime validation):",
        "",
    ]
    for rule_id in sorted(BUILTIN_RULE_DESCRIPTIONS):
        lines.append(f"- **{rule_id}** — {BUILTIN_RULE_DESCRIPTIONS[rule_id]}")
    lines.extend(
        [
            "",
            "Examples: built-in `dependency.acceptance_capability_available` in "
            "`review-respond-family-discovery`; custom `custom.evidence-gap` with "
            "`rule_definition` in `review-respond-family-discovery-output`.",
            "",
        ]
    )
    return "\n".join(lines)


_AGENT_README_PLAN_DEPENDENCIES = """## Plan apply: dependencies

For new items in the same `operations` batch, set execution prerequisites **inline**
on `add_item.item.depends_on`:

- Values may be **stable item ids** or **temp_id** strings from other `add_item`
  ops in the same batch.
- Accepts a **string** (`"item-api"`) or **array** (`["item-api"]`).
- Operation order within the batch does not need to list dependencies before
  dependents; temp ids are pre-registered for the transaction.
- Each `temp_id` must be **unique** within one `plan apply` batch.

Example: `tdp agent example expand-branch` (UI item depends on API via inline
`depends_on`). Packaged planner skill content is in `agent_context.skills` on the
session manifest.

To change dependencies on **existing** items, use `add_dependency`,
`remove_dependency`, or `replace_dependencies`. `update_item` patch cannot change
`depends_on`.

"""

_AGENT_README_WORKFLOW_AND_BEYOND = """## Workflow

1. Planner expands the plan with `plan apply` until `candidate_plan_ready`.
   Each `add_item` requires `kind`: `work` for batchable leaves, `aggregate` for
   grouping-only parents. The seeded root is `aggregate` (`item-root`, title
   `Root`). Before adding children under `item-root`, use `update_item` on
   `item-root` to set a meaningful title and outcome; use `update_plan` to
   revise plan-level `scope`, `boundaries`, `constraints`, `assumptions`,
   `acceptance`, and `risks` (seeded from `run.boundaries` / `run.acceptance` at run creation).
   Item-level `risks` and `source_refs` use `add_item` / `update_item`.
   For dependencies between new items in the same batch, set `depends_on` inline on
   `add_item` (see Plan apply: dependencies above and `expand-branch`).
   Every `work` leaf must also set item-level `scope.includes`, `scope.excludes`,
   and/or `boundaries` (approval mode errors when all three are empty).
   Once `item-root` has active children, deterministic validation requires a
   non-default title and non-empty outcome on `item-root`.
2. Mandatory whole-plan review (`review respond`) must complete the gate before production.
   Stages: `initial_review` (discovery), optional `finding_verification` (close known
   findings after revisions), then fresh `scope_review` (complete-scope discovery).
   Contract v2 payloads require `audit_attestation`, `finding_families`, and
   `target_digest` on discovery stages — see `review-respond-family-discovery`,
   `review-respond-family-verification`, and `review-respond-scope`, plus readme
   sections Audit attestation and Built-in finding-family rule_id values.
   Review packages include an embedded plan tree, `review_policy.category_definitions`,
   `rubric_items` and `required_audit_passes` on every stage, and optional configured
   rubric themes on initial review; adapt example payloads using package ids
   (do not copy rubric ids from static examples). Refresh with
   `plan snapshot --view active` when revising after
   `needs_revision` or initial `changes_requested`. Reviewers prioritize plan
   correctness and internal consistency. Approval requires a clear
   fresh `scope_review` against the current artifact digest — finding closure alone is not
   enough.
3. Producer records batches with `production apply` (service assigns `batch_id`), then
   `submit-completion` with a non-empty `goal_assessment`. The command implies the goal
   is met; do not send `goal_met` in the request. Batch turns close when apply
   persists; the completion turn closes when the claim persists. Production `ready`
   snapshots expose `ready_items` and compact `disposition_summary` counts; use
   `--view dispositions` for the full map.
4. Mandatory whole-output review must complete the gate before `outcome: accepted`.
   Same mandatory contract-v2 gate as whole-plan review (`initial_review`, then
   repeatable verification and fresh `scope_review` rounds). Review packages include
   production traceability, `review_policy.category_definitions`, stable
   `rubric_items` and `required_audit_passes` on every stage, and reviewer guidance
   that prioritizes output correctness and cross-artifact consistency. Use
   `tdp agent readme` (Audit attestation; Built-in finding-family rule_id values)
   and stage examples for `review respond` payloads — not TDP source. Use
   `review-respond-family-discovery-output`, `review-respond-family-verification-output`,
   and `review-record-family-fix-output` for whole-output payloads. After
   `needs_revision` or initial `changes_requested`, the producer must use
   `production apply` with `evidence_revision: true` and **new** output evidence IDs
   on terminal items targeted by unresolved required findings (dispositions unchanged),
   record owner `family_fix` sweeps via `tdp agent review record-actions`, then
   re-submit completion with `goal_assessment` only (the owner revision turn closes
   when that completion claim persists). During production, focused-output
   evidence revision also requires `focused_review_loop_id` bound to the loop's
   `target_revision`. Plan amendment is not available during whole-output review.
5. Optional focused reviews use `review request` with bounded `scope.item_ids`.
   A focused-output request closes the current producer turn; end the turn after
   the request persists and do not `report-blocked` merely because that review is
   pending. Focused plan reviewers receive the same embedded plan snapshot guidance as
   whole-plan review. Discovery may use flat `target_refs`, structured
   `instance_ref`, or optional `finding_families` within scope — see
   `review-respond`, `review-respond-focused-with-instance-ref`,
   `review-respond-family-discovery-focused-plan`, and
   `review-respond-family-discovery-focused-output`. Verification uses
   `review-respond-verification`. Focused loops do not run `scope_review` or
   require audit attestation.

## Run store

Agent commands locate runs via `--runs-dir`, `$TDP_RUNS_DIR`, or `./runs` (in that
precedence). Provider subprocesses receive `TDP_RUNS_DIR`, `TDP_RUN_ID`,
`TDP_AGENT_REQUESTS_DIR`, and `TDP_CAPABILITY_TOKEN_FILE`, so in-agent
commands typically need only `--run <run-id>`. Run ids use
`run-YYYYMMDDTHHMMSS-<6hex>` (UTC creation time plus random suffix).

`plan.json` items include `depth` (0-based from the tree root, derived from
`parent_id`). Depth is required on load and recomputed on save.

`digests.context_spec` binds agent-context **declarations** at run creation: default, role,
and activity models, configured guidance entries, resource path selection, skill declarations (workspace-relative
paths or `tdp:builtin:` keys for packaged skills), and the resolved
`context_snapshot` exclusion policy (defaults, ordered patterns, built-in policy version).
`digests.context_snapshot` binds materialized resource bytes, skill contents, and guidance
text/file digests via `context_snapshot_binding` (compact relative-path → bare SHA-256 hex
maps; guidance remains a list of digest entries). Exclusions apply to resource collection
only — skills and guidance stay bound. Direct file resources always bind; directory/glob
discoveries are filtered. Each `production apply` validates cumulative snapshot drift
against the candidate batch outputs; production completion re-validates and rebases the
snapshot when drift is attributable to hash-matched production evidence (latest
``output_evidence`` per path must match current workspace bytes). Apply authorizes
candidate batch output refs before capture. Unauthorized drift blocks apply retry,
completion, or resume. Resource paths and evidence refs must
resolve inside the workspace; escapes and absolute refs fail explicitly. Invalid
persisted evidence refs fail rebase validation rather than masquerading as unauthorized
drift. `.gitignore` is not inherited. Omitting
`context_snapshot` equals `excludes.defaults: true` with empty user patterns.

## Sub-TDP accepted results

Parent Sub-TDP orchestration binds each completed unit with an immutable
`accepted_result` attestation and matching `accepted_result_digest`. The
attestation is content-bound:

- `workspace_changes`: map of canonical relative path → write record with
  `operation: "write"`, `sha256`, `size`, and `snapshot_ref`. Built from live-batch
  `output_evidence` only; the latest capture per path is the authoritative final
  state. Path authorization from bare `output_refs` is rejected.
  Delete tombstones are not supported until production can capture them.
- `baseline_context_snapshot_digest`: context snapshot when the child started.
- `baseline_accepted_result_digests`: ordered predecessor accepted-result digests
  explaining the baseline snapshot (empty when rooted at the package initial
  snapshot; one digest for linear closure; multiple for composite `--baseline`
  joins). Persisted on `package_binding` and included in the accepted-result
  attestation digest.
- `final_context_snapshot_digest`: context snapshot when the child finished
  (rebased after whole-output owner revisions that change resources).
- `output_refs`: objects with `id`/`type`/`ref`; each `ref` must appear in
  `workspace_changes`.

Cumulative workspace baselines merge accepted results in snapshot-lineage order.
Parent sub-TDP authorization loads the prepared package's initial
`context_snapshot_digest` as the succession root. Within a baseline set,
`baseline_accepted_result_digests` on each accepted result explicitly identifies
predecessor closure (empty for roots at the package initial snapshot, one digest
for linear joins, multiple for composite multi-result `--baseline` joins).
`depends_on` adds further constraints. When replaying accepted results with path-writer
tracking, same-path hash overwrites require the digest of the result that last wrote
that path to appear in the incoming result's
`baseline_accepted_result_digests`. Without path-writer tracking, overwrites are
allowed when the incoming baseline snapshot digest matches the cumulative snapshot
after prior accepted results. Unrepresentable baseline joins fail closed.

Upstream wrappers also carry `accepted_result_digest` and
`upstream_contract_digest`. Parent resume, baseline authorization, and
whole-output entry re-derive each wrapper's delivery from live child production,
then verify current workspace bytes once against the fully merged baseline map
(not per historical wrapper individually). Parent integration production evidence
may supersede child hashes on shared paths when the parent captures new output.

Run records carry top-level `schema_version` (currently `3`), distinct from config document
`version`. Old absolute-path or list-shaped bindings and unsupported schema versions are
rejected — recreate the run; there is no migrator. Prefer snapshot excludes over
`PYTHONDONTWRITEBYTECODE=1` as the durable fix for bytecode false positives.

`digests.config_contract` binds approval-meaning configuration (input/output goal semantics,
boundaries, acceptance, review policy, context declarations). `digests.config_execution`
binds operational limits and execution budgets (including `limits.provider.max_retries_per_call`,
`limits.provider.turn_idle_timeout_seconds` for Cursor stream idle detection, and
`limits.provider.max_stream_json_record_bytes` for the assembled stream-json line cap, including the terminating newline).
Approvals bind to `config_contract`, not
`config_execution`. The monolithic `digests.config` field is not accepted on schema v3.

Provider session replacement (one attempt per `phase_action_id`) runs when Cursor reports a
missing remote session (`provider_session_not_found`) or when a turn stalls with no
stream-json stdout within `limits.provider.turn_idle_timeout_seconds` when that limit is
greater than zero (`provider_turn_stalled`). Replacement exhausted for the current
`phase_action_id` fails the run with `session_recovery_exhausted`.

Run lifecycle fields on `run.json`: `status` (`running`, `paused`, `completed`, `failed`);
`outcome` (non-null only when `status` is `completed`); `stop` (structured stop record
when paused or failed, otherwise null); `phase_action_id` (active logical action id for
the current in-flight provider step, or null after the provider/domain boundary
commits); `phase_action_domain_committed_id` (the last provider action whose domain
boundary committed successfully). `provider_turn_failed` means an actual provider turn
failed while that action was still active; persist the interrupted id in
`stop.details.phase_action_id` with `domain_committed: false`. Orchestration or review
state conflicts after a successful turn use `orchestrator_state_conflict` or
`review_state_conflict`, not `provider_turn_failed`. Provider session teardown failures
on a running run also use `orchestrator_state_conflict`. Paused stops use `category: operational` with
`code` in `limit_exhausted`, `review_incomplete`, `provider_unavailable`,
`provider_turn_failed`, `orchestrator_state_conflict`, `review_state_conflict`,
`focused_review_wait`, `user_cancelled`, `orchestrator_interrupted`, or `amendment_pending` (internal amendment)
checkpoint); failed stops use `category: invariant` with
`code` in `state_integrity_failure`, `evidence_integrity_failure`,
`unsupported_phase_state`, `orchestrator_invariant_failure`, or
`session_recovery_exhausted`. Each stop record includes `phase`, `message`, `role`
(null when unset), and optional `details`. For `user_cancelled`, `details.terminated_pids`
lists agent subprocess pids stopped during cancel. Cancel also records `agent_terminated`
and `planner_session_ended` / `producer_session_ended` / `reviewer_session_ended` audit
events. `RunEngine.continue_run` scans for orphan agents (`agent_orphan_cleaned` when
cleaned). `status: running` with no live orchestrator is normal between blocking CLI
steps (idle, awaiting resume). When orphan agents remain, reconcile to `paused` with
`orchestrator_interrupted` via `tdp doctor --fix` or automatic resume preflight when
orphans are detected. Use `tdp doctor --run <id>` to inspect orphan agent pids, or
`tdp doctor --fix` to kill orphans, reconcile interrupted runs, and remove leftover
`.creating-*` staging directories. Omit `--run` for workspace-level diagnostics.

## Resume

Paused runs resume through `prepare_resume()` (read-only) and
`apply_resume_plan_atomically()` (config + status transition). The CLI wraps both:

- `tdp resume --run <id> --config <yaml>` — apply candidate config and continue
- `tdp resume --run <id> --set limits.planning.max_agent_turns=40` — limit-only override
- `tdp resume --run <id> --check ...` — print the resume plan; no writes or provider calls.
  `--check` also reports semantic lifecycle diagnostics (stale review-bound production blockers, unsatisfiable review-bound waits whose matching loop is already terminal, ambiguous untyped legacy blockers, misclassified `provider_turn_failed` after a committed phase action, and
  advisory handoff identity mismatches) with a proposed safe reconciliation. It does
  not mutate ambiguous state.
- `tdp resume --run <id> --until plan|validated|completed` — loop `RunEngine` after apply
  (default: one orchestrator step)
- `tdp resume --run <id> --allow-config-drift --config <yaml>` — opt in to contract/model
  config changes on resume (see below)

`tdp run` and `tdp prepare` report live input/output-goal drift during `create_run`
as `creation_snapshot_changed` when no canonical run exists yet. Persistence errors
against an existing run remain `corrupt_run`.

By default, resume rejects contract drift (`run.output_goal`, prompts, review/planning
settings, model, and other approval-meaning fields), non-model `context_spec` drift
(guidance/resource/skill declarations and snapshot exclusion policy), and
provider/workspace changes. `--allow-config-drift` is a per-invocation escape hatch.
Before mandatory whole-plan approval, accepted contract and model changes apply and
update `digests.config_contract`, `digests.input`, `digests.output_goal`, and
`digests.context_spec` atomically with the new resolved config. Model-only
`context_spec` drift is accepted under the same flag; other `context_spec` fields remain
strict. After whole-plan approval, approval-bound contract and model changes are ignored
(warned in `--check` / apply summary) while limit changes and presentation changes still
apply; approval records are not invalidated or rewritten.

Limit-only changes update `digests.config_execution` only; approvals remain bound to
`digests.config_contract`. Failed runs cannot be resumed. Replacement exhausted for the
current `phase_action_id` blocks resume until the action completes or the run fails.

Execution limits on resume may increase or decrease. When consumption is tracked
(`limit_exhausted` stop details), the candidate value must be strictly greater than
`consumed`; otherwise any numeric change is accepted. Untracked limits accept any
numeric change.

For mandatory whole-plan / whole-output `limit_exhausted` pauses, `stop.details` must
include the full limit path (`limits.whole_*_review.max_*`), integer `consumed` /
`configured`, `loop_id`, and `exhausted_budget`. Resume requires the exhausted limit's
candidate value to be strictly greater than consumed usage. Setting that limit above
consumed usage revives the same review loop and preserves `revision_cycles` /
`scope_review_rounds` — it does not open a new loop or reset the phase budget
counter. For `exhausted_budget=verification_revision`, revival also sets
`pending_revision_cycle_entry` because the pause happened before
`enter_revision_cycle` charged the next owner revision; continue then consumes
exactly one new cycle and clears the flag. A genuine mid-cycle interrupt after
a charged `enter_revision_cycle` leaves `pending_revision_cycle_entry` false and
resumes the owner without incrementing again.

When a reviewer gate turn ends without `review respond`, the run pauses with
`limits.review.max_agent_turns_per_gate` once the per-gate turn budget is exhausted.
`stop.details` carries `loop_id` and consumed `gate_agent_turns` (no `exhausted_budget`).
Resume requires `limits.review.max_agent_turns_per_gate` strictly above the consumed
gate-turn count; the in-progress review loop is preserved.

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

Completion claims require non-empty `goal_assessment` (the submit-completion command
implies `goal_met`). During `whole_output_review`, set `evidence_revision: true` on
`production apply` with new output evidence IDs when revising terminal items after
reviewer `changes_requested`.
During `production`, focused-output evidence revision requires `focused_review_loop_id`
and matches the loop `target_revision` to the current `output_revision`.

Plan `snapshot` and `check` responses separate validation `issues` (errors with
`code`, `message`, optional `path`) from `warnings` (human-readable strings).
`apply` returns the same split plus mutation budget warnings and sets
`applied: true` only when the batch was persisted. Compact apply responses omit
`changed_subtree` and per-item `planning_budget`; refresh with `plan snapshot`
(`--view active` or `--view budget` for planning limits). Mutations that would introduce
new hard validation errors are rejected before persistence with `operation_error`
and leave the plan revision unchanged. `ok` is true only when validation has no
error-severity issues after a persisted apply (inspect `issues` after apply even
when `applied: true` for pre-existing draft issues). Production `snapshot` uses the same plan validation shape;
use `production check` for batch/disposition-specific checks. Active plan snapshots
include item-owned `scope`, `boundaries`, `acceptance`, `risks`, and `source_refs`.
Production `ready` snapshots and `approved_plan.items` add merged `effective_scope`
and `effective_boundaries`. Plan `ready` views exclude items blocked by unresolved
`focused_plan` / `whole_plan` findings; production `ready` views exclude items
blocked by unresolved `focused_output` / `whole_output` findings. Plans carry
`schema_version` (currently 2). Unsupported or missing plan `schema_version`
fails load with a recreate message — there is no plan migrator. `check --mode approval` always runs
approval-mode soft limits; digest and whole-plan review hooks compare against a
stored approval when one exists for the current revision, otherwise surface
`*_not_checked` warnings. Prefer dependency edges on the narrowest meaningful
plan item when a more specific descendant already captures the prerequisite.

`plan snapshot`, `plan apply`, and `plan check` exit 0 only when `ok` is true.
When `item-root` has active children, draft validation errors on
`default_root_title` (seeded title `Root`) or `missing_root_outcome`.
`production snapshot` and `production check` follow the same rule. A persisted
`plan apply` may return `applied: true` with exit 1 only when post-apply validation
reports pre-existing error-severity issues that the mutation did not introduce.
`production apply` returns `ok: true` when the batch was persisted;
use `production snapshot` or `production check` for plan validation.

## Further reading

Agent hub: tools/top_down_planning/docs/README.md
Package README: tools/top_down_planning/README.md
"""

AGENT_README_TEXT = (
    AGENT_README_PREFIX
    + _finding_category_readme_section()
    + _finding_family_readme_section()
    + _audit_attestation_readme_section()
    + _builtin_rule_readme_section()
    + _AGENT_README_PLAN_DEPENDENCIES
    + _AGENT_README_WORKFLOW_AND_BEYOND
)


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
