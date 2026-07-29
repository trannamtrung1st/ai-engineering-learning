# Top-Down Planning Tool

Generic CLI that progressively decomposes one Markdown input into a structured plan using Cursor Agent CLI in agent mode for decomposition and sequential cumulative render authoring.

## Install

```bash
cd tools/top_down_planning
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## CLI discovery

Inspect usage, contracts, and minimal examples without reading repository docs:

```bash
top-down-planning usage
top-down-planning schema list
top-down-planning schema show operation --format json
top-down-planning example list
top-down-planning example show plan --format yaml
```

Helper CLIs also expose offline discovery:

```bash
planning-plan-tool usage
planning-plan-tool schema --target operation
planning-plan-tool example --type mark_actionable
planning-plan-tool validate --json '{"type":"mark_actionable","node_id":"item-002"}'

planning-review-tool usage --stage specialist_review
planning-review-tool schema --stage specialist_review
planning-review-tool example --stage specialist_review
```

## Usage

Using a YAML config file (recommended for repeatable runs):

```bash
top-down-planning --config ./examples/planning.config.yaml
```

CLI flags override values from the config file. Paths in the config file are resolved
relative to `workspace` (or the config file's directory when `workspace` is `.` or omitted),
unless absolute.

Or pass options directly:

```bash
top-down-planning \
  --input ./examples/idea.md \
  --output-goal-file ./examples/output-goal.md \
  --output ./planning-output
```

Or pass a short inline goal:

```bash
top-down-planning \
  --input ./examples/idea.md \
  --output-goal "Produce an actionable implementation plan" \
  --output ./planning-output
```

The explicit `run` subcommand is also supported:

```bash
top-down-planning run --input ./examples/idea.md ...
```

Resume an interrupted run:

```bash
top-down-planning run \
  --input ./examples/idea.md \
  --output-goal "Produce an actionable implementation plan" \
  --output ./planning-output \
  --resume
```

Stream machine-readable events to stdout:

```bash
top-down-planning run \
  --input ./examples/idea.md \
  --output-goal "Produce a migration plan" \
  --output ./planning-output \
  --stream-json
```

Human-readable logs and agent progress go to stderr when `--stream-json` is enabled.

### Desktop notifications

Terminal outcomes (`complete`, incomplete, paused, failed) can emit native desktop notifications.

- **Default:** enabled on desktop sessions; disabled when `CI=true` or on headless Linux
- **CLI:** `--notify` / `--no-notify`
- **Env:** `PLANNING_TOOL_NOTIFY=true|false`
- **Config:** `notify: true|false`

Iteration progress is not notified. `--stream-json` stdout remains machine-readable only.

### Model selection

By default the tool uses Cursor model `composer-2.5`. Override with `--model` or `PLANNING_TOOL_MODEL`:

- **Default:** `composer-2.5` (`DEFAULT_CURSOR_MODEL` in `models.py`)
- **Override:** `--model <slug>` or env var `PLANNING_TOOL_MODEL`
- **Precedence:** `agent_context.<phase>.model` → `agent_context.default.model` → CLI `--model` → `PLANNING_TOOL_MODEL` → package default

```bash
top-down-planning \
  --input ./examples/idea.md \
  --output-goal "Produce an actionable implementation plan" \
  --output ./planning-output \
  --model composer-2.5
```

## Outputs

The tool separates **user-facing deliverables** from **internal resumable state**.

`--output` stores resumable planning state under `.planning-output/`. Final
deliverables are written directly to workspace paths established by scaffold and batch
author agents from the output goal. They are not stored under `--output`.

Example layout:

```text
workspace/
├── implementation-plan.md          # example final deliverable
├── plans/my-feature/               # example multi-file deliverable tree
│   ├── overview.md
│   ├── phase-1.md
│   └── phase-2.md
└── planning-output/
    └── .planning-output/
        ├── plan.yaml
        ├── run-state.json
        ├── review-state.json
        └── render/
            ├── render-state.json
            ├── scaffold/
            ├── batches/
            └── reviews/
```

Goal-driven deliverables are written only when planning finishes with status `complete`
and review status `confirmed` (when review is enabled). Rendering is a separate lifecycle
from planning: after confirmation, the tool runs a **sequential cumulative render pipeline**:

1. **Scaffold** — one agent establishes destination paths, structure, and conventions.
2. **Agent-selected batches** — each render session chooses a coherent batch of uncovered
   actionable leaf items via `planning-render-tool select-batch`; one author agent at a
   time integrates each batch into the cumulative workspace output.
3. **Batch review** — after each batch, an independent reviewer may request bounded revision.
4. **Final review** — whole-output review with bounded targeted revision.

Agents write deliverables directly to workspace destination paths. The orchestrator
discovers artifacts by diffing workspace file hashes before and after each session.
Paths matching `render.artifact_ignore_patterns` (gitignore-style globs) and canonical
planning state under the configured run output directory (`--output/.planning-output/`)
are excluded from that diff. The run `--output` directory must lie inside `--workspace`.
Deliverables are UTF-8 text files only.

The output goal may be a one-line prompt or a longer specification. An optional
`## Output artifacts` section is illustrative sample layout only.

