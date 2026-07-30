# Final Top Down Planning Tool Proposal

## 1. Purpose

The Top Down Planning tool is a generic agent orchestration system that receives an input and an output goal, creates a high-level top-down plan, reviews and validates that plan, and then produces the requested output in coherent agent-selected batches.

The tool is responsible for:

- High-level flow and decomposition.
- Scope, exclusions, and boundaries.
- Material dependencies and sequencing.
- Review and revision loops.
- Lightweight deterministic validation.
- Controlled plan amendment when production exposes a material planning problem.
- Completion assessment and final outcome resolution.

The tool is not intended to become a detailed task manager, a domain-specific workflow engine, or a repository of implementation-level instructions. Detailed execution choices remain with the active agent and the project context supplied by the configured provider.

---

## 2. Core design principles

### 2.1 Top-down and high-level

The planner begins with the complete input and output goal, establishes the overall shape, and expands only where the additional structure improves understanding, control, or production.

A plan item should normally stop expanding when it has:

- One coherent intended outcome.
- Clear included and excluded scope.
- Important boundaries.
- Material dependencies.
- A recognizable completion or acceptance condition.
- A clear contribution to its parent and the output goal.

The plan should not decompose into implementation steps merely because more depth is available.

### 2.2 One owner per primary phase

Planning and production each have one persistent primary session:

- One primary planner session owns the complete planning phase.
- One primary producer session owns the complete production phase.

Feedback never causes the orchestrator to replace the active primary session. Revisions resume the same owner session so it retains intent and continuity.

### 2.3 Independent but continuous review loops

Every new review/revision loop starts a fresh reviewer session with a clean, bounded review package.

Within that review/revision loop, the same reviewer session remains active. It remembers its original findings, examines the primary agent's revisions, and determines whether those findings were fixed correctly.

A later, separate review loop always starts a new reviewer session and does not inherit unrelated reviewer history.

### 2.4 Structured interaction through tools

Agents should use structured tool operations for plan state, production state, review findings, amendment requests, and completion records. Agents should not directly rewrite orchestration files.

The actual output may still be created through normal provider capabilities, such as editing project files or producing text. The orchestration records around that output must be updated through the tool.

Plan items are units of reasoning, coverage, decision, and control. They are not required to map one-to-one to files, changes, or other deliverables. Production may combine many plan items into one output, use one plan item across several outputs, or satisfy an item without producing an artifact.

### 2.5 Quality before mechanical limits

Decomposition depth and expansion limits guide the agent before it creates an oversized plan. They are soft planning limits, not an excuse to produce weak or arbitrary groupings.

The tool surfaces limit usage and warnings during construction. The planner should reshape the plan before exceeding a limit when that can be done without reducing quality. When a sound plan genuinely cannot fit, it should report a blocker instead of silently degrading the decomposition.

### 2.6 Small, durable validation surface

Deterministic validation should cover a small set of important generic invariants. Domain-specific semantics and large rule catalogs should remain outside the core.

### 2.7 Provider abstraction with native context

Cursor CLI is the initial default provider, but the orchestrator depends on a provider interface. Provider-native project rules, skills, and context should remain available to the planner, producer, and reviewers.

---

## 3. Overall lifecycle

```text
Receive input and output goal
        ↓
Analyze context, scope, boundaries, constraints, and conflicts
        ↓
Construct the high-level top-down plan
        ↓
Optional focused plan review/revision loops
        ↓
Mandatory whole-plan review/revision loop
        ↓
Minimal deterministic plan validation
        ↓
Start the primary producer with the approved plan
        ↓
Select a coherent ready batch
        ↓
Produce partial output and record results
        ↓
Optional focused output review/revision loops
        ↓
If production exposes a material plan defect, request amendment
        ↓
Resume the same planner, revise, review, and revalidate the plan
        ↓
Resume the same producer and continue batching
        ↓
Repeat until the whole applicable plan is processed
        ↓
Mandatory whole-output review/revision loop
        ↓
Minimal deterministic output validation
        ↓
Accepted / Rejected / Blocked
```

The planner and producer may perform semantic self-checks and may call the deterministic check tool during their own work. A separate orchestration phase is not required for every self-check. Mandatory final checks still run before plan approval and final acceptance.

---

## 4. Session model

### 4.1 Primary planner session

Exactly one persistent primary planner session owns the planning phase.

It is responsible for:

- Understanding the input and output goal.
- Identifying missing, conflicting, or inconsistent context.
- Establishing scope, exclusions, and boundaries.
- Creating the top-level decomposition.
- Deciding whether each item should expand further.
- Respecting the stop hint, maximum depth, and maximum expansion guidance.
- Proactively requesting a focused review when useful.
- Applying all planning revisions.
- Producing the complete candidate plan.
- Responding to the mandatory whole-plan review.

The orchestrator resumes this same session after every planning review response.

### 4.2 Primary producer session

Exactly one persistent primary producer session owns the production phase. It is separate from the planner session.

It receives:

- The approved plan revision.
- The original input and output goal.
- Scope, boundaries, and acceptance expectations.
- Relevant context references and digests.
- Provider-native project context.

It is responsible for:

