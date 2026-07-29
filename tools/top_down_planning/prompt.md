Design and implement a generic `top_down_planning` tool.

## Objective

The tool receives:

1. one Markdown file containing a task, idea, proposal, or initial requirements;
2. a short prompt describing the expected final output.

It uses an agent loop to progressively analyze and decompose the input into a sufficiently detailed plan.

Example:

```bash
top-down-planning \
  --input ./idea.md \
  --output-goal "Produce an implementation plan with actionable development tasks" \
  --output ./planning-output
```

The tool only performs planning. It must not execute the resulting tasks.

## Planning strategy

Use top-down decomposition.

1. Read and understand the complete input document.
2. Establish the major planning areas first.
3. Expand those areas into smaller items.
4. Continue expanding incomplete items.
5. Stop when all relevant leaf items are sufficiently detailed for the requested output goal.

Prefer breadth-first planning (enforced by the orchestrator):

* create a coherent high-level plan before producing low-level details;
* only items at the shallowest incomplete depth are eligible each iteration;
* avoid fully detailing one branch while other major branches remain undefined.

This is not bottom-up planning. The tool must not generate disconnected low-level tasks and group them afterward.

## Inputs

### Input Markdown

The tool accepts exactly one primary Markdown input file.

The document may contain:

* an idea;
* a task;
* a proposal;
* requirements;
* constraints;
* background information;
* open questions;
* expected behavior.

The tool should treat the whole document as the source planning context.

### Output goal

The tool accepts a short natural-language prompt describing the desired final result.

Examples:

```text
Produce an actionable implementation plan.
```

```text
Produce a migration plan with phases, dependencies, and acceptance criteria.
```

```text
Break this proposal into reviewable development tasks.
```

```text
Produce a concise workshop preparation plan.
```

The output goal affects:

* what planning dimensions are needed;
* how far decomposition should continue;
* what information each final item must contain;
* how the final result is rendered.

Do not hardcode the tool specifically for software implementation plans.

## Structured planning state

Maintain the plan as one structured planning graph or tree.

Do not create a separate Markdown file for every item.

Use a flat collection with stable IDs and parent references so the tool can perform deterministic traversal and updates.

Suggested structure:

```yaml
schema_version: 2

source:
  input_file: ./idea.md
  output_goal: Produce an actionable implementation plan.

plan:
  - id: item-001
    parent_id: null
    title: Understand and plan the requested work
    objective: Transform the input into the requested final plan
    depth: 0
    order: 1

    decomposition_status: needs_expansion
    readiness_status: pending

    dependencies: []
    expected_outputs: []
    acceptance_criteria: []
    notes: []
    risks: []
    open_questions: []

result:
  status: planning
  summary: null
```

The initial root wording is bootstrap state only. The root's first decomposition
operation must replace its `title` and `objective` with agent-generated values specific
to the input document and output goal, whether it expands or reaches a terminal status.

Supported `decomposition_status` values:

* `needs_expansion`
* `expanded`
* `actionable`
* `blocked`
* `out_of_scope`

Suggested `readiness_status` values:

* `pending`
* `ready`
* `blocked`

Keep decomposition state separate from future execution state.

The structure must support:

* stable item identity;
* parent-child relationships;
* breadth-first traversal;
* deterministic ordering;
* dependencies;
* incremental expansion;
* validation;
* resuming interrupted planning;
* rendering hierarchical and flat final plans.

The tool should own ID generation. The agent should not generate canonical IDs.

## Planning loop

Use a loop similar to:

```text
load the input Markdown
initialize the planning state

while expandable items remain:
    expose only the shallowest incomplete items as eligible
    prepare the relevant planning context (including a plan-overview file reference)
    ask the agent to assess or expand those items
    parse the structured operations
    validate all proposed operations
    apply valid operations atomically
    persist the updated planning state

validate overall plan completeness
render the final output
```

The selected batch should normally contain items with:

```text
decomposition_status = needs_expansion
```

across independent branches, preferring shallower items first.

Each planning iteration runs **one** agent session. The agent chooses a coherent batch
from the eligible inventory via `planning-plan-tool select-batch` before recording
operations. Each iteration counts toward `limits.max_iterations`.

## Agent responsibilities

For every selected item, the agent must choose exactly one result:

1. expand it into child items (the parent becomes `expanded`);
2. mark the item as actionable (leaf only);
3. mark it blocked;
4. mark it out of scope.

### Expand

