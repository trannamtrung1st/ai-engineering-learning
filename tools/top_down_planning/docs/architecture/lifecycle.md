# Lifecycle and state-transition architecture

**Audience:** maintainers tracing how a run moves between phases and outcomes.

Operator vocabulary for status vs phase vs review stage vs revision: [lifecycle terms](../concepts/lifecycle-terms.md). Stop-state rationale: [lifecycle stop states](../decisions/lifecycle-stop-states.md). This page is the engine’s current transition architecture.

## Canonical state

Persisted run state is authoritative. Returned continuation results, CLI outcomes, and in-memory objects must match it. Once a layer durably moves a run out of `running`, outer error handling must **preserve** that decision (reload before applying a generic failure/pause). `SessionRecoveryPaused` means the pause is already persisted; it is not remapped to a second pause.

## Status transitions

Allowed lifecycle mutations (enforced centrally):

```text
running  → paused | failed | completed
paused   → running (validated resume only) | failed (explicit escalation)
completed / failed → no lifecycle mutation
```

- `paused` requires an **operational** stop record and null `outcome`.
- `failed` requires an **invariant** stop record and null `outcome`.
- `completed` requires a quality `outcome` (`accepted` / `rejected` / `blocked`) and null `stop`.
- `running` has null `outcome` and null `stop`.

Continuation success is `completed` **and** `accepted` only.

## Phases and review stages

The engine walks product phases (`planning`, `whole_plan_review`, `plan_validated`, `production`, `plan_amendment`, `sub_tdps`, `whole_output_review`, `output_validated`). Mandatory whole-plan/whole-output **stages** (`initial_review`, `finding_verification`, `scope_review`) live on the review loop, not on `run.status`. Review-loop mechanics: [review architecture](../internals/reviews.md).

`phase_action_id` identifies the current provider step. Session replacement and some limits are scoped per `phase_action_id`.

Each lifecycle transition and its required audit event share one commit (`CommitSpec`: run/production state plus events). New split `save_run` + `append_event` lifecycle paths are not added. Persistence details: [persistence](../internals/persistence.md).

## Ownership

Continuation acquires run ownership (POSIX flock on a persistent sentinel under the run dir) for the duration of `continue_run` / resume apply. Two processes cannot continue the same run. [Run ownership](../decisions/run-ownership.md), [troubleshooting](../manual/troubleshooting.md#concurrency).

Capability tokens are bound to the session and phase; revocation is coordinated with the same commit path when a phase ends. [Agent authorization](../decisions/agent-authorization.md).

## Outcome resolution

After output validation, the engine evaluates the acceptance invariant ([quality loop](../concepts/quality-loop.md)) and maps it to `accepted` / `rejected` / `blocked`, then completes the run. A missing whole-plan/whole-output approval or failed deterministic validation yields `blocked`. Remaining unsatisfied invariant clauses yield `rejected`. That mapping is domain logic (`resolve_quality_outcome`), not operator CLI flags.

Prepared Sub-TDP parent flow (drive/attach children → synthesize → parent production → whole-output review) is still this lifecycle with phase `sub_tdps`. [Prepared execution](../workflows/prepared-and-sub-tdp.md).

Related: [system context](system-context.md), [sessions](sessions.md).