- Inspecting unprocessed plan items and dependency readiness.
- Selecting each coherent production batch.
- Producing the partial output for the batch.
- Recording affected plan items, artifacts, changes, or intentional no-change results.
- Proactively requesting a focused review when useful.
- Applying all output revisions.
- Continuing until the whole applicable plan is processed and the output goal is met, or until it is genuinely blocked.
- Requesting a controlled plan amendment when production discovers that the approved plan is materially wrong, incomplete, inconsistent, or no longer suitable.

A batch completing does not permit the producer to stop. The producer must continue while applicable plan items remain unresolved or the output goal remains unmet. The producer may not directly mutate the approved plan.

### 4.3 Reviewer sessions

A reviewer session belongs to exactly one review/revision loop.

A new loop creates a fresh reviewer session. The review package must be explicit and bounded:

- Review purpose.
- Review scope.
- Current plan or output revision.
- Relevant input and context references.
- Scope boundaries and exclusions.
- Applicable acceptance conditions.
- A specific concern or question when the primary agent requested the review.

The reviewer should not receive:

- The private transcript of the primary planner or producer.
- Previous unrelated reviewer conversations.
- Unnecessary project context outside the review scope.
- Prior review findings from other loops unless they are part of the current whole-plan or whole-output artifact itself.

Within the loop, the same reviewer remains active:

```text
Reviewer inspects current revision
        ↓
Reviewer returns findings
        ↓
Primary planner or producer revises in its persistent session
        ↓
Same reviewer checks the revision against the original findings
        ↓
Approve / request another revision / block
```

This gives the reviewer enough continuity to judge whether the original issues were fixed well, without carrying bias from unrelated reviews.

### 4.4 Capability-based authorization

Mutating agent commands are authorized by session capability tokens, not self-declared CLI flags. When the orchestrator starts or resumes a provider session, it:

1. Creates a capability record under `capabilities/` in the run store (persisting only a `secret_hash`, never the raw secret).
2. Binds the capability to the provider `session_id` and, for reviewers, the review `loop_id`.
3. Exports `TDP_CAPABILITY_TOKEN` to the provider subprocess.
4. Revokes prior tokens when re-issuing for the same session, at turn boundaries, when a review loop becomes terminal, and when leaving a phase.
5. Enforces phase, operation, session, and loop checks in the agent tool layer before any mutation.

Role boundaries protect lifecycle integrity:

- The planner may mutate plan state and answer plan reviews.
- The producer may select batches, record production results, request amendments, and answer output reviews.
- A reviewer may submit findings and decisions for its assigned review loop, but may not mutate plan or production state.
- Only the orchestrator may create or resume sessions, change phases, bind approvals to revisions, and write the final run outcome.

Provider prompts and workspace permissions may supplement these guardrails, but authorization remains token-bound in the core.

---

## 5. Review policy

### 5.1 Optional focused reviews

Focused reviews are optional and initiated proactively by the primary planner or producer.

Appropriate focused review targets include:

- One plan branch or bounded group of branches.
- A difficult scope or boundary decision.
- A material dependency decision.
- A risky or consequential production batch.
- A partial output that affects later work.
- A conflict or ambiguity that the primary agent cannot confidently resolve alone.

A focused review must remain within its declared scope. It should not re-review the entire plan or output unless the primary agent explicitly requests a whole review.

### 5.2 Mandatory whole-plan review

The whole-plan review is mandatory.

Planning cannot proceed to production until:

1. The primary planner has completed a candidate plan.
2. A fresh whole-plan reviewer session has reviewed the current full plan.
3. The primary planner has addressed required findings.
4. The same reviewer has approved the revised plan within that loop.
5. Deterministic plan validation passes for the approved plan revision.

If the review loop reaches its configured limit without approval, the run becomes rejected or blocked according to the unresolved cause. It must never be silently accepted.

### 5.3 Mandatory whole-output review

The whole-output review is mandatory.

Final acceptance requires:

1. Every applicable plan item has an explicit terminal production disposition or a valid derived terminal satisfaction state.
2. The primary producer has explicitly assessed the output goal.
3. A fresh whole-output reviewer session has reviewed the complete current output.
4. The primary producer has addressed required findings.
5. The same reviewer has approved the revised output within that loop.
6. Deterministic output validation passes for the approved output revision.

---

## 6. Planning and decomposition controls

### 6.1 Stop hint

`stop_hint` is semantic guidance that explains when additional decomposition is no longer useful.

Example:

```yaml
planning:
  stop_hint: >
    Stop decomposing when an item expresses one coherent outcome with clear
    scope, boundaries, material dependencies, and acceptance expectations.
    Do not decompose into implementation-level tasks.
```

The stop hint is advisory. The planner uses judgment and may stop earlier when the goal is already clear.

### 6.2 Maximum depth

`max_depth` is a soft planning ceiling.

```yaml
planning:
  max_depth: 4
```

The root is depth `0`. Its direct children are depth `1`.

The tool should expose the current depth and remaining depth whenever the planner inspects or expands an item. The planner should avoid creating an item beyond the configured depth. If high-quality decomposition cannot fit, it should regroup the plan or report a blocker.

An exceeded limit is reported by validation and prevents ordinary plan approval. The planner is allowed to record the oversized structure temporarily when needed to explain or repair it; the tool should warn rather than blindly reject the mutation.

### 6.3 Maximum expansion per item

