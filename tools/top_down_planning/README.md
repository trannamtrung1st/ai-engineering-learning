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

Each run writes user-facing deliverables directly under `--output`. The deliverable
filename(s) and format(s) come from the output goal's **Output artifacts** section
when present, or are chosen by the final render phase to match the goal.

Internal resumable state is stored separately under `.top-down-planning/`:

```text
planning-output/
├── implementation-plan.md          # example goal-driven deliverable
└── .top-down-planning/
    ├── plan.yaml
    ├── run-state.json
    └── iterations/
        ├── 001-request-prompt.md
        ├── 001-response.json
        └── render-response.json
```

The `--output` directory should contain only generated deliverables at its top level.
Do not place input files or output goal files there.

Goal-driven deliverables are written only when planning finishes with status `complete`.
Incomplete or failed runs keep internal state under `.top-down-planning/` but do not
write new deliverables.

## v1 contracts

### Planning state (`plan.yaml`)

Flat list of items with stable tool-owned IDs (`item-001`, `item-002`, ...), parent references, deterministic ordering, and separate decomposition/readiness statuses.

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

### Agent context

Each iteration prompt references the primary input Markdown file by path (workspace-relative when possible, plus absolute). The agent is instructed to open and read that file; the prompt does not embed the full document inline.

The output goal may be supplied inline with `--output-goal` or as a Markdown/text file via `--output-goal-file`. When a file is used, the prompt references that file by path instead of embedding its contents. Resume compatibility uses SHA-256 digests of the resolved goal content.

### Actionability and stopping

Actionability criteria are inferred from `--output-goal`. Implementation-oriented goals require expected outputs and acceptance criteria on actionable leaves.

Planning completes when no expandable items remain and the graph is structurally valid. Safety limits (`--max-iterations`, `--max-depth`, `--max-items`, `--batch-size`, `--max-retries`) preserve partial output with explicit final statuses.

### Persistence and resume

`run-state.json` stores iteration counters, limits, and SHA-256 digests of the input file and output goal. Resume rejects changed input, changed output goal, or mismatched limits. Resuming an
already-complete run skips the render phase when prior deliverables still exist on disk.

### Stream events

When `--stream-json` is enabled, render-phase events include:

- `render.started`
- `render.completed` (with `artifacts`)
- `render.skipped` (when resuming with existing deliverables)
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
