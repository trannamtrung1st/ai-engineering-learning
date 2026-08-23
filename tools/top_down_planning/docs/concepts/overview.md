# What Top Down Planning is

**Audience:** newcomers deciding whether TDP applies to their work.

Top Down Planning (`tdp`) orchestrates planning and production: it takes an input and an output goal, builds a top-down plan, reviews and validates that plan, produces output in coherent batches, and resolves a final quality outcome.

The durable unit of work is a **run**. Agents inside provider sessions mutate plan, production, and review state only through `tdp agent` commands. Operators start, stage, inspect, and resume runs through the user CLI. The orchestration engine owns phase transitions and persisted run state.

Production runs use the `cursor` provider. The `stub` provider is test-only.

## Problem

Complex work needs a plan that can be reviewed, a production sequence that records evidence, and a quality gate that does not collapse “the agent said it was done” into acceptance. Without that loop, planning, implementation, and review live in chat transcripts that cannot be resumed, audited, or validated against a contract.

TDP persists the plan tree, production batches, review decisions, and run lifecycle so a later session can continue from canonical state rather than from memory.

## Intended use cases

- Drive a project output from declared inputs and an output goal through planner, producer, and reviewer sessions with mandatory plan and output reviews.
- Decompose work as a top-down tree of items with dependencies, then produce ready work items in batches with recorded evidence.
- Stage a run (for example stop after planning or validation), inspect it, and resume, including after an operational pause.
- Nest work as Sub-TDP child runs under a parent, then integrate accepted child results.
- Give runtime agents a discoverable protocol (`tdp agent help`, `readme`, `schema`, `example`) instead of host IDE planning modes.

Procedures for those journeys live under [workflows](../workflows/README.md) and the [operator manual](../manual/README.md). Agent request shapes live under [runtime agents](../agents/README.md).

## Non-goals

- **Host IDE planning modes** are not the TDP workflow. Runtime agents record work through `tdp agent` commands.
- **`stub` is not a production provider.** Tests script deterministic turns with `stub`; operators running `tdp` use `cursor`.
- **Hand-editing orchestrator-owned run files** is not how operators or agents advance a run. Inspect through documented commands; see [run store](../manual/run-store.md).
- **TDP is not a general chat UI** and not a replacement for the Cursor CLI. It orchestrates provider sessions and persists planning, production, and review.
- **Internal Python type names** are maintainer vocabulary. User-facing names are CLI commands, config paths, run status, phases, and the plan/production/review fields documented here.

Related: [plan tree](plan-tree.md), [roles](roles.md), [first-run walkthrough](../workflows/first-run.md), [documentation home](../README.md).