`max_expansion_per_item` is a soft limit on the number of direct children of one item.

```yaml
planning:
  max_expansion_per_item: 7
```

When an item appears to need more children, the planner should first consider:

- Combining closely related outcomes.
- Correcting an overly broad parent.
- Introducing a meaningful intermediate grouping when depth allows.
- Moving unrelated scope into a sibling branch.

The planner must not create arbitrary buckets only to satisfy the number. If a sound decomposition still requires exceeding the configured expansion, the planner should report the conflict and block rather than lower plan quality.

### 6.4 Agent-facing limit hints

Every plan snapshot and plan mutation response should include relevant guidance, for example:

```yaml
planning_budget:
  item_id: backend
  depth: 3
  max_depth: 4
  depth_remaining: 1
  direct_children: 6
  max_expansion_per_item: 7
  expansion_remaining: 1
  warnings:
    - near_depth_limit
    - near_expansion_limit
```

This is intended to influence the agent before it creates an unsuitable structure, not only detect problems at final validation.

---

## 7. Plan model

### 7.1 Plan-level data

The plan should contain only the high-level information required for controlled production and acceptance:

```yaml
plan:
  id: plan-001
  revision: 12
  input_refs: []
  output_goal: "..."
  scope:
    includes: []
    excludes: []
  boundaries: []
  constraints: []
  assumptions: []
  acceptance: []
  items: []
```

### 7.2 Plan item

A plan item should remain compact. It represents something that must be understood, decided, covered, bounded, resolved, or accounted for. It is not inherently a task or deliverable:

```yaml
id: item-backend
parent_id: item-application
order_key: "internal"
title: Backend capability
outcome: Required backend behavior exists and supports the output goal.
scope:
  includes: []
  excludes: []
boundaries: []
depends_on: []
acceptance: []
planning_status: open
```

Notes:

- `id` is stable and never derived from display numbering.
- `parent_id` defines decomposition hierarchy.
- `order_key` is managed internally by the tool. Agents do not calculate it.
- `depends_on` defines prerequisite relationships and is separate from hierarchy.
- Children are derived from `parent_id`; they do not need to be duplicated in the item.
- Display numbers such as `1.2.3` are generated from current tree order and are never canonical identifiers.
- No item type should force a one-to-one mapping to an output artifact.
- Item-to-output relationships are recorded later as optional many-to-many production contributions.

### 7.3 Hierarchy and dependencies are separate

Hierarchy means:

> This item is a decomposition of its parent.

Dependency means:

> This item requires another item to be satisfied first.

A child does not automatically depend on its parent. Siblings do not automatically depend on one another. Cross-branch dependencies are valid.

A dependency may target any plan item, but its satisfaction must be explicit and inspectable. Resolution follows a simple rule:

1. Use the item's explicit terminal disposition when one exists.
2. Otherwise, for a non-leaf item, derive satisfaction from its applicable subtree.
3. Otherwise, the dependency remains unresolved.

The tool should expose the concrete unresolved descendant or disposition that prevents satisfaction rather than relying on hidden aggregation behavior. The first implementation should prefer dependencies on the narrowest meaningful item. Broader subtree dependencies remain supported for flexibility, but must not produce surprising readiness behavior.

---

## 8. Agent-friendly plan interaction tool

The best interaction shape is one unified structured CLI with a small read/apply/check protocol. Agents should work with stable IDs, relative placement, and atomic transactions rather than global indexes or direct file edits.

The core agent-facing commands are:

```text
tdp agent help
tdp agent readme
tdp agent schema <name>
tdp agent example <name>

tdp agent plan snapshot
tdp agent plan apply
tdp agent plan check

tdp agent production snapshot
tdp agent production apply
tdp agent production check
tdp agent production request-amendment
tdp agent production submit-completion
tdp agent production report-blocked

tdp agent review request
tdp agent review respond

tdp agent run status
```

The CLI should accept structured JSON or YAML through standard input or a request file and return structured output. JSON is recommended for machine-facing responses; YAML examples may be shown for readability.

### 8.1 Plan snapshot

`plan snapshot` returns a bounded, revisioned view:

```bash
tdp agent plan snapshot --view tree
```

Useful options include:

```bash
tdp agent plan snapshot --root item-backend --depth 2
tdp agent plan snapshot --view ready
tdp agent plan snapshot --view issues
```

The result should include:

- Current plan revision.
- Tree-local item order.
- Stable IDs.
- Dependencies.
- Validation warnings.
- Depth and expansion guidance.
- A dependency-ready view when requested.

### 8.2 Atomic plan apply

`plan apply` performs one atomic transaction against a declared base revision.

Example request:

```json
{
  "base_revision": 12,
  "operations": [
    {
      "op": "add_item",
      "temp_id": "new-api",
      "parent_id": "item-backend",
      "placement": { "after": "item-auth" },
      "item": {
        "title": "Application API",
        "outcome": "Required API behavior is available.",
        "acceptance": ["The producer can verify the required API behavior."]
      }
    },
    {
      "op": "add_dependency",
      "item_id": "item-frontend-forms",
      "depends_on": "new-api"
    }
  ]
}
```

The transaction should either apply completely or not apply at all. Before persistence,
the service compares hard validation errors before and after the candidate mutation
and rejects the transaction when new error-severity issues would be introduced.
Soft-limit warnings may still be introduced. Invalid item payloads (for example
missing or blank `title` on `add_item`) are rejected at the domain layer.