### Render-only mode

Render an existing confirmed plan without rerunning decomposition or review:

```bash
top-down-planning \
  --render-only \
  --output ./planning-output
```

Rerender with a revised output goal:

```bash
top-down-planning \
  --render-only \
  --output ./planning-output \
  --output-goal-file updated-output-goal.md
```

Force rerender from scratch:

```bash
top-down-planning \
  --render-only \
  --output ./planning-output \
  --force-rerender
```

Configure render behavior in the run config:

```yaml
render:
  max_retries: 3
  final_review: true
  max_batch_revision_cycles: 1
  max_final_revision_cycles: 2
  scaffold: true
  artifact_ignore_patterns:
    - "**/__pycache__/"
    - "**/.pytest_cache/"
    - "*.pyc"
    - "**/build/"
```

Incomplete, blocked, or failed planning runs keep internal state under `.planning-output/`
but do not write new deliverables.

## v1 contracts

Authoritative contracts and examples are available from the CLI:

```bash
top-down-planning schema list
top-down-planning schema show plan
top-down-planning schema show operation
top-down-planning example show transaction
```

### Planning state (`plan.yaml`)

Flat list of items with stable tool-owned IDs (`item-001`, `item-002`, ...), parent references, deterministic ordering, and separate decomposition/readiness statuses.

The `source` block stores compact labels for the output goal and stop hint. When a goal
or hint comes from a file, `plan.yaml` also records `output_goal_file` or
`stop_hint_file`. Full text is loaded from those files at runtime.

Supported decomposition statuses:

- `needs_expansion`
- `expanded`
- `actionable`
- `blocked`
- `out_of_scope`

### Sequential agent-selected batches

Each planning iteration runs **one** Cursor agent session. The orchestrator exposes
only the **shallowest incomplete depth** as eligible items (stable sort by `order`,
then `id`). The agent reviews that inventory, processed-batch history, and output
goal, then records its chosen scope with `planning-plan-tool select-batch` before
recording operations and finalizing the transaction.

Each iteration counts toward `limits.max_iterations` (default `50`). When a session
completes, the transaction is validated and applied atomically. Failed sessions retry
up to `limits.max_retries` without mutating the plan.

Structural decomposition limits (`limits.max_depth`, default `6`; root depth is `0`, and
`limits.max_children_per_expansion`, default `12`) are shown in each planning prompt with
per-item remaining depth budget. The agent should plan within these caps: group related
work, use `mark_actionable` with rich `notes` / `expected_outputs` / `acceptance_criteria`
when finer source detail does not warrant its own child, and avoid `mark_blocked` solely
because a structural limit was reached. Oversized `expand` operations are rejected with
corrective validation feedback.

### Generation batch context

By default, branch refinement reuses one **persistent primary planner chat** (`--resume <chatId>`)
across iterations. Fresh Cursor sessions are used for independent checkpoint reviewers.

Each primary-planner turn includes:

- **Eligible item inventory** — only the shallowest incomplete depth (stable sort by
  `order`, then `id`); expandable or amendable items the agent may choose from.
- **Processed batch history** — prior iterations for context; agents may revisit batches
  for refinement when warranted.
- **Serialized planning state** — durable `planning-state.yaml` with frozen decisions,
  coverage mappings, branch status, and finding dispositions.
- **Agent-selected scope (writable)** — items recorded via `select-batch`; exactly one
  operation per selected item via `planning-plan-tool`.
- **Patchable related items** — directly related existing nodes may receive optional
  `update_item` patches through `planning-plan-tool record-update` (scope is derived from
  the selected batch; no separate env var).
- **Disposition sessions** — use `session_mode=disposition`; record finding dispositions
  and optional `update_item` patches without `select-batch` or `record-operation`.
- **Global plan context (read-only)** — a digest-addressed plan-overview file reference
  plus broader relevant context. Read the overview file before recording operations.

Configure orchestration with `planning_mode` (`simple`, `lightweight`, `full`, `auto`) and
`session_strategy` in the run config.

Stream events: `generation.batch.context_prepared`, `generation.batch.validated`,
`generation.batch.completed` (include `plan_overview_artifact` and `model` where
applicable; plus `iteration.*` events).

### Agent operation schema

