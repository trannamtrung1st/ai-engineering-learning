# Roles and responsibilities

**Audience:** anyone joining a TDP run who needs to know who does what.

Five roles share a run. Three are **runtime agents** inside provider sessions. One is the **human or automation operator** at the user CLI. One is the **orchestration engine** that owns persisted lifecycle.

Exact `tdp agent` command tables live on the [agent hub](../agents/README.md). Operator commands live in the [user CLI](../manual/cli.md). This page states boundaries only.

## Planner

The planner constructs and revises the [plan tree](plan-tree.md).

- Reads plan state with `tdp agent plan snapshot`.
- Mutates the tree with `tdp agent plan apply` (revision field `base_revision`).
- Validates a candidate with `tdp agent plan check`.
- May request focused plan review with `tdp agent review request`.
- Signals a candidate ready for whole-plan review with `candidate_plan_ready`.

The planner does not produce workspace output and does not record production dispositions.

## Producer

The producer implements approved **work** items and records evidence.

- Reads ready items with `tdp agent production snapshot`.
- Records batches with `tdp agent production apply` (`production_revision`, dispositions, outputs).
- Submits a completion claim with `tdp agent production submit-completion` when applicable items are terminal.
- Reports blockers or requests a plan amendment when the approved plan cannot be followed.
- Revises output evidence after `changes_requested` without changing dispositions (`evidence_revision`).

The producer does not expand the plan tree except by requesting an amendment. Batch turns close when apply persists; completion turns close when the claim persists.

## Reviewer

The reviewer judges a plan or output artifact against the review package.

- Responds with `tdp agent review respond` (decisions such as `approved`, `changes_requested`, `blocked`).
- On mandatory whole-plan/whole-output loops, works through `initial_review`, `finding_verification`, and `scope_review` ([lifecycle terms](lifecycle-terms.md)).
- Owners record family-fix sweeps with `tdp agent review record-actions`.

Reviewer turns close when `review respond` persists a decision. Owner advisory turns close when `record-actions` persists. The reviewer does not apply plan mutations or production batches.

## Operator

The operator configures and drives the run from outside provider sessions.

- Installs the package, provider, and working directory ([install](../manual/install.md)).
- Starts, stages, inspects, validates, pauses, and resumes runs.
- Reads status, logs, and run-store artifacts without hand-editing orchestrator state.
- Chooses `cursor` for production runs. Does not use `stub` as an interactive provider.

The operator does not submit `tdp agent` mutating requests. Watching planner/producer/reviewer sessions from the outside is described in [agent sessions](../workflows/agent-sessions.md).

## Orchestration engine

The engine is the `tdp` process that continues a run: it loads canonical persisted state, binds provider sessions, injects agent context and skills, enforces revision and capability checks, records audit events, and applies **monotonic** lifecycle transitions (running → paused / failed / completed).

It owns:

- Phase changes listed under [lifecycle terms](lifecycle-terms.md)
- Provider session create/resume/teardown and process cleanup
- Run ownership so two operators do not mutate the same run concurrently
- Mapping durable state to continuation success (`completed` + `accepted` only)

It does not invent plan items, dispositions, or review findings. Those come from agents through authorized `tdp agent` commands.

Related: [overview](overview.md), [quality loop](quality-loop.md), [session architecture](../architecture/sessions.md).