The response returns:

- The new plan revision.
- Assigned stable IDs for temporary IDs.
- A concise changed-subtree view.
- New warnings or validation issues.
- Updated depth and expansion guidance.
- Any newly ready or no-longer-ready items.

Revision conflicts should fail clearly and instruct the agent to request a new snapshot.

### 8.3 Supported plan operations

The minimal operation set should be:

```text
add_item
update_item
move_subtree
supersede_item
remove_item
add_dependency
remove_dependency
replace_dependencies
```

`remove_item` should be restricted to safe draft cases with no active references or review history. Once an item is materially used, `supersede_item` preserves auditability and redirects affected relationships explicitly. `supersede_item` is leaf-only: the target must have no active children.

### 8.4 Tree-local ordering

Agents should not set global sequence numbers. They should express placement relative to siblings.

Supported placement forms:

```json
{ "first_child": true }
{ "last_child": true }
{ "before": "sibling-id" }
{ "after": "sibling-id" }
```

`move_subtree` changes the parent and/or sibling placement of an item while moving all descendants with it.

Example:

```json
{
  "op": "move_subtree",
  "item_id": "item-api",
  "new_parent_id": "item-backend",
  "placement": { "after": "item-auth" }
}
```

The tool maintains an internal sibling order key and renders the plan using depth-first preorder traversal:

```text
parent
  first child
    first child's descendants
  second child
    second child's descendants
next parent
```

This guarantees that direct children remain close to their parent and related subtrees remain together.

A separate global “reorder everything” command is unnecessary and potentially destructive. Relative `move_subtree` operations are more precise, easier for agents to reason about, and naturally preserve tree locality.

### 8.5 Mutation safeguards

The plan tool should reject mutations that would corrupt structural integrity, including:

- Unknown parent or dependency IDs.
- Moving an item below one of its descendants.
- Self-parenting.
- Self-dependency.
- Duplicate dependency edges when normalization is not requested.
- Adding or changing a dependency in a way that creates a dependency cycle.
- Stale base revisions.
- `supersede_item` on an item with active children.
- Missing or blank item titles on `add_item`, `supersede_item`, or `update_item` patches.
- Candidate mutations that introduce new hard deterministic validation errors.

Soft depth or expansion limit violations should return prominent warnings rather than automatically rejecting the operation. They must still be resolved or reported as a blocker before plan acceptance. Pre-existing hard validation issues may remain after a persisted apply; the response reports them without advancing acceptance.

---

## 9. Dependency handling and validation

### 9.1 Dependency readiness

The production tool should derive a ready set from current item dispositions and dependency state.

An item is ready when:

- It is applicable and not terminal.
- Every required dependency is satisfied.
- It is not blocked by an unresolved review finding.

The producer uses two different views:

- The plan tree for scope understanding and coherent batch selection.
- The dependency-ready set for determining what can be processed safely.

Tree order is not execution order.

### 9.2 Dependency checks

Deterministic validation should check:

- Every dependency target exists.
- No item depends on itself.
- Duplicate dependency edges are absent or normalized.
- The dependency graph contains no cycles.
- The validator reports the actual cycle path.
- A ready item has no unresolved required dependency.
- A completed item does not rely on an unresolved or blocked dependency unless an explicit allowed disposition explains it.
- A non-leaf dependency resolves according to its visible applicable-subtree satisfaction state.
- The remaining unresolved items are not in an impossible waiting state.

Example cycle report:

```yaml
issue: dependency_cycle
path:
  - item-a
  - item-b
  - item-c
  - item-a
```

The tool should also detect a dependency deadlock where all remaining applicable items wait on unresolved items and no valid item is ready. A deadlock may be caused by a cycle, blocked dependency, missing disposition, unresolved subtree satisfaction, or inconsistent dependency state. The report should distinguish these causes and explain the blocking chain in agent-readable form.

### 9.3 Hierarchy checks

The hierarchy validator should check:

- Every non-root parent exists.
- No item is its own parent.
- An item has at most one parent.
- The parent-child graph is acyclic.
- Derived depth matches the actual hierarchy.
- Display traversal includes each active item exactly once.

---

## 10. Production model

### 10.1 Agent-selected batches

The producer decides the size and composition of each batch. The orchestrator should not enforce a fixed batch size.

A good batch is normally:

- Coherent in the plan tree.
- Valid according to dependencies.
- Small enough to produce and assess reliably.
- Large enough to make meaningful progress.

A batch may include items from different branches when their dependency and output relationships make that coherent.

### 10.2 Batch loop

```text
Read remaining plan and ready set
        ↓
Select a coherent ready batch
        ↓
Record batch intent
        ↓
Produce partial output
        ↓
Perform semantic self-check and optional deterministic check
        ↓
Record item dispositions and output evidence
        ↓
Optionally request a focused review
        ↓
Continue with the next batch
```

The production loop ends only when:

- Every applicable plan item has an explicit terminal disposition or valid derived terminal satisfaction state, and the output goal is met, or
- Further responsible progress is blocked and the blocker is recorded with evidence.

### 10.3 Production dispositions

