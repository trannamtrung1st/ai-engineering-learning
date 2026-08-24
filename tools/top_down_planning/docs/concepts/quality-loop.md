# Quality loop

**Audience:** operators and runtime agents who need the shared model of how output is produced and judged.

After a plan is approved and validated, TDP produces output in **batches**, binds **evidence**, then requires a **completion claim**, **output review**, and **deterministic validation** before a **quality outcome**. Vocabulary for run status and phases is on [lifecycle terms](lifecycle-terms.md). Procedures are under [workflows](../workflows/README.md).

## Production batches

A producer records a batch against the current `production_revision`. The batch names `plan_items` (ready `work` ids), a **disposition** per item, and **outputs** (workspace paths that changed).

Every changed snapshot-bound workspace path must appear in that batch’s `outputs`. The agent supplies `id`, `type`, and `ref`; the service captures hash, size, media type, and an immutable snapshot. Missing paths fail with `production_evidence_incomplete`. Skill/guidance drift is not authorizable through outputs (`production_context_mutation_unauthorized`).

One production batch is recorded per producer provider turn. Persisting `production apply` closes that turn.

## Dispositions

Every applicable `work` item ends with a terminal disposition:

| Disposition | Meaning |
| --- | --- |
| `completed` | The item’s outcome was produced |
| `satisfied_without_change` | The item is already satisfied; no workspace change |
| `not_applicable` | The item does not apply (requires `reason`) |
| `superseded` | Replaced by another item (requires `replacement_ref`) |
| `blocked` | The producer cannot finish the item (requires `evidence`) |

`blocked` is terminal for that item but is not a satisfied disposition. Aggregates are not given batch dispositions; their satisfaction is derived from descendants ([plan tree](plan-tree.md)).

## Completion claims

When all applicable items have terminal dispositions, the producer submits a completion claim with `goal_assessment` and `production_revision` (`tdp agent production submit-completion`; see `tdp agent example completion-claim`). The service persists that the goal is met and binds the claim to the current plan revision and output revision. The orchestrator closes that producer turn when the claim persists.

## Validation

**Deterministic validation** is not a reviewer opinion. Plan validation and output validation check structure, digests, dispositions, and review state. Approval-mode validation is part of the [acceptance invariant](#acceptance-and-quality-outcomes) below. Operators inspect with `tdp validate`; see the [user CLI](../manual/cli.md).

## Review

Reviews are a separate axis from validation:

| Loop type | When |
| --- | --- |
| `focused_plan` / `focused_output` | Optional, scoped to selected items during planning or production |
| `whole_plan` | Mandatory gate on the candidate plan |
| `whole_output` | Mandatory gate on produced output |

Reviewer decisions include `approved`, `changes_requested`, and `blocked`. Mandatory whole-plan and whole-output loops also use **stages** (`initial_review`, `finding_verification`, `scope_review`) defined on [lifecycle terms](lifecycle-terms.md). Owner `review record-actions` records family-fix sweeps. Protocol details live under [runtime agents](../agents/README.md).

## Acceptance and quality outcomes

A run **completes** with a quality **outcome**. `accepted` requires every clause of the acceptance invariant:

- Whole-plan review approved for the current plan revision
- Deterministic plan validation passed
- All applicable production items terminal or derived
- Completion claim explicitly assesses the output goal as met
- Whole-output review approved for the current output revision
- Deterministic output validation passed
- No unresolved required findings

If that invariant is satisfied, the outcome is `accepted`. If plan or output deterministic validation failed, or a required whole-plan or whole-output approval is missing, the outcome is `blocked`. Otherwise the outcome is `rejected`.

**Terminal quality success** is `status=completed` and `outcome=accepted`. `completed` with `rejected` or `blocked` is a finished run that did not accept. Those values are not the same as run **status** `failed` (an invariant stop).

**Continuation-command success** (`ok` on `tdp run` / `tdp resume`) is broader: a `running` run can still have `ok=true` after a staged `--until` target. `paused` and `failed` are `ok=false`. Vocabulary: [lifecycle terms](lifecycle-terms.md).

Related: [plan tree](plan-tree.md), [roles](roles.md), [lifecycle walkthrough](../workflows/lifecycle.md).
