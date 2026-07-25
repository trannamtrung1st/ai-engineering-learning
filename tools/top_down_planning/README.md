# Top-Down Planning Tool

Generic CLI that progressively decomposes one Markdown input into a structured plan using Cursor Agent CLI in agent mode for decomposition (and agent mode for final render).

This package mirrors the reusable infrastructure patterns from [`../implement_todos/`](../implement_todos/) while keeping planning-specific state and operations separate.

## Install

```bash
cd tools/top_down_planning
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
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

When render falls back to a deterministic artifact, the final notification indicates fallback mode. Wave/iteration progress is not notified. `--stream-json` stdout remains machine-readable only.

### Model selection

By default the tool uses Cursor model `auto`. Override with `--model` or `PLANNING_TOOL_MODEL`:

```bash
top-down-planning \
  --input ./examples/idea.md \
  --output-goal "Produce an actionable implementation plan" \
  --output ./planning-output \
  --model auto
```

## Outputs

The tool separates **user-facing deliverables** from **internal resumable state**.

`--output` stores resumable planning state under `.planning-output/`. Deliverables may
be written anywhere in the workspace according to the output goal — they are not
required to live under `--output`.

Example layout when deliverables stay under `--output`:

```text
planning-output/
├── implementation-plan.md          # example goal-driven deliverable
└── .planning-output/
    ├── plan.yaml
    ├── run-state.json
    ├── review-state.json
    └── iterations/
        ├── 001-request-prompt.md
        ├── 001-transaction.json
        ├── 001-response.json
        ├── render-brief.md
        ├── render-001-response.json
        └── reviews/
            ├── whole-plan-request-prompt.md
            ├── whole-plan-result.json
            ├── final-confirmation-request-prompt.md
            └── final-confirmation-result.json
```

Goal-driven deliverables are written only when planning finishes with status `complete`
and review status `confirmed` (when review is enabled). The render phase transforms
the completed breakdown into deliverables that satisfy the output goal. Incomplete,
blocked, or failed runs keep internal state under `.planning-output/` but do not write
new deliverables.

Before render, the tool writes `render-brief.md` from `plan.yaml`. That brief lists
every actionable leaf unit and is the authoritative scope contract for deliverables.
The output goal defines format and schema; the breakdown defines which items must
appear. After render, the tool validates that every breakdown title appears in the
written deliverables and retries with feedback when coverage is incomplete.

Render audit artifacts under `.planning-output/iterations/` include
`render-brief.md`, per-attempt files such as `render-001-request-prompt.md`,
`render-001-response.json`, and `render-001-agent.{ndjson,log}` (one numbered set
per render attempt/ retry), plus agent logs when audit is enabled.

## v1 contracts

### Planning state (`plan.yaml`)

Flat list of items with stable tool-owned IDs (`item-001`, `item-002`, ...), parent references, deterministic ordering, and separate decomposition/readiness statuses.

The `source` block stores compact labels for the output goal and stop hint. When a goal
or hint comes from a file, `plan.yaml` also records `output_goal_file` or
`stop_hint_file`. Full text is loaded from those files at runtime.

Supported decomposition statuses:

- `needs_expansion`
- `actionable`
- `blocked`
- `out_of_scope`

### Concurrent batch selection

Each planning wave selects expandable items across independent branches, preferring
shallower items first (tie-broken by insertion order). Up to `--concurrent-batches`
agent sessions run in parallel per wave (default `3`), and each batch is capped by
`--batch-size`. Each launched batch counts as one iteration toward `--max-iterations`.

When a wave completes, all batch responses are validated against the same plan
snapshot and merged atomically. If any batch in a wave fails after retries, the
entire wave is discarded and nothing from that wave is applied.

### Agent operation schema

During decomposition, the agent records structured operations through the bundled
`planning-plan-tool` CLI (one transaction file per iteration batch). It must not edit
`plan.yaml` directly. Supported operation types:

- `expand`
- `mark_actionable`
- `mark_blocked`
- `mark_out_of_scope`

Each batch session writes `.planning-output/iterations/{NNN}-transaction.json`. The
orchestrator validates the full wave atomically, assigns IDs/depth/order, and persists
the updated state to `plan.yaml`. On success it also writes matching
`{NNN}-response.json` audit files used by resume recovery.

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
`expand`, `mark_actionable`, and `plan_complete` (via `set-assessment`). Resume rejects
runs when the stop hint changes after a prior run stored a digest.

### Agent context

Configure workspace-relative skill and rule file paths under `agent_context` in the run config:

```yaml
agent_context:
  default:
    skills:
      - ./.cursor/skills/shared/SKILL.md
    rules:
      - ./.cursor/rules/shared.mdc
  planning:
    model: gpt-5.6-sol-high
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
`default` + `rendering` references. Whole-plan review and final confirmation receive
`default` + `review` references.

See [`examples/planning.config.yaml`](examples/planning.config.yaml).

### Prompt embedding

Prompts use hybrid embedding for the primary input and output goal: when content is at or below `--embed-threshold` characters (default 4000, env `PLANNING_TOOL_EMBED_THRESHOLD`),
it is inlined in the prompt; otherwise the agent is told to open the file by path
(workspace-relative when possible, plus absolute). Resume compatibility uses SHA-256
digests of the resolved goal content.