Every applicable plan item must eventually receive one terminal disposition or a derived terminal satisfaction state. The producer records explicit dispositions for the items it directly processes. When a non-leaf item has no explicit disposition, the tool may derive its satisfaction from its applicable descendants when that result is unambiguous:

```text
completed
satisfied_without_change
not_applicable
superseded
blocked
```

Suggested meanings:

- `completed`: Production work, reasoning, or output contribution satisfies the item. It does not require a dedicated artifact.
- `satisfied_without_change`: Existing output, analysis, or context already satisfied the item, or an intentional no-op was correct.
- `not_applicable`: The item was valid in the plan but does not apply after production context was resolved; a reason is required.
- `superseded`: Another approved item or revision replaced this item; the replacement reference is required.
- `blocked`: The item cannot be completed because of a recorded unresolved blocker.

No item may disappear silently.

### 10.4 Controlled plan amendment during production

Production may expose a material defect in the approved plan, for example:

- A required capability or branch is missing.
- A planned assumption is false.
- A dependency or boundary is materially wrong.
- New project context makes part of the plan inapplicable.
- The current plan cannot meet the output goal without a structural change.

The producer must not silently rewrite the plan or misuse `not_applicable` or `superseded` to hide a planning defect. It should request an amendment with evidence and the affected plan references.

The amendment path is:

```text
Producer requests plan amendment
        ↓
Orchestrator pauses new production batches
        ↓
Resume the same primary planner session
        ↓
Planner revises the plan
        ↓
Mandatory whole-plan review/revision loop for the new revision
        ↓
Deterministic plan validation
        ↓
Resume the same primary producer session with the amended plan
```

An amendment does not create a new planner or producer. Already valid production evidence remains attached to stable plan items where possible. The amendment process must explicitly reconcile removed, superseded, changed, and newly added items before production continues. Amendment loops and revision cycles are governed by configuration limits.

### 10.5 Generic output evidence and contributions

The output goal is dynamic, so the core should accept generic evidence and optional many-to-many contribution records:

```yaml
batch_result:
  batch_id: batch-07
  plan_items:
    - item-api-analysis
    - item-forms-boundary
  outputs:
    - id: architecture-report
      type: file
      ref: docs/architecture.md
  contributions:
    - item_id: item-api-analysis
      output_refs:
        - architecture-report
      summary: Contributed API constraints and findings.
    - item_id: item-forms-boundary
      output_refs:
        - architecture-report
      summary: Contributed form boundary decisions.
  summary: "..."
  empty_output: false
  goal_assessment: "..."
```

Contribution records are descriptive, not a strict accounting model. Several items may contribute to one output, one item may contribute to several outputs, and an item may be satisfied without an output reference.

On `production apply`, the service resolves each output `ref` against the project workspace, captures `sha256`, `size`, `media_type`, and `captured_at`, and snapshots the file under `artifacts/<snapshot-uuid>/<filename>` in the run store. Evidence IDs are unique across the full `output_evidence` history; revisions must use new IDs. Resume and output validation verify that stored snapshots still match their recorded hashes.

The tool must also support intentional empty output or no git changes:

```yaml
batch_result:
  batch_id: batch-08
  plan_items:
    - item-existing-config
  outputs: []
  contributions: []
  empty_output: true
  empty_output_reason: Existing project output already satisfies this item.
```

Empty output is not an error by itself. It must be explicit, justified, and consistent with the plan item disposition and output goal.

---

## 11. Review records

A review loop should have a stable loop ID, one provider reviewer session ID, and revision-bound findings.

```yaml
review_loop:
  id: review-whole-plan-01
  type: whole_plan
  reviewer_session_id: provider-session-ref
  target_revision: 12
  scope:
    kind: whole_plan
  status: changes_requested
  findings:
    - id: finding-01
      importance: blocking
      target_refs:
        - item-backend
      issue: "..."
      required_change: "..."
      status: unresolved
```

Within the same loop, the reviewer updates the stable finding status after each revision:

```text
unresolved
resolved
superseded
```

A review result uses a small decision vocabulary:

```text
approved
changes_requested
blocked
```

Advisory findings do not prevent approval unless the reviewer explicitly marks them blocking.

---

## 12. Deterministic validation

The primary agents may run checks at any time. The orchestrator runs mandatory checks against the exact revisions approved by the whole-plan and whole-output reviewers.

### 12.1 Plan validation

Required generic checks:

- Plan schema and version are valid.
- Stable IDs are unique.
- Parent references are valid.
- Hierarchy has no cycles.
- Dependency references are valid.
- Dependency graph has no cycles.
- No impossible dependency deadlock remains.
- Tree traversal includes every active item once.
- Soft depth and expansion limits are not exceeded in an approvable plan.
- All required plan fields are present at the intended high level.
- No blocking whole-plan findings remain unresolved.
- Whole-plan approval targets the current plan revision.
- Input, output-goal, configuration, and context digests match the reviewed version.

The validator should avoid extensive content heuristics such as minimum text lengths or domain-specific wording rules.

### 12.2 Output validation

Required generic checks:

- Every applicable plan item has an explicit terminal production disposition or a valid derived terminal satisfaction state.
- Completed and satisfied items do not have unresolved required dependencies.
- Blocked items include blocker evidence.
- Superseded items reference their approved replacements.
- Every recorded batch references valid plan items.
- Output evidence is structurally valid.
- Intentional empty output is explicitly declared and justified.
- Git changes are optional and are not required for acceptance.
- The producer explicitly assessed whether the output goal was met.
- No blocking whole-output findings remain unresolved.
- Whole-output approval targets the current output revision.
- Plan, output, configuration, and context digests remain consistent.

### 12.3 Self-check versus deterministic checks

Agents are expected to perform semantic self-checks during their active step. They may call `plan check` or `production check` themselves before requesting review or submitting a completion claim.

The deterministic checker verifies generic invariants. It does not replace reviewer judgment or the primary agent's semantic responsibility.

---

## 13. Loop limits

Every repeatable loop must have a configurable limit. No loop may run indefinitely.

A practical configuration shape is:

```yaml
limits:
  planning:
    max_items_added: 20
    max_agent_turns: 40

  focused_plan_review:
    max_loops: 5
    max_revision_cycles_per_loop: 3

  whole_plan_review:
    max_revision_cycles: 5

  production:
    max_batches: 50
    max_agent_turns_per_batch: 10

  focused_output_review:
    max_loops: 8
    max_revision_cycles_per_loop: 3

  whole_output_review:
    max_revision_cycles: 5

  amendment:
    max_requests: 3
    max_revision_cycles_per_request: 3

  provider:
    max_retries_per_call: 2
```

The exact defaults may be tuned, but the concepts are required.

Limit exhaustion never means acceptance. The orchestrator determines the terminal outcome from the unresolved cause:

- `rejected` when a complete and assessable candidate still fails the goal or required review after allowed revisions.
- `blocked` when missing information, conflict, unavailable capability, dependency deadlock, or another unresolved condition prevents responsible progress.
- `failed` when the orchestration or provider fails operationally.

---

## 14. Configuration and CLI overrides

YAML is the authoritative configuration format.

Example:

```yaml
version: 1

run:
  input_refs:
    - README.md
    - docs/requirements.md
  output_goal: >
    Produce the requested project output while preserving the declared scope
    and satisfying the approved plan.

planning:
  stop_hint: >
    Stop when each item has one coherent outcome, clear boundaries,
    material dependencies, and acceptance expectations.
  max_depth: 4
  max_expansion_per_item: 7

review:
  focused_plan:
    enabled: true
  focused_output:
    enabled: true

provider:
  name: cursor

observability:
  log_level: normal
  log_format: console
  color: auto
  show_agent_text: true
  show_timestamps: false
  agent_transcript: false

limits:
  planning:
    max_items_added: 20
  whole_plan_review:
    max_revision_cycles: 5
  production:
    max_batches: 50
  amendment:
    max_requests: 3
    max_revision_cycles_per_request: 3
  whole_output_review:
    max_revision_cycles: 5
```

The main CLI uses repeated generic overrides:

```bash
tdp run \
  --config top-down-planning.yaml \
  --set planning.max_depth=5 \
  --set planning.max_expansion_per_item=8 \
  --set limits.production.max_batches=80 \
  --set provider.model=some-model
```

Override semantics:

- Paths use dot notation.
- Values are parsed as YAML values, not always strings.
- Repeated overrides apply in order; later values win.
- Unknown paths fail explicitly rather than creating hidden configuration.
- Override results are materialized into the resolved run configuration. Semantic config digests exclude `observability` and `runtime.runs_dir`; presentation settings live in `invocation.json`.

Precedence:

```text
built-in defaults < YAML configuration < CLI --set overrides < dedicated CLI flags when explicitly supplied
```

Observability and other presentation settings may be set in YAML under `observability` or overridden with dedicated flags (`--log-level`, `--color`, `--timestamps`, `--agent-text`, `--agent-transcript`, `--log-format`). Omitted flags do not override YAML.

Agent thinking/response console output uses `core_tools.observability.AgentTextStreamController`: Cursor `stream-json` text is read from `text` or `message.content`, cumulative chunks are deduplicated, complete sentences are emitted as they arrive, and any trailing fragment flushes before tool calls or turn completion. Empty thinking events are not normalized or printed.

Tool invocations print as `[tool:start]` and `[tool:end]` with a concise summary from the normalized provider event (`summary` field). Cursor native tools are summarized from the nested `tool_call` payload; structured Top Down Planning agent tools summarize from `tool` and `request` (for example `plan_apply @r0 3 ops`). `tool_call` events with `subtype: started` or `completed` reach the console bridge; `tool_result` events and duplicate lifecycle events for the same `call_id` are dropped.

Console output prints `[category]` once per category block (optional `[timestamp]` when `show_timestamps` is enabled). Multi-line messages and consecutive events with the same category omit the prefix on continuation lines but keep category styling until the category changes.

`tdp run` and `tdp resume` treat Ctrl+C as a cooperative cancel: `RunEngine` calls `terminate_all_sessions()`, emits a `session:cancel` observability event, returns without marking the run failed, and the CLI exits with code 130. With `--stream-json`, the final stdout payload includes `"cancelled": true` and `"reason": "cancelled by user"`.

Dedicated operational flags include:

```text
--config
--set
--resume
--stream-json
--runs-dir
--no-color
--log-level
--log-format
--color
--timestamps / --no-timestamps
--agent-text / --no-agent-text
--agent-transcript / --no-agent-transcript
```

