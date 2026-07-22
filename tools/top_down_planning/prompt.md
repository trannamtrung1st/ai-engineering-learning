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

Prefer breadth-first planning:

* create a coherent high-level plan before producing low-level details;
* expand items at the shallowest incomplete level first;
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
schema_version: 1

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

Supported `decomposition_status` values:

* `needs_expansion`
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
    select the shallowest incomplete items
    prepare the relevant planning context
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

Batch size and concurrent batch count should be configurable. Each launched batch
counts as one iteration. Up to the configured concurrency limit, independent batches
may run in parallel per wave and are merged atomically after validation.

## Agent responsibilities

For every selected item, the agent must choose exactly one result:

1. mark the item as actionable;
2. expand it into child items;
3. mark it blocked;
4. mark it out of scope.

### Expand

Use when the item still contains multiple meaningful pieces of work or unresolved planning concerns.

### Actionable

Use when the item is detailed enough for the output goal.

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
* `PLANNING_TOOL_SELECTED_IDS` — comma-separated selected node ids
* `PLANNING_TOOL_PLAN_FILE` — read-only path to canonical `plan.yaml`
* `PLANNING_TOOL_COMMAND` — resolved shell command for the CLI

Workflow per batch:

1. `planning-plan-tool show-context` (optional)
2. `planning-plan-tool status` (optional)
3. `planning-plan-tool record-operation --json '<operation>'` once per selected item
4. `planning-plan-tool set-assessment [--plan-complete|--no-plan-complete] --summary "..."`
5. `planning-plan-tool finalize`

The orchestrator loads the finalized transaction, validates the wave atomically, assigns
IDs/depth/order, and persists the updated state to `plan.yaml`. Successful batches also
write matching `{NNN}-response.json` audit files for resume recovery.

Example operation payload for `record-operation`:

```json
{
  "type": "expand",
  "node_id": "item-001",
  "reason": "The root contains multiple independent planning areas.",
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

Keep the initial version small. Only include `update_item` if it is necessary for correcting or enriching existing items.

## Validation

Validate every finalized transaction before modifying the planning state.

Validation must ensure:

* referenced item IDs exist;
* only expandable items are expanded;
* an item cannot be expanded and marked actionable in the same operation set;
* children have meaningful titles and objectives;
* duplicate siblings are rejected or explicitly merged;
* cycles cannot be created;
* parent and depth values are tool-controlled;
* ordering remains deterministic;
* blocked items contain a reason and open question;
* out-of-scope items contain a reason;
* actionable items satisfy the minimum criteria derived from the output goal;
* limits are respected.

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
* all relevant leaves are `actionable`, `blocked`, or `out_of_scope`;
* the overall plan satisfies the output goal;
* dependencies are valid;
* no unresolved structural gaps remain.

Do not stop only because a maximum depth was reached.

Use configurable safety limits:

* maximum iterations;
* maximum depth;
* maximum total items;
* maximum children per expansion;
* maximum batch size;
* maximum concurrent batches;
* maximum validation retries.

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
├── implementation-plan.md          # example deliverable (path chosen by output goal)
└── .planning-output/
    ├── plan.yaml
    ├── run-state.json
    └── iterations/
        ├── 001-request.json
        ├── 001-transaction.json
        ├── 001-response.json
        ├── render-response.json
        └── render-request-prompt.md
```

`--output` holds internal resumable state under `.planning-output/`. Deliverables may
be written anywhere in the workspace according to the output goal.

Deliverables are produced by a final render phase after decomposition completes.
The render agent runs in write mode, transforms the completed breakdown into
deliverables, and writes one or more files under the deliverable directory (typically
`--output`, excluding `.planning-output/`). Format and schema come from the output
goal; scope and item coverage come from the breakdown.

Before render, the tool writes `render-brief.md` from `plan.yaml`. That brief lists
every actionable leaf unit with objectives, dependencies, expected outputs, and
acceptance criteria. The render prompt treats the breakdown as the authoritative
scope contract and the output goal as the authoritative format contract.

The tool discovers newly written or updated files anywhere in the workspace (excluding
`.planning-output/` and common VCS/dependency directories). After discovery, it
validates that every breakdown title appears in the deliverables. Missing coverage
triggers a render retry with validation feedback. If the render session fails or
coverage remains incomplete after retries, a deterministic fallback artifact is
generated internally.

The output goal may define an **Output artifacts** section with suggested filenames
and formats. Paths mentioned only as examples inside the output goal must not be
treated as copy sources; deliverables must be generated fresh from the breakdown.

The render agent must not copy or restore pre-existing files from git history or
from paths cited in the output goal. It must not modify canonical state under
`.planning-output/`. The tool backs up and restores `plan.yaml` if render corrupts it.

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

Readable final output files rendered according to the output goal while preserving:

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
progress. In that case, rebuild the plan by replaying stored
`iterations/*-response.json` audit files before continuing. During render, back up and
restore `plan.yaml` if the render agent modifies canonical state.

## Final plan views

The rendered result should include two logical views when applicable.

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

Do not assume every output goal requires an execution-task list. The renderer may adapt its terminology and presentation based on the requested output.

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
--max-depth
--max-items
--batch-size
--concurrent-batches
--max-retries
--resume
--stream-json
```

`--output-goal` may be a short inline prompt. `--output-goal-file` may supply a longer
Markdown or text specification, including an **Output artifacts** section.

## Streaming

When `--stream-json` is enabled, emit one valid JSON object per line.

Suggested events:

```json
{"type":"planning.started","input":"./idea.md","concurrent_batches":3}
{"type":"wave.started","wave_size":2,"iterations":[1,2]}
{"type":"iteration.started","iteration":1,"batch_index":0,"batch_count":2,"selected_items":["item-001"]}
{"type":"item.expanded","item_id":"item-001","children_count":4}
{"type":"item.actionable","item_id":"item-003"}
{"type":"validation.failed","iteration":2,"errors":["Duplicate child title"]}
{"type":"iteration.retrying","iteration":2,"attempt":2}
{"type":"planning.completed","status":"complete","items":18,"actionable_items":11,"artifacts":["./planning-output/implementation-plan.md"]}
{"type":"render.started"}
{"type":"render.completed","artifacts":["./planning-output/implementation-plan.md"]}
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
* breadth-first item selection;
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
* Prefer breadth-first top-down decomposition.
* Do not execute the generated plan.
* Keep the tool generic across domains.
* Make interrupted runs resumable.
* Make completed runs auditable.
* Preserve partial results on failure or limit exhaustion.

## Tests

Add focused unit tests for:

* input loading;
* root-plan initialization;
* breadth-first item selection;
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
2. the breadth-first selection algorithm;
3. the agent operation schema;
4. actionability and stopping decisions;
5. persistence and resume behavior.

Then implement the smallest coherent version without adding unrelated framework abstractions.
