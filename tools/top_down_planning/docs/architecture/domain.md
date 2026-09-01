# Domain model and invariants

**Audience:** maintainers changing plan, production, or review rules.

Shared vocabulary: [plan tree](../concepts/plan-tree.md), [quality loop](../concepts/quality-loop.md), [lifecycle terms](../concepts/lifecycle-terms.md). Type names below are maintainer vocabulary, not a user-facing API.

Domain code is pure: it must not import CLI, config, persistence, orchestrator, or `core_tools`. Orchestrator and agent_tool call domain functions and persist results.

## Plan

A `Plan` has an `output_goal`, plan-level `scope` / `boundaries` / `constraints` / `assumptions` / `acceptance` / `risks`, `input_refs`, and a tree of `PlanItem`s. Plans persist `schema_version` (currently 2). Unsupported versions fail load; there is no plan migrator.

Items are `work` or `aggregate`. Aggregates are never in the production ready set; their satisfaction is derived from descendants. Only `planning_status=open` items participate. `item-root` is required.

**Effective contract:** `effective_scope` / `effective_boundaries` = plan-level lists then item-level lists (blanks skipped, case-insensitive dedupe). Producers enforce batch boundaries from `effective_*`. Every active `work` leaf must declare item-level scope includes/excludes and/or boundaries.

**Dependencies:** `depends_on` must name existing items; cycles are validation errors. Readiness: a `work` item is ready when active, not yet terminal, and every dependency is satisfied (explicit disposition or derived subtree). Review findings can block readiness (`review_blocked`).

Soft planning limits (`planning.max_depth`, `planning.max_expansion_per_item`) bound construction; they are not run status.

## Production

Applicable items are active `work` items that are not yet terminal. Terminal dispositions: `completed`, `satisfied_without_change`, `not_applicable`, `superseded`, `blocked`. Satisfied dispositions exclude `blocked`. Aggregates do not take batch dispositions.

Output evidence is content-bound at apply time: agents supply `id`, `type`, `ref`; the service captures hash, size, media type, snapshot. Evidence IDs are unique across the run. Snapshot-bound workspace drift must appear in that batch’s `outputs` or apply fails (`production_evidence_incomplete` / `production_context_mutation_unauthorized`).

A completion claim that asserts the goal is met is persisted with `goal_met`, current plan revision, and current output revision. Agent request shape is only `goal_assessment` + `production_revision` ([producer](../agents/producer.md)).

`production_revision` versions production state; `output_revision` versions the output snapshot used by review and claims.

Structured `blocker_report` values are either `external` (genuine terminal blocked outcome) or `focused_review_wait` (recoverable pause). Before terminalizing, orchestration re-evaluates review-bound identity (loop, revision, and digest when the blocker recorded one). Untyped legacy blockers are rebound only from unambiguous event history. An active wait pauses with `stop.code=focused_review_wait` rather than `outcome=blocked`. Details: [review architecture](../internals/reviews.md).

## Reviews

Loop types: `focused_plan`, `focused_output`, `whole_plan`, `whole_output`. Decisions include `approved`, `changes_requested`, `blocked`. Mandatory whole-artifact loops add stages and finding families. Approval identity is the plan versus whole-output digest key sets (not a single contract digest): [review architecture](../internals/reviews.md) and [split-digest decision](../decisions/split-config-digests.md). Unresolved required findings block acceptance.

## Acceptance

The acceptance invariant is a conjunction: current whole-plan approval, deterministic plan validation, all applicable items terminal or derived, completion claim goal assessed as met, current whole-output approval, deterministic output validation, zero unresolved required findings. Mapping to quality outcomes: [lifecycle architecture](lifecycle.md).

Related: [system context](system-context.md), [decisions](../decisions/README.md).
