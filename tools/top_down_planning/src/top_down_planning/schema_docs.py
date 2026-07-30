"""CLI-discoverable schemas, examples, and agent help for ``tdp agent`` (proposal §8, §20)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.domain.dispositions import TERMINAL_DISPOSITIONS

PUBLIC_SCHEMAS: tuple[str, ...] = (
    "config",
    "plan-transaction",
    "production-apply",
    "review-respond",
    "focused-review-request",
    "amendment-request",
    "completion-claim",
    "blocker-report",
)

PUBLIC_EXAMPLES: tuple[str, ...] = (
    "expand-branch",
    "batch-result",
    "empty-output",
    "review-respond",
    "focused-review-request",
    "amendment-request",
    "completion-claim",
    "blocker-report",
)

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
                "item": {"type": "object"},
            },
            "additionalProperties": True,
        },
        {
            "type": "object",
            "required": ["op", "item_id", "patch"],
            "properties": {
                "op": {"const": "update_item"},
                "item_id": {"type": "string"},
                "patch": {"type": "object"},
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
            "properties": {
                "op": {"const": "supersede_item"},
                "item_id": {"type": "string"},
                "temp_id": {"type": "string"},
                "replacement": {"type": "object"},
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
    "required": ["id", "importance", "target_refs", "issue", "required_change"],
    "properties": {
        "id": {"type": "string"},
        "importance": {"type": "string", "enum": ["blocking", "advisory"]},
        "target_refs": {"type": "array", "items": {"type": "string"}},
        "issue": {"type": "string"},
        "required_change": {"type": "string"},
        "status": {
            "type": "string",
            "enum": ["unresolved", "resolved", "superseded"],
        },
    },
    "additionalProperties": False,
}

_SCHEMAS: dict[str, dict[str, Any]] = {
    "config": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "TopDownPlanningConfig",
        "description": "Resolved run configuration (proposal §14).",
        "type": "object",
        "required": ["version", "run", "planning", "review", "provider", "limits"],
        "properties": {
            "version": {"type": "integer"},
            "run": {
                "type": "object",
                "properties": {
                    "input_refs": {"type": "array", "items": {"type": "string"}},
                    "output_goal": {"type": "string"},
                },
            },
            "planning": {
                "type": "object",
                "properties": {
                    "stop_hint": {"type": "string"},
                    "max_depth": {"type": "integer"},
                    "max_expansion_per_item": {"type": "integer"},
                },
            },
            "review": {"type": "object"},
            "provider": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "enum": ["cursor", "stub"]},
                    "use_native_project_context": {"type": "boolean"},
                    "model": {"type": "string"},
                    "binary": {"type": "string"},
                    "skip_probe": {"type": "boolean"},
                },
            },
            "limits": {"type": "object"},
        },
        "additionalProperties": True,
    },
    "plan-transaction": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "PlanApplyRequest",
        "description": "Atomic plan transaction for `tdp agent plan apply`.",
        "type": "object",
        "required": ["base_revision", "operations"],
        "properties": {
            "role": {"type": "string"},
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
        "description": "Production batch request for `tdp agent production apply`.",
        "type": "object",
        "required": ["production_revision", "plan_items", "dispositions"],
        "properties": {
            "role": {"type": "string"},
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
        },
        "additionalProperties": False,
    },
    "review-respond": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ReviewRespondRequest",
        "description": "Review findings and decision for `tdp agent review respond`.",
        "type": "object",
        "required": ["loop_id", "target_revision", "decision", "findings"],
        "properties": {
            "role": {"type": "string"},
            "loop_id": {"type": "string"},
            "target_revision": {"type": "integer"},
            "decision": {
                "type": "string",
                "enum": ["approved", "changes_requested", "blocked"],
            },
            "findings": {
                "type": "array",
                "items": _REVIEW_FINDING_SCHEMA,
            },
        },
        "additionalProperties": False,
    },
    "focused-review-request": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "FocusedReviewRequest",
        "description": "Optional focused review request for `tdp agent review request`.",
        "type": "object",
        "required": ["type", "scope"],
        "properties": {
            "role": {"type": "string"},
            "type": {
                "type": "string",
                "enum": ["focused_plan", "focused_output"],
            },
            "scope": {
                "type": "object",
                "required": ["kind", "item_ids"],
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["focused_plan", "focused_output"],
                    },
                    "item_ids": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string"},
                    },
                },
                "additionalProperties": False,
            },
        },
        "additionalProperties": False,
    },
    "amendment-request": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "AmendmentRequest",
        "description": "Controlled plan amendment request for `tdp agent production request-amendment`.",
        "type": "object",
        "required": ["evidence", "affected_refs"],
        "properties": {
            "role": {"type": "string"},
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
        "required": ["goal_assessment"],
        "properties": {
            "role": {"type": "string"},
            "goal_assessment": {"type": "string", "minLength": 1},
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
            "role": {"type": "string"},
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
    "review-respond": {
        "schema": "review-respond",
        "description": "Reviewer requests plan changes with one blocking finding.",
        "payload": {
            "loop_id": "review-whole-plan-01",
            "target_revision": 0,
            "decision": "changes_requested",
            "findings": [
                {
                    "id": "finding-001",
                    "importance": "blocking",
                    "target_refs": ["item-api"],
                    "issue": "Acceptance criteria are not testable.",
                    "required_change": "Add concrete acceptance checks for API behavior.",
                    "status": "unresolved",
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

Plan (planner role):
  tdp agent plan snapshot --run <run-id> [--view tree|ready|issues]
  tdp agent plan apply --run <run-id> --role planner --request <file>
  tdp agent plan check --run <run-id> [--mode draft|approval]

Production (producer role):
  tdp agent production snapshot --run <run-id> [--view tree|ready]
  tdp agent production apply --run <run-id> --role producer --request <file>
  tdp agent production check --run <run-id>
  tdp agent production request-amendment --run <run-id> --role producer --request <file>
  tdp agent production submit-completion --run <run-id> --role producer --request <file>
  tdp agent production report-blocked --run <run-id> --role producer --request <file>

Review:
  tdp agent review request --run <run-id> --role planner|producer --request <file>
  tdp agent review respond --run <run-id> --role reviewer --request <file>

Run status:
  tdp agent run status --run <run-id>

Published schemas: """ + ", ".join(PUBLIC_SCHEMAS) + """
Published examples: """ + ", ".join(PUBLIC_EXAMPLES) + """

Request bodies are JSON or YAML objects. Use --request <file> or pipe stdin.
Revision fields (base_revision, production_revision) must match the latest snapshot.
"""