Use when the item still contains multiple meaningful pieces of work or unresolved planning concerns.
Expanding marks the parent `expanded` and creates child items for further decomposition.

### Actionable

Use when the item is a leaf detailed enough for the output goal.

For example, when the output goal asks for an implementation plan, an actionable item should normally include:

* a clear objective;
* bounded scope;
* expected outputs;
* relevant dependencies;
* acceptance criteria;
* enough context for an execution agent to begin;
* no unresolved decision that would fundamentally change the work.

The exact actionability criteria should be inferred from the output goal rather than being completely hardcoded.

### Blocked

Use when decomposition requires information that is missing from the input and cannot safely be inferred.

Blocked items must include:

* the missing information;
* why it matters;
* a concrete open question.

### Out of scope

Use when the item does not contribute to the requested output goal.

It must include a reason.

## Agent response contract

During decomposition, the agent records structured operations through the bundled
`planning-plan-tool` CLI. It must **not** return planning JSON in chat and must **not**
edit `.planning-output/plan.yaml` directly.

Each batch session receives scoped environment variables:

* `PLANNING_TOOL_TXN_FILE` — path to `{NNN}-transaction.json`
* `PLANNING_TOOL_ELIGIBLE_IDS` — comma-separated eligible node ids
* `PLANNING_TOOL_PATCHABLE_IDS` — comma-separated related node ids eligible for `update_item`
* `PLANNING_TOOL_PLAN_FILE` — read-only path to canonical `plan.yaml`
* `PLANNING_TOOL_COMMAND` — resolved shell command for the CLI

Workflow per batch:

1. `planning-plan-tool select-batch --node-id <id> [--purpose "..."]`
2. `planning-plan-tool show-context` (optional)
3. `planning-plan-tool status` (optional)
4. `planning-plan-tool record-operation --json '<operation>'` once per selected item
5. `planning-plan-tool record-update --json '<update_item>'` zero or more times for patchable related items
6. `planning-plan-tool finalize`

The orchestrator loads the finalized transaction, validates the iteration atomically, assigns
IDs/depth/order, and persists the updated state to `plan.yaml`. Successful batches also
write matching `{NNN}-response.json` and `{NNN}-validation.json` audit files for resume
recovery (replay requires sibling validation with `"errors": []`).

Example operation payload for `record-operation`:

```json
{
  "type": "expand",
  "node_id": "item-001",
  "reason": "The root contains multiple independent planning areas.",
  "title": "Design and implement the top-down planning tool",
  "objective": "Produce a generic planning tool that satisfies the requested contracts.",
  "children": [
    {
      "title": "Define the planning state model",
      "objective": "Define the canonical structure used by the planning loop.",
      "dependencies": [],
      "expected_outputs": [
        "Typed planning-state schema"
      ],
      "acceptance_criteria": [
        "The schema supports stable parent-child relationships.",
        "The schema can be validated deterministically."
      ]
    }
  ]
}
```

Supported operation types:

* `expand`
* `mark_actionable`
* `mark_blocked`
* `mark_out_of_scope`
* `update_item` (optional cross-item patch for related existing nodes)

`update_item` is recorded through `record-update`, not `record-operation`. Omitted fields
preserve the current value; an empty list clears a list field. Related batches whose write
scopes overlap are serialized across iterations so later agents consume the persisted plan state.

## Validation

Validate every finalized transaction before modifying the planning state.

Validation must ensure:

* referenced item IDs exist;
* only `needs_expansion` items are expanded;
* `mark_actionable` applies only to leaves;
* expanded nodes have children and are not render deliverables;
* an item cannot be expanded and marked actionable in the same operation set;
* children have meaningful titles and objectives;
* duplicate siblings are rejected or explicitly merged;
* cycles cannot be created;
* parent and depth values are tool-controlled;
* ordering remains deterministic;
* blocked items contain a reason and open question;
* out-of-scope items contain a reason;
* actionable items satisfy the minimum criteria derived from the full resolved output goal;
* limits are respected;
* `update_item` patches target only patchable related nodes, not assigned items;
* cross-item updates require a reason and at least one changed field;
* omitted patch fields preserve the current value and empty lists clear list fields;
* only one planning iteration mutates the plan at a time.

Apply each response atomically.

If any operation is invalid:

1. reject the complete operation batch;
2. provide concise validation errors to the agent;
3. retry within the configured retry limit.

Do not partially apply an invalid response.

## Context supplied to the agent

The agent should receive:

* the output goal;
* relevant content from the input Markdown;
* the selected planning items;
* their ancestors;
* their direct siblings;
* a concise summary of other established branches;
* validation feedback from the previous attempt, when applicable.

Do not continuously resend an unbounded conversation history.

For the first version, sending the complete input Markdown may be acceptable. Keep the context-building layer replaceable so larger input handling can be improved later.

## Stopping rules

Planning completes when:

* no items remain with `needs_expansion`;
* internal nodes that were decomposed are `expanded`;
* all relevant leaves are `actionable`, `blocked`, or `out_of_scope`;
* the overall plan satisfies the output goal;
* dependencies are valid;
* no unresolved structural gaps remain.

Do not stop only because a maximum depth was reached.

Use configurable safety limits:

* maximum iterations;
* maximum validation retries;
* session timeout;
* parse error threshold.

When a limit is reached, preserve the partial plan and return an explicit incomplete result.

Final statuses:

* `complete`
* `incomplete_blocked`
* `incomplete_limit_reached`
* `failed`

## Outputs

The tool separates **user-facing deliverables** from **internal resumable state**.

Suggested layout:

```text
planning-output/
├── implementation-plan.md          # example final deliverable
└── planning-output/
    └── .planning-output/
    ├── plan.yaml
    ├── run-state.json
    ├── review-state.json
    └── iterations/
        ├── 001-request.json
        ├── 001-transaction.json
        ├── 001-response.json
        └── render/
            ├── render-state.json
            ├── scaffold/
            ├── batches/
            └── reviews/
```

`--output` holds internal resumable state under `.planning-output/`. Final deliverables
are written directly to workspace destination paths by render author agents.

Deliverables are produced by a **sequential cumulative render pipeline** after decomposition
completes (and after review/confirmation when review is enabled). Rendering is a separate
lifecycle from planning:

1. Run a scaffold session that establishes destination paths, structure, and conventions.
2. For each render iteration: agent selects a batch via `planning-render-tool select-batch`,
   then author session → batch review → optional bounded revision.
3. Run whole-output semantic review (`rendered_output_review`) with optional bounded final revision.

Processed-batch history in `render-state.json` records completed batches for review
digests and resume. The output goal defines format and intent; an optional
`## Output artifacts` section is sample layout only.
Review prompts embed a human-readable render brief derived from `plan.yaml`.

Deliverables must be generated fresh from the confirmed plan. Zero workspace deliverables
is invalid once rendering starts unless the author sessions fail validation.

Render agents must not copy or restore pre-existing files from git history or from paths
cited in the output goal. They must not modify canonical state under the configured run
output directory (`.planning-output/` under `--output`). The tool backs up and restores
`plan.yaml` if a session corrupts it.

Workspace change detection ignores paths matched by `render.artifact_ignore_patterns`
(gitignore-style globs) and always excludes canonical planning state under the configured
run output directory. The run `--output` directory must lie inside `--workspace`. Only
UTF-8 text deliverables participate in artifact tracking, digests, and review.

Render failures (author validation exhaustion, blocked batch review, blocked final review)
surface as explicit errors; there is no deterministic fallback deliverable.

### `plan.yaml`

The canonical structured planning state (internal).

It should contain:

* source input metadata;
* a compact output-goal label and optional `output_goal_file` path;
* optional stop-hint label and optional `stop_hint_file` path;
* all planning items;
* relationships;
* statuses;
* dependencies;
* final result metadata.

When the output goal or stop hint comes from a file, `plan.yaml` stores a short
label plus the source file path. Full goal/hint text is loaded at runtime from that
file. Resume compatibility still uses SHA-256 digests of the resolved file contents.

### Goal-driven deliverables

Render author agents produce readable workspace files when the output goal calls for
them. Typical content preserves:

* hierarchy;
* item ordering;
* expected outputs;
* dependencies;
* acceptance criteria;
* blocked items;
* open questions.

Avoid exposing unnecessary internal orchestration fields unless the output goal requires them.

### `run-state.json`

Contains resumable runtime information such as:

* current iteration;
* active status;
* configured limits;
* retry counts;
* input digest;
* output-goal digest;
* generated artifact paths;
* last successful update.

The input digest should prevent accidentally resuming a state against a different input document.

Resume should detect when `plan.yaml` was reset but `run-state.json` still shows prior
progress. In that case, rebuild the plan by replaying stored `iterations/*-response.json`
audit files whose sibling `*-validation.json` records `"errors": []` before continuing.
During render, back up and restore `plan.yaml` if the render agent modifies canonical state.