During decomposition, the agent records structured operations through the bundled
`planning-plan-tool` CLI (one transaction file per iteration batch). It must not edit
`plan.yaml` directly. Supported operation types:

- `expand`
- `mark_actionable`
- `mark_blocked`
- `mark_out_of_scope`
- `update_item` (optional cross-item patch for related existing nodes)

Cross-item `update_item` patches use explicit optional fields: omitted means preserve,
empty list means clear. They may update `title`, `objective`, `dependencies`,
`expected_outputs`, `acceptance_criteria`, `notes`, `risks`, and `open_questions` on
patchable related nodes only.

The first decomposition operation on `item-001` must include an agent-generated `title`
and `objective` specific to the input and output goal. This applies whether the root is
expanded or marked actionable, blocked, or out of scope. These values replace the
generic bootstrap wording before the root enters later plan context, review, or rendering.
Assigned non-root items may also optionally refine their `title` and/or `objective` when
the current wording is misleading or too narrow.

`run-state.json` records the resolved `planning_model`, `review_model`, and
`rendering_model` for the run. These are refreshed from the current config on each
start or resume.

Each batch session writes `.planning-output/iterations/{NNN}-transaction.json`. The
orchestrator validates the iteration atomically, assigns IDs/depth/order, and persists
the updated state to `plan.yaml`. On success it also writes matching
`{NNN}-response.json` and `{NNN}-validation.json` audit files used by resume recovery
(validation must record `"errors": []` for replay).

Set `PLANNING_TOOL_COMMAND` when the CLI is not on `PATH` (for example during local
development):

```bash
export PLANNING_TOOL_COMMAND="$PWD/.venv/bin/python -m top_down_planning.plan_tool"
```

If unset, the orchestrator uses `planning-plan-tool` when installed, otherwise falls
back to `python -m top_down_planning.plan_tool`.

Review and confirmation sessions use `planning-review-tool` (or
`python -m top_down_planning.review_tool`) to record structured results.

Optional guidance for when to stop expanding versus marking items actionable:

- CLI: `--stop-hint` or `--stop-hint-file`
- Config: `stop_hint` or `stop_hint_file`

The stop hint is included in planning prompts to help the agent decide between
`expand` and `mark_actionable`. Resume rejects runs when the stop hint changes after a
prior run stored a digest.

### Agent context

Configure workspace-relative skill and rule file paths under `agent_context` in the run config:

```yaml
agent_context:
  default:
    model: composer-2.5
    skills:
      - ./.cursor/skills/shared/SKILL.md
    rules:
      - ./.cursor/rules/shared.mdc
  planning:
    skills:
      - ./.cursor/skills/planning/SKILL.md
  rendering:
    skills:
      - ./.cursor/skills/rendering/SKILL.md
    rules:
      - ./.cursor/rules/rendering.mdc
  review:
    skills:
      - ./.cursor/skills/review/SKILL.md
```

Planning sessions receive `default` + `planning` references. Render sessions receive
`default` + `rendering` references. Checkpoint specialist reviews receive
`default` + `review` references. Supported phase keys are `default`, `planning`,
`rendering`, and `review`; unknown keys fail at config load.

See [`examples/planning.config.yaml`](examples/planning.config.yaml).

### Prompt embedding

Prompts use hybrid embedding for the primary input and output goal: when content is at or below `--embed-threshold` characters (default 4000, env `PLANNING_TOOL_EMBED_THRESHOLD`),
it is inlined in the prompt; otherwise the agent is told to open the file by path
(workspace-relative when possible, plus absolute). Resume compatibility uses SHA-256
digests of the resolved goal content.

### Actionability and stopping

Actionability criteria are inferred from the **full resolved output goal text** (inline or
file-backed), not just the compact label stored in `plan.yaml`. Implementation-oriented
goals require expected outputs and acceptance criteria on actionable leaves.

Structural completion is evaluated deterministically: planning finishes when no expandable
items remain, decomposed internal nodes are `expanded`, relevant leaves are `actionable`,
`blocked`, or `out_of_scope`, and the graph is structurally valid (`expanded` nodes have
children; `actionable` nodes are leaves). Checkpoint specialist reviews and deterministic
orchestration validation provide goal-aware semantic approval before render. Persisted plans
use `schema_version: 2`.
Safety limits (`--max-iterations`, `--max-depth`, `--max-children-per-expansion`,
`--max-retries`, `session_timeout_seconds`, `parse_error_threshold`) preserve partial
output with explicit final statuses.

### Checkpoint reviews and finalization

After structural decomposition completes, the tool runs checkpoint specialist reviews and a
deterministic finalization gate before render (enabled by default):

```yaml
review:
  enabled: true
  max_retries: 3
```

Lifecycle:

```text
Persistent primary decomposition → checkpoint specialist reviews →
primary-planner finding disposition → deterministic validation → render
```

Review sessions are read-only with respect to `plan.yaml`. Agents record structured
results through `planning-review-tool` (not free-form chat approval). Each specialist
result is tied to a deterministic plan digest; stale approvals are rejected when the
plan changes.

When `review.enabled: false`, structurally complete plans render immediately
(`review_status: skipped`).

Configure review agent context under `agent_context.review` (model, skills, rules).
Disposition and replan turns reuse the persistent primary planner session.

Render requires `review_status: confirmed` when review is enabled.

### Persistence and resume

`run-state.json` stores iteration counters, limits, resolved phase models
(`planning_model`, `review_model`, `rendering_model`), SHA-256 digests of the input
file and output goal, and durable `planning-state.yaml`. `review-state.json` stores
review stage, plan digest, and completed checkpoints. On resume, decomposition continues
when expandable items remain; otherwise the tool reuses stored specialist review artifacts
only when their plan digest matches the current canonical plan, then proceeds to
finalization or render.

Resume rejects changed input, changed output goal, or mismatched `render`
settings. Safety limits (`max_iterations`, `max_depth`, `max_children_per_expansion`,
`max_retries`, `session_timeout_seconds`, `parse_error_threshold`) may be updated on
resume — for example, raise `max_iterations` after hitting
`incomplete_limit_reached`. Resuming an
already-complete, confirmed run skips render when render state is `complete` and prior
deliverables still exist on disk (use `--force-rerender` to regenerate).

On resume, the tool detects when `plan.yaml` was reset but `run-state.json` still shows
prior progress. It attempts to rebuild the plan by replaying stored
`iterations/*-response.json` audit files whose sibling `*-validation.json` records
`"errors": []` before continuing. Obsolete `run-state.json` keys (for example a removed
`generation` block) fail closed on load — start a fresh run or remove incompatible fields.

During decomposition, render, and review/confirmation sessions, `plan.yaml` is backed
up and restored automatically if an agent modifies canonical state unexpectedly.

### Examples

**Software implementation plan** (default bundled example):

```bash
top-down-planning --config ./examples/planning.config.yaml
```

Uses [`examples/idea.md`](examples/idea.md) with an implementation-oriented output goal.
After review and confirmation, sequential render batches write deliverables such as
`implementation-plan.md` when the output goal calls for them.

**Generic non-software planning** — use a non-implementation goal; optionally disable
review for a lightweight run:

```yaml
output_goal: Produce a structured event planning checklist with ordered phases.
review:
  enabled: false
```

### Stream events

When `--stream-json` is enabled, planning-phase events include:

- `planning.started`
- `iteration.started` / `iteration.completed` (with `eligible_items`, `selected_items`)
- `generation.batch.context_prepared` / `generation.batch.validated` / `generation.batch.completed`
  (include `plan_overview_artifact` and `model` where applicable)
- `validation.failed`, `item.expanded`, `item.actionable`, `item.updated`, etc.

Render-phase events include:

- `render.only.started` (render-only mode)
- `render.scaffold.started` / `render.scaffold.completed`
- `render.batch.started` / `render.batch.completed` (`render.batch.started` includes
  `eligible_items` for uncovered actionable leaves)
- `render.batch.review.started` / `render.batch.review.completed`
- `render.batch.revision.started` / `render.batch.revision.completed`
- `render.final_review.started` / `render.final_review.completed`
- `render.final_revision.started` / `render.final_revision.completed`
- `render.completed` (with `artifacts`)
- `render.skipped` (when resuming with completed render state and existing deliverables)

Review-phase events include:

- `review.started` / `review.completed` / `review.needs_revision` / `review.blocked`
- `revision.started` / `revision.applied` (with `reopened_nodes`, `amend_node_ids`, `annotated_node_ids`)
- `confirmation.started` / `confirmation.confirmed` / `confirmation.needs_revision` / `confirmation.blocked`

## Testing

```bash
pytest
python -m build
```

Integration tests use a deterministic fake agent fixture; live Cursor tests are optional and marked `@pytest.mark.live`.

## Design note: render scope

Rendering covers **actionable leaf items** in agent-selected batches. Actionable leaves
are listed in dependency-safe topological order (creation `order` is the tie-breaker).
**Expanded** internal nodes provide context in prompts but are not render deliverables
and do not receive separate render sessions. Each batch author integrates its assigned
leaves into the cumulative workspace deliverables established by the scaffold and prior
batches. The render brief defines authoritative ownership while treating named paths and
examples as investigation anchors unless the source says otherwise.
Processed-batch history in `render-state.json` records completed batches for review
digests and resume.