---

## 15. Run states and outcomes

Operational state and quality outcome are separate.

```yaml
run_status:
  - running
  - paused
  - completed
  - failed

outcome:
  - accepted
  - rejected
  - blocked
```

### Accepted

The output goal is met, every applicable plan item has an explicit terminal disposition or valid derived satisfaction state, mandatory reviews approved the current revisions, and deterministic checks passed.

### Rejected

A complete and assessable plan or output exists, but it does not satisfy the output goal, required acceptance boundary, or mandatory review after the permitted revisions.

### Blocked

Responsible completion is impossible because of unresolved conflict, inconsistent input or context, missing required information, unavailable capability, an impossible dependency state, a quality-preserving plan that cannot fit the configured constraints, or another recorded blocker.

### Failed

An operational error occurred, such as provider process failure, corrupted state, or an unrecoverable persistence error. Failure is not a quality judgment about the candidate output.

---

## 16. Provider abstraction

Cursor CLI is the default initial provider. The core orchestrator depends on a provider contract with operations such as:

```text
start_primary_session(role, context_manifest)
resume_primary_session(session_id, request)
start_reviewer_session(review_package)
send(session_id, request)
stream_events(session_id)
get_capabilities()
get_session_reference(session_id)
terminate_session(session_id)
terminate_all_sessions()
```

The provider adapter is responsible for:

- Provider-specific command construction.
- Session identifiers and resume behavior.
- Stream parsing and normalization.
- Model and capability resolution.
- Working-directory behavior.
- Native project context integration.
- Provider-specific rules, skills, and instruction discovery.
- Terminating in-flight provider subprocesses when orchestration no longer needs them. `terminate_all_sessions()` is called by the run engine after each phase step and on user cancel (Ctrl+C); the Cursor adapter kills the active CLI process tree so background agent subprocesses are not left running.

The provider should run in the project workspace so existing project context remains naturally available. Explicit context configured by the Top Down Planning tool supplements provider-native context rather than replacing it.

Reviewer packages should use explicit references and digests so a fresh reviewer receives clear evidence without inheriting unrelated session history.

---

## 17. Recommended implementation architecture

The implementation should use a small layered architecture so orchestration rules remain testable and provider-independent.

### 17.1 Core domain

Pure models and rules for:

- Run and phase state.
- Plan tree and stable item identities.
- Dependency graph and readiness.
- Review loops and revision-bound findings.
- Production batches, dispositions, contributions, and blockers.
- Amendment requests and reconciliation.
- Validation results and final outcomes.

This layer should not know about Cursor, subprocesses, CLI parsing, or file layout.

### 17.2 Application orchestrator

The orchestrator owns lifecycle transitions:

```text
plan
→ review plan
→ validate plan
→ produce batches
→ amend plan when materially required
→ review output
→ validate output
→ resolve outcome
```

It enforces session ownership, role guardrails, loop limits, approval-to-revision binding, and final outcome authority.

### 17.3 Agent tool service

The structured tool service exposes atomic domain operations to agents. It performs schema validation, optimistic revision checks, role checks, and concise response shaping before calling the domain layer.

### 17.4 Provider adapter

The provider adapter implements session start/resume, message delivery, event streaming, capability discovery, and provider-native context behavior. Cursor CLI is the first adapter.

### 17.5 Persistence adapter

Persistence stores canonical snapshots, events, review records, and provider session references behind an interface. The first implementation may use files while preserving the option to move to another backend.

### 17.6 Implementation sequence

A practical delivery order is:

1. Plan tree, atomic mutations, dependency DAG, and validators.
2. Persistent planner and mandatory whole-plan review.
3. Persistent producer, agent-selected batches, dispositions, and flexible output contributions.
4. Mandatory whole-output review and orchestrator-owned acceptance.
5. Controlled plan amendment and reconciliation.
6. Resume, provider abstraction, and durable session references.
7. Optional focused reviews, extensions, and richer diagnostics.

Each stage should preserve the final lifecycle invariants. Optional features should not delay a working end-to-end core.

---

## 18. Persistence and resumability

Agents never edit persistence files directly. All state changes go through the structured tool.

A minimal run store may contain:

```text
runs/<run-id>/
  resolved-config.yaml
  invocation.json
  run.json
  plan.json
  production.json
  capabilities/
    <capability-id>.json
  artifacts/
    <snapshot-uuid>/
      <filename>
  reviews/
    <review-loop-id>.json
  events.jsonl
```

Responsibilities:

- `resolved-config.yaml`: fully resolved configuration after overrides (includes observability for operator visibility).
- `invocation.json`: CLI invocation metadata for the latest `run`/`resume` process (observability snapshot, runs-dir resolution, `stream_json`, `until`). Not included in semantic config digests.
- `run.json`: run status, outcome, phase, digests, and provider session references.
- `plan.json`: canonical current plan and revision.
- `production.json`: batches, item dispositions, output evidence, and output revision.
- `capabilities/`: session capability token hashes, session/loop binding, and revocation state.
- `artifacts/`: immutable content snapshots for output evidence hashes (UUID paths).
- `reviews/`: review-loop records and stable findings.
- `events.jsonl`: append-only audit trail; commit events carry `txn_id` for idempotent recovery.