## Final plan views

Output-goal text may ask render agents to include logical views such as:

### Hierarchical view

Shows the complete top-down reasoning structure.

```text
1. Major area
   1.1 Sub-area
       1.1.1 Actionable item
```

### Final actionable list

Shows only actionable leaf items in a sensible order.

For implementation-oriented output goals, this should be dependency-safe where possible.

The tool does not assemble these views deterministically. Render agents decide
structure and format from the output goal and intermediate artifacts.

## CLI

Provide a simple interface:

```bash
top-down-planning \
  --input ./idea.md \
  --output-goal "Produce an actionable implementation plan" \
  --output ./planning-output
```

Suggested options:

```text
--input
--output-goal
--output-goal-file
--output
--max-iterations
--max-retries
--resume
--stream-json
```

`--output-goal` may be a short inline prompt. `--output-goal-file` may supply a longer
Markdown or text specification. An optional `## Output artifacts` section is sample
layout only.

## Streaming

When `--stream-json` is enabled, emit one valid JSON object per line.

Suggested events:

```json
{"type":"planning.started","input":"./idea.md"}
{"type":"iteration.started","iteration":1,"eligible_items":["item-001"]}
{"type":"item.expanded","item_id":"item-001","children_count":4}
{"type":"item.actionable","item_id":"item-003"}
{"type":"validation.failed","iteration":2,"errors":["Duplicate child title"]}
{"type":"iteration.retrying","iteration":2,"attempt":2}
{"type":"planning.completed","status":"complete","items":18,"actionable_items":11,"artifacts":["./planning-output/implementation-plan.md"]}
{"type":"render.scaffold.completed","artifacts":["implementation-plan.md"]}
{"type":"render.batch.started","batch_index":0,"eligible_items":["item-002","item-003"]}
{"type":"render.batch.completed","batch_index":0,"selected_items":["item-002","item-003"],"artifacts":["implementation-plan.md"]}
{"type":"render.batch.review.started","batch_index":0,"cycle":0}
{"type":"render.batch.review.completed","batch_index":0,"decision":"approve","cycle":0}
{"type":"render.final_review.started","cycle":0}
{"type":"render.final_review.completed","decision":"approve","cycle":0}
{"type":"render.completed","artifacts":["./implementation-plan.md"]}
```

Requirements:

* stdout contains only stream JSON when enabled;
* each line is independently valid JSON;
* human-readable logs go to stderr;
* event types and fields are documented;
* partial agent text must not be mixed into the event stream.

## Architecture

Separate these concerns:

* CLI and configuration;
* Markdown input loading;
* planning-state models;
* breadth-first item selection (shallowest incomplete depth only);
* agent prompt construction;
* agent invocation;
* response parsing;
* operation validation;
* atomic state updates;
* persistence and resume;
* final rendering;
* stream events and logging.

Use typed models for all persisted state and agent responses.

Use a replaceable agent adapter so the planning engine is not tightly coupled to one provider or CLI.

## Important constraints

* Accept one primary Markdown input file.
* Accept one output goal via inline prompt or goal file.
* Maintain one structured plan state.
* Do not create a Markdown file for every item.
* During planning, the agent only proposes structured operations; the tool validates and applies them.
* During render, the agent writes deliverables wherever the output goal calls for them and must not modify `.planning-output/`.
* Prefer breadth-first top-down decomposition (orchestrator-enforced shallowest depth).
* Do not execute the generated plan.
* Keep the tool generic across domains.
* Make interrupted runs resumable.
* Make completed runs auditable.
* Preserve partial results on failure or limit exhaustion.

## Tests

Add focused unit tests for:

* input loading;
* root-plan initialization;
* breadth-first item selection (shallowest incomplete depth only);
* deterministic ordering;
* expansion;
* actionable-item validation;
* blocked and out-of-scope states;
* duplicate detection;
* cycle prevention;
* atomic rejection of invalid operations;
* maximum iteration, depth, and item limits;
* retry behavior;
* persistence;
* resume compatibility;
* input-digest mismatch;
* final status calculation;
* Markdown rendering;
* JSONL stream validity.

Before implementation, briefly document:

1. the canonical planning-state schema;
2. the shallowest-depth eligibility and topological ordering rules;
3. the agent operation schema;
4. actionability and stopping decisions;
5. persistence and resume behavior.

Then implement the smallest coherent version without adding unrelated framework abstractions.
