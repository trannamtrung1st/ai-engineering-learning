# Top-Down Planning Tool

Generic CLI that progressively decomposes one Markdown input into a structured plan using Cursor Agent CLI in read-only (`ask`) mode.

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

### Model selection

By default the tool uses Cursor model `gpt-5.6-sol-high`. Override with `--model` or `PLANNING_TOOL_MODEL`:

```bash
top-down-planning \
  --input ./examples/idea.md \
  --output-goal "Produce an actionable implementation plan" \
  --output ./planning-output \
  --model gpt-5.6-sol-high
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
    └── iterations/
        ├── 001-request-prompt.md
        ├── 001-response.json
        └── render-response.json
```

Goal-driven deliverables are written only when planning finishes with status `complete`.
The render phase transforms the completed breakdown into deliverables that satisfy the
output goal. Incomplete or failed runs keep internal state under `.planning-output/`
but do not write new deliverables.

Before render, the tool writes `render-brief.md` from `plan.yaml`. That brief lists
every actionable leaf unit and is the authoritative scope contract for deliverables.
The output goal defines format and schema; the breakdown defines which items must
appear. After render, the tool validates that every breakdown title appears in the
written deliverables and retries with feedback when coverage is incomplete.

Render audit artifacts under `.planning-output/iterations/` include
`render-brief.md`, `render-request-prompt.md`, `render-response.json` (discovered
artifact paths and any coverage errors), and agent logs when audit is enabled.

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

### Breadth-first selection

Each iteration selects items with `decomposition_status = needs_expansion` at the **minimum current depth**, ordered by insertion order, capped by `--batch-size`.

### Agent operation schema

The agent returns structured operations only:

- `expand`
- `mark_actionable`
- `mark_blocked`
- `mark_out_of_scope`

The tool validates the full batch atomically, assigns IDs/depth/order, and persists the updated state.

Optional guidance for when to stop expanding versus marking items actionable:

- CLI: `--stop-hint` or `--stop-hint-file`
- Config: `stop_hint` or `stop_hint_file`

The stop hint is included in planning prompts to help the agent decide between
`expand`, `mark_actionable`, and `assessment.plan_complete`. Resume rejects
runs when the stop hint changes after a prior run stored a digest.

### Agent context

Prompts use hybrid embedding for the primary input and output goal: when content is at
or below `--embed-threshold` characters (default 4000, env `PLANNING_TOOL_EMBED_THRESHOLD`),
it is inlined in the prompt; otherwise the agent is told to open the file by path
(workspace-relative when possible, plus absolute). Resume compatibility uses SHA-256
digests of the resolved goal content.

### Actionability and stopping

Actionability criteria are inferred from `--output-goal`. Implementation-oriented goals require expected outputs and acceptance criteria on actionable leaves.

Planning completes when no expandable items remain and the graph is structurally valid. Safety limits (`--max-iterations`, `--max-depth`, `--max-items`, `--batch-size`, `--max-retries`) preserve partial output with explicit final statuses.

### Persistence and resume

`run-state.json` stores iteration counters, limits, and SHA-256 digests of the input file and output goal. Resume rejects changed input, changed output goal, or mismatched limits. Resuming an already-complete run skips the render phase when prior deliverables still exist on disk.

On resume, the tool detects when `plan.yaml` was reset but `run-state.json` still shows prior progress. It attempts to rebuild the plan by replaying stored `iterations/*-response.json` audit files before continuing.

During render, `plan.yaml` is backed up and restored automatically if the render agent modifies canonical state.

### Stream events

When `--stream-json` is enabled, render-phase events include:

- `render.started`
- `render.completed` (with `artifacts`)
- `render.skipped` (when resuming with existing deliverables)
- `render.validation_failed` (when deliverables omit breakdown items)
- `render.fallback` (deterministic fallback artifact)
- `render.retrying`

## Testing

```bash
pytest
python -m build
```

Integration tests use a deterministic fake agent fixture; live Cursor tests are optional and marked `@pytest.mark.live`.

## Design note: expanded internal nodes

When an item is expanded, it becomes a non-leaf container marked `actionable` so it is no longer selected for expansion. Only **leaf** actionable items should appear in the final actionable list inside the rendered deliverable.
