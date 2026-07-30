"""CLI-discoverable schemas, examples, and agent help for ``tdp agent`` (proposal §8, §20)."""

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

_SCHEMAS: dict[str, dict[str, Any]] = {
    "config": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "TopDownPlanningConfig",
        "description": "Resolved run configuration (proposal §14).",
        "type": "object",
        "required": ["version", "project", "run", "agent_context", "planning", "review", "provider", "limits"],
        "properties": {
            "version": {"type": "integer"},
            "project": {
                "type": "object",
                "description": (
                    "Shared project context. project.workspace is the canonical "
                    "workspace root. project.resources resolve against "
                    "project.workspace."
                ),
                "properties": {
                    "workspace": {
                        "type": "string",
                        "description": (
                            "Canonical workspace root. Relative paths resolve "
                            "against the process working directory."
                        ),
                    },
                    "resources": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "additionalProperties": False,
            },
            "agent_context": {
                "type": "object",
                "description": (
                    "Per-role model, resources, and skills. Resources and skills "
                    "are additive with agent_context.default and project.resources."
                ),
                "properties": {
                    role: {
                        "type": "object",
                        "properties": {
                            "model": {"type": "string"},
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
                    "focused_plan": {
                        "type": "object",
                        "properties": {"enabled": {"type": "boolean"}},
                        "additionalProperties": False,
                    },
                    "focused_output": {
                        "type": "object",
                        "properties": {"enabled": {"type": "boolean"}},
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
                            "max_revision_cycles": {"type": "integer"},
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
                            "max_revision_cycles": {"type": "integer"},
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
            "across the full run history."
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
                    "During whole_output_review only: revise outputs for terminal "
                    "plan_items targeted by unresolved blocking findings without "
                    "changing dispositions."
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
        "description": "Review findings and decision for `tdp agent review respond`.",
        "type": "object",
        "required": ["loop_id", "target_revision", "decision", "findings"],
        "properties": {
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
    "evidence-revision": {
        "schema": "production-apply",
        "description": (
            "During whole_output_review, revise evidence for terminal items targeted "
            "by unresolved blocking findings."
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
  tdp agent plan snapshot --run <run-id> [--view tree|ready|issues]
  tdp agent plan apply --run <run-id> --request <file>
  tdp agent plan check --run <run-id> [--mode draft|approval]

Production:
  tdp agent production snapshot --run <run-id> [--view tree|ready]
  tdp agent production apply --run <run-id> --request <file>
  tdp agent production check --run <run-id>
  tdp agent production request-amendment --run <run-id> --request <file>
  tdp agent production submit-completion --run <run-id> --request <file>
  tdp agent production report-blocked --run <run-id> --request <file>

Review:
  tdp agent review request --run <run-id> --request <file>
  tdp agent review respond --run <run-id> --request <file>

Whole-plan and focused_plan reviewers receive an embedded plan snapshot in the
review package; call `tdp agent plan snapshot --run <run-id> --view tree` to
refresh before responding when the plan may have changed.

Run status:
  tdp agent run status --run <run-id>

Run store: agent commands use --runs-dir, $TDP_RUNS_DIR, or ./runs. The orchestrator
exports the resolved absolute store root as TDP_RUNS_DIR and a session-scoped
TDP_CAPABILITY_TOKEN to provider subprocesses. Mutating commands require the token;
authorization is bound to run phase and session role, not a self-declared flag.

Published schemas: """ + ", ".join(PUBLIC_SCHEMAS) + """
Published examples: """ + ", ".join(PUBLIC_EXAMPLES) + """

Request bodies are JSON or YAML objects. Use --request <file> or pipe stdin.
Revision fields (base_revision, production_revision) must match the latest snapshot.
"""

AGENT_README_TEXT = """# Top Down Planning — agent protocol

`tdp` orchestrates planning and production with structured agent tools. Agents interact
only through `tdp agent` commands; the orchestrator owns lifecycle transitions, limits,
and mandatory review gates.

## Session roles and authorization

The orchestrator binds one primary planner, producer, or reviewer session per phase.
Mutating `tdp agent` commands require the session capability token exported as
`TDP_CAPABILITY_TOKEN`. Authorization checks phase, allowed operations, the bound
provider session, and (for reviewers) the review loop. Capability records store
only a `secret_hash`; tokens are revoked when turns, loops, or phases end. Agents
do not pass `--role` on the CLI.

- planner — mutate the plan during planning or amendment
- producer — record production batches, completion claims, blockers, amendment requests
- reviewer — submit review findings and decisions

## Workflow

1. Planner expands the plan with `plan apply` until `candidate_plan_ready`.
2. Mandatory whole-plan review (`review respond`) must approve before production.
   Review packages include an embedded plan tree; refresh with
   `plan snapshot --view tree` when revising after `changes_requested`.
3. Producer records batches with `production apply`, then `submit-completion` with
   `goal_met: true` and a `goal_assessment` rationale.
4. Mandatory whole-output review must approve before `outcome: accepted`. After
   `changes_requested`, the producer must use `production apply` with
   `evidence_revision: true` and **new** output evidence IDs on terminal items
   targeted by unresolved blocking findings (dispositions unchanged), then
   re-submit completion with `goal_met: true`.
   Plan amendment is not available during whole-output review.
5. Optional focused reviews use `review request` with bounded `scope.item_ids`.
   Focused plan reviewers receive the same embedded plan snapshot guidance as
   whole-plan review.

## Run store

Agent commands locate runs via `--runs-dir`, `$TDP_RUNS_DIR`, or `./runs` (in that
precedence). The orchestrator exports the resolved absolute store root as
`TDP_RUNS_DIR` and a session-scoped `TDP_CAPABILITY_TOKEN` to provider subprocesses,
so in-agent commands typically need only `--run <run-id>`.

Production `outputs` in apply requests need only `id`, `type`, and workspace `ref`.
The service captures content hashes and stores immutable snapshots under
`artifacts/<snapshot-uuid>/<filename>` in the run store. Reusing an evidence ID
across batches is rejected.

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
Specification: tools/top_down_planning/docs/spec.md
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