Multi-file mutations use `RunStore.commit()` with a journaled staging directory: per-file backups before replace, per-file staged-content digests recorded in the journal, replacement recorded in the journal only after `Path.replace()` succeeds, digest verification before completing recovery, rollback of partial or falsely journaled replaces, completion of pending event appends when replacements finished before a crash, and a per-run OS file lock (`.commit.lock`) around recovery, revision checks, replacements, event appends, commits, and commit-managed reads (`load_run`, `load_plan`, `load_production`, `load_events`, `load_review`, `list_reviews`). `create_run` stages under `.creating-<run-id>/` and renames atomically on success.

Storage should be behind an interface so the implementation may later move from files to another backend without changing orchestration semantics.

---

## 19. Core utilities and project-specific extensions

The reusable core should contain:

- Lifecycle state machine.
- Session ownership and resume logic.
- Review-loop management.
- Controlled plan amendment and reconciliation.
- Provider interfaces.
- Configuration loading and generic overrides.
- Structured agent tool protocol.
- Plan tree and dependency graph utilities.
- Generic deterministic validators.
- Revision and digest binding.
- Atomic persistence and audit events.
- Outcome resolution.

Project-specific extensions may supply:

- Additional context collectors.
- Prompt additions.
- Domain-specific plan fields.
- Artifact inspectors.
- Extra deterministic checks.
- Domain acceptance policies.
- Provider-specific helper behavior.

Project-specific logic must not be embedded into the orchestration core. This separation allows reusable utilities to be moved into a shared `core_tools` project or folder later.

---

## 20. Recommended command surface

### User-facing orchestration commands

```bash
tdp run --config top-down-planning.yaml
tdp run --config top-down-planning.yaml --set path=value
tdp resume --run <run-id>
tdp status --run <run-id>
tdp inspect --run <run-id> --view tree
tdp validate --run <run-id>
```

### Agent-facing structured commands

```bash
tdp agent help
tdp agent readme
tdp agent schema plan-transaction
tdp agent example expand-branch

tdp agent plan snapshot --view tree
tdp agent plan snapshot --view ready
tdp agent plan apply --request <file-or-stdin>
tdp agent plan check

tdp agent production snapshot
tdp agent production apply --request <file-or-stdin>
tdp agent production check
tdp agent production request-amendment --request <file-or-stdin>
tdp agent production submit-completion --request <file-or-stdin>
tdp agent production report-blocked --request <file-or-stdin>

tdp agent review request --request <file-or-stdin>
tdp agent review respond --request <file-or-stdin>

tdp agent run status
```

The agent-facing protocol should return concise machine-readable responses plus actionable warnings. The CLI should expose its agent README, schemas, examples, and usage hints so agents can discover the correct structured operation without reading implementation files.

Primary agents submit completion claims, blockers, and amendment requests. They do not write `accepted`, `rejected`, or `blocked` as the authoritative final run outcome. The orchestrator resolves and persists the outcome after mandatory review, deterministic validation, and limit handling.

---

## 21. Final acceptance invariant

Only the orchestrator may report `accepted`, and only when all of the following are true:

```yaml
acceptance_invariant:
  plan:
    whole_plan_review_approved_current_revision: true
    deterministic_plan_validation_passed: true

  production:
    all_applicable_items_have_terminal_or_derived_satisfaction: true
    output_goal_explicitly_assessed_as_met: true

  output:
    whole_output_review_approved_current_revision: true
    deterministic_output_validation_passed: true

  findings:
    unresolved_blocking_findings: 0
```

The producer may submit a completion claim only after every applicable plan item is processed or has a valid derived satisfaction state and the output goal is assessed as met. The orchestrator remains the final acceptance authority.

An intentional empty output or no-change result can be accepted when it is explicitly recorded, justified, reviewed, and consistent with the output goal.

---

## 22. Final tool shape

The final Top Down Planning tool consists of:

1. A YAML-configured orchestration CLI with generic `--set path=value` overrides.
2. One persistent primary planner session.
3. Optional focused plan review/revision loops.
4. One mandatory whole-plan review/revision loop.
5. Minimal deterministic plan validation, including hierarchy and dependency-cycle checks.
6. One persistent primary producer session.
7. Agent-selected, dependency-valid production batches until the complete applicable plan is processed.
8. Flexible many-to-many relationships between plan items and produced outputs, including valid no-output results.
9. A controlled amendment path that resumes the same planner and producer when production exposes a material plan defect.
10. Optional focused output review/revision loops.
11. One mandatory whole-output review/revision loop.
12. Minimal deterministic output validation.
13. Orchestrator-owned accepted, rejected, or blocked outcomes, separate from operational failure.
14. A unified structured agent tool based on revisioned snapshots and atomic transactions.
15. Stable item IDs, relative subtree placement, and automatically derived tree-local display order.
16. Soft decomposition limits surfaced proactively to the planner.
17. Configurable limits for every repeatable loop, including amendments.
18. Simple operation-level role guardrails.
19. A provider abstraction with Cursor CLI as the initial adapter and native project context preserved.
20. A layered implementation architecture and strict separation between reusable core utilities and project-specific extensions.

This shape keeps the workflow simple while preserving continuity, independent review, controlled decomposition, reliable production completion, resumability, and generic acceptance across dynamic output goals.