AGENT_README_TEXT = """# Top Down Planning — agent protocol

`tdp` orchestrates planning and production with structured agent tools. Agents interact
only through `tdp agent` commands; the orchestrator owns lifecycle transitions, limits,
and mandatory review gates.

## Roles

- planner — mutate the plan during planning or amendment
- producer — record production batches, completion claims, blockers, amendment requests
- reviewer — submit review findings and decisions

## Workflow

1. Planner expands the plan with `plan apply` until `candidate_plan_ready`.
2. Mandatory whole-plan review (`review respond`) must approve before production.
3. Producer records batches with `production apply`, then `submit-completion`.
4. Mandatory whole-output review must approve before `outcome: accepted`.
5. Optional focused reviews use `review request` with bounded `scope.item_ids`.

## Discoverability

- `tdp agent schema [<name>]` — JSON Schema for request/config contracts
- `tdp agent example [<name>]` — minimal valid example payloads
- `tdp agent help` — command summary

## Revision safety

Plan apply requires `base_revision` from `plan snapshot`. Production apply requires
`production_revision` from `production snapshot`. Stale revisions return a conflict
error with instructions to refresh the snapshot.

Plan `snapshot` and `check` responses separate validation `issues` (errors with
`code`, `message`, optional `path`) from `warnings` (human-readable strings).
`apply` returns the same split plus mutation budget warnings and sets
`applied: true` when the batch was persisted. `ok` is true only when validation
has no error-severity issues (inspect `issues` after apply even when
`applied: true`). Production `snapshot` uses the same plan validation shape;
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
`production snapshot` and `production check` follow the same rule. `plan apply`
may return `applied: true` with exit 1 when post-apply validation reports
errors. `production apply` returns `ok: true` when the batch was persisted;
use `production snapshot` or `production check` for plan validation.

## Further reading

Package README: tools/top_down_planning/README.md
Specification: temp/final-top-down-planning-tool-proposal.md
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


def validate_against_schema(value: Any, schema: dict[str, Any], *, path: str = "$") -> list[str]:
    """Minimal JSON Schema checker for published contracts (no external deps)."""

    issues: list[str] = []

    if "oneOf" in schema:
        branch_issues = [
            validate_against_schema(value, branch, path=path)
            for branch in schema["oneOf"]
        ]
        if not any(not branch for branch in branch_issues):
            issues.append(f"{path}: value does not match any oneOf branch")
        return issues

    schema_type = schema.get("type")
    if schema_type == "object":
        if not isinstance(value, dict):
            return [f"{path}: expected object"]
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(schema.get("properties", {}))
            if extra:
                issues.append(f"{path}: unexpected properties: {sorted(extra)}")
        elif isinstance(schema.get("additionalProperties"), dict):
            allowed = set(schema.get("properties", {}))
            value_schema = schema["additionalProperties"]
            for key, item in value.items():
                item_path = f"{path}.{key}"
                if key in allowed:
                    continue
                issues.extend(
                    validate_against_schema(item, value_schema, path=item_path)
                )
        for key in schema.get("required", []):
            if key not in value:
                issues.append(f"{path}: missing required property {key!r}")
        for key, prop_schema in (schema.get("properties") or {}).items():
            if key in value:
                issues.extend(
                    validate_against_schema(value[key], prop_schema, path=f"{path}.{key}")
                )
        return issues

    if schema_type == "array":
        if not isinstance(value, list):
            return [f"{path}: expected array"]
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(value):
                issues.extend(
                    validate_against_schema(
                        item,
                        item_schema,
                        path=f"{path}[{index}]",
                    )
                )
        min_items = schema.get("minItems")
        if min_items is not None and len(value) < min_items:
            issues.append(f"{path}: expected at least {min_items} items")
        return issues

    if schema_type == "string":
        if not isinstance(value, str):
            return [f"{path}: expected string"]
        if "enum" in schema and value not in schema["enum"]:
            issues.append(f"{path}: value {value!r} not in enum")
        min_length = schema.get("minLength")
        if min_length is not None and len(value) < min_length:
            issues.append(f"{path}: string shorter than minLength {min_length}")
        return issues

    if schema_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            return [f"{path}: expected integer"]
        return issues

    if schema_type == "boolean":
        if not isinstance(value, bool):
            return [f"{path}: expected boolean"]
        return issues

    if isinstance(schema_type, list):
        if any(
            not validate_against_schema(value, {"type": option}, path=path)
            for option in schema_type
        ):
            return []
        return [f"{path}: expected one of types {schema_type}"]

    if "const" in schema and value != schema["const"]:
        issues.append(f"{path}: expected const {schema['const']!r}")

    return issues


def default_config_example() -> dict[str, Any]:
    """Return a copy of built-in defaults for schema smoke tests."""

    return deepcopy(DEFAULT_CONFIG)
