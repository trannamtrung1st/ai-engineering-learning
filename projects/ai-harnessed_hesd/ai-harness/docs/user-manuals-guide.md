# User Manuals Guide

How the **ManualsGen** loop produces end-user documentation under `docs/user-manuals/`.

## Purpose

ManualsGen is a third harness loop (alongside Ralph and TestGen) with its **own lifecycle**. It turns product specs into:

- **Module guides** — `docs/user-manuals/modules/<slug>.md` (one per user-facing MVP module)
- **Demo flow scripts** — `docs/user-manuals/flows/FLOW-xx.md` (step-by-step walkthroughs for live demos)
- **Demo runbook** — `docs/user-manuals/demo-runbook.md` (ordered stakeholder demo agenda)

These are **not** the engineering user-flow spec in `docs/ui-ux/10-user-flows.md`. That doc defines FLOW-xx for implementers; ManualsGen writes plain-language scripts you can follow while the app runs.

## When to run

ManualsGen is independent of Ralph. Run it anytime after the harness planner has emitted `ai-harness/manuals-backlog.json` (generator step `harness-context-maps`):

```bash
npm run aih:preview              # optional — verify demo steps against a live stack
npm run aih:manualsgen:loop      # generate all pending manual items
```

Optional implementation gate: set `implementationGate.mode` to `required` in `workflows/manualsgen-loop.json` to block ManualsGen until all Ralph slices pass.

## Commands

| Command | What it does |
|---|---|
| `npm run aih:manualsgen:once` | Generate one manual item from backlog |
| `npm run aih:manualsgen:loop` | Autonomous loop until all items are current |
| `npm run aih:manualsgen:drift` | Mark items stale when source docs change fingerprint |
| `npm run aih:manualsgen:validate` | Validate one generated markdown artifact |

Environment overrides: `AIH_MANUALSGEN_MODEL`, `AIH_SKIP_MANUALSGEN_AGENT=1`.

## Flow

```
pick manual item (priority) → doc fingerprint → manualsgen agent
  → validate markdown → mark item in manuals-index → commit
```

1. Pick next item from `ai-harness/manuals-backlog.json` where `manuals-index.json` marks `current: false`
2. Runbook items wait until all `type: flow` items are current
3. `check-manuals-drift.sh` compares doc fingerprint from `manualsgen-docs-map.json` + item `sourceDocs`
4. `build-prompt.sh manualsgen <itemId>` injects into `manualsgen.prompt.md`
5. Agent writes artifact + updates `docs/user-manuals/README.md` index
6. `validate-user-manuals.sh` — required headings, min lines, no forbidden placeholders
7. Item marked current in `manuals-index.json`; optional git commit (ManualsGen-owned paths only)

## Backlog shape

Planner generates `ai-harness/manuals-backlog.json`:

| Type | ID pattern | Output |
|---|---|---|
| `module` | `module-<slug>` | `docs/user-manuals/modules/<slug>.md` |
| `flow` | `FLOW-xx` | `docs/user-manuals/flows/FLOW-xx.md` |
| `runbook` | `demo-runbook` | `docs/user-manuals/demo-runbook.md` |

Index: [`docs/user-manuals/README.md`](../../docs/user-manuals/README.md).

## Running a demo

1. Start preview: `npm run aih:preview`
2. Open [`docs/user-manuals/demo-runbook.md`](../../docs/user-manuals/demo-runbook.md) (after ManualsGen completes)
3. Follow flow scripts in the order listed in the runbook
4. Use role/account notes from the runbook cheat sheet

## Related docs

- [`docs/ui-ux/10-user-flows.md`](../../docs/ui-ux/10-user-flows.md) — engineering flow definitions (source for demo scripts)
- [`docs/preview-runtime.md`](preview-runtime.md) — stack startup for live verification
- [`HARNESS-DESIGN.md`](../HARNESS-DESIGN.md) — ManualsGen component map