### Actionability and stopping

Actionability criteria are inferred from `--output-goal`. Implementation-oriented goals require expected outputs and acceptance criteria on actionable leaves.

Planning completes when no expandable items remain and the graph is structurally valid.
Safety limits (`--max-iterations`, `--max-depth`, `--max-items`, `max_children_per_expansion`,
`--batch-size`, `--concurrent-batches`, `--max-retries`) preserve partial output with
explicit final statuses.

### `max_children_per_expansion` and explicit siblings

`max_children_per_expansion` (default `12`) is a per-`expand` safety limit. It must
not be used to silently merge or omit explicitly required sibling groups. When the
source or stop hint requires more direct children than the limit allows, the planning
agent should `mark_blocked` with:

- `constraint_code: "max_children_exceeded"`
- `required_min_children` greater than the configured limit

Example blocked summary:

```text
Source requires at least 9 direct children under item-001, but
max_children_per_expansion is 8. Increase the limit to at least 9
or revise the source structure.
```

These runs finish as `incomplete_blocked` and do not enter review or render.

### Whole-plan review and final confirmation

After structural decomposition completes, the tool runs a bounded semantic quality gate
before render (enabled by default):

```yaml
review:
  enabled: true
  max_revision_cycles: 1
  max_retries: 3
```

Lifecycle:

```text
Decomposition → deterministic validation → whole-plan review →
(optional targeted revision + replan) → final confirmation → render
```

Review sessions are read-only with respect to `plan.yaml`. Agents record structured
results through `planning-review-tool` (not free-form chat approval). Each result is
tied to a deterministic plan digest; stale approvals are rejected when the plan changes.

When `review.enabled: false`, behavior matches the previous tool: structurally complete
plans render immediately (`review_status: skipped`).

Configure review agent context under `agent_context.review` (model, skills, rules).
Planning replan after targeted revision reuses the planning context.

Targeted revision reopens the smallest affected branch(es), removes descendant
decomposition, and resumes normal top-down planning for at most `max_revision_cycles`.

Render requires `review_status: confirmed` when review is enabled.

### Persistence and resume

`run-state.json` stores iteration counters, limits, and SHA-256 digests of the input
file and output goal. `review-state.json` stores review stage, plan digest, revision
cycle, and decisions. On resume, decomposition continues when expandable items remain;
otherwise the tool reuses stored review/confirmation results only when their plan digest
matches the current canonical plan, then proceeds to the next unfinished stage
(review, confirmation, or render).

Resume rejects changed input, changed output goal, or mismatched limits. Resuming an
already-complete, confirmed run skips render when prior deliverables still exist on disk.

On resume, the tool detects when `plan.yaml` was reset but `run-state.json` still shows prior progress. It attempts to rebuild the plan by replaying stored `iterations/*-response.json` audit files (falling back to `*-transaction.json` when needed) before continuing.

During decomposition, render, and review/confirmation sessions, `plan.yaml` is backed
up and restored automatically if an agent modifies canonical state unexpectedly.

### Examples

**Software implementation plan** (default bundled example):

```bash
top-down-planning --config ./examples/planning.config.yaml
```

Uses [`examples/idea.md`](examples/idea.md) with an implementation-oriented output goal.
After review and confirmation, the render phase writes deliverables such as
`implementation-plan.md`.

**Generic non-software planning** — use a non-implementation goal; optionally disable
review for a lightweight run:

```yaml
output_goal: Produce a structured event planning checklist with ordered phases.
review:
  enabled: false
```

**Explicit child-limit conflict** — when the source requires more direct siblings than
the configured limit:

```yaml
limits:
  max_children_per_expansion: 8
stop_hint: |
  Preserve these nine top-level workstreams as distinct direct children.
```

The agent should `mark_blocked` with `constraint_code: max_children_exceeded` and
`required_min_children: 9`. The run finishes as `incomplete_blocked`; no review or
render occurs.

### Stream events

When `--stream-json` is enabled, planning-phase events include:

- `planning.started` (with `concurrent_batches`)
- `wave.started` / `wave.completed` / `wave.retrying`
- `iteration.started` / `iteration.completed` (with `batch_index`, `batch_count`)
- `validation.failed`, `item.expanded`, `item.actionable`, etc.

Render-phase events include:

- `render.started`
- `render.completed` (with `artifacts`)
- `render.skipped` (when resuming with existing deliverables)
- `render.validation_failed` (when deliverables omit breakdown items)
- `render.fallback` (deterministic fallback artifact)
- `render.retrying`

Review-phase events include:

- `review.started` / `review.completed` / `review.needs_revision` / `review.blocked`
- `revision.started` / `revision.applied`
- `confirmation.started` / `confirmation.confirmed` / `confirmation.needs_revision` / `confirmation.blocked`

## Testing

```bash
pytest
python -m build
```

Integration tests use a deterministic fake agent fixture; live Cursor tests are optional and marked `@pytest.mark.live`.

## Design note: expanded internal nodes

When an item is expanded, it becomes a non-leaf container marked `actionable` so it is no longer selected for expansion. Only **leaf** actionable items should appear in the final actionable list inside the rendered deliverable.
