# Operator-visible agent sessions

**Audience:** operators watching planner, producer, and reviewer sessions without implementing agent protocol.

Agents mutate state only through `tdp agent` commands. Exact schemas, capability tokens, and request files: [agent hub](../agents/README.md). Roles: [roles](../concepts/roles.md). This page is what you see from the operator CLI.

Host IDE planning modes are not part of the TDP session flow.

## What a blocking `tdp run` / `tdp resume` does

The engine binds a provider session, injects packaged skills (default) and context, and runs turns until a **persisted** agent command or completion signal closes the turn ([protocol](../agents/protocol.md#completion-signals)).

On stderr you typically see `[run:start]` / `[run:resume]`, then `[session:start]` / `[session:resume]` / `[session:end]` with `phase`, `role`, `activity`, and `model`. Reviewer sessions also carry loop type; mandatory whole-plan/whole-output gates add `stage`. Console category meanings: [observability](../manual/observability.md).

`phase` is the run lifecycle. `stage` is a mandatory review step. Do not treat them as `run.status`.

## Planning

Activity around `initial_plan` / `plan_revision`. The planner snapshots and applies the plan, then emits `candidate_plan_ready`. Optional focused plan review may interleave. Then the engine starts `whole_plan_review`.

## Production

After `plan_validated`, a producer session records batches. Each persisted `production apply` closes that turn; the engine queues the next turn on the same session. `submit-completion` closes the completion turn. Amendment requests move the run to `plan_amendment` (planner emits `amendment_revision_ready`). [Producer protocol](../agents/producer.md).

## Reviews

Focused reviews use bounded reviewer sessions. Mandatory whole-plan and whole-output gates run `initial_review`, `finding_verification`, and `scope_review`. A persisted `review respond` releases the reviewer session. Owner (planner or producer) advisory turns close on `review record-actions`. If a reviewer turn ends without respond, the engine nudges until `limits.review.max_agent_turns_per_gate` then pauses `limit_exhausted`. [Reviewer protocol](../agents/reviewer.md).

## Completion signals operators rely on

You do not type these. You infer progress from status/phase and stderr:

| Visible effect | Underlying close condition |
| --- | --- |
| Planning construction ends; whole-plan review starts | Planner `candidate_plan_ready` |
| Production batch recorded; next producer turn | `production apply` persisted |
| Whole-output review can start | `submit-completion` persisted |
| Reviewer session ends | `review respond` persisted |
| Owner sweep recorded | `review record-actions` persisted |

If the process is interrupted, [cancellation](../manual/troubleshooting.md#cancellation). If a session stalls or the remote Cursor session vanishes, one replacement per `phase_action_id`; exhaustion fails the run (`session_recovery_exhausted`).

Related: [lifecycle](lifecycle.md), [first run](first-run.md).
