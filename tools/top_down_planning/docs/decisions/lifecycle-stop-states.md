# Decision: lifecycle stop states

**Status:** verified current behavior.

**Evidence:** `domain/run_lifecycle.py`; `tests/unit/test_design_decisions.py` (`test_decision_1`–`6`); `orchestrator/resume_stop_validators.py`; agent protocol (`tdp agent readme`, Resume / run lifecycle fields).

Vocabulary for operators: [lifecycle terms](../concepts/lifecycle-terms.md). Transition architecture: [lifecycle architecture](../architecture/lifecycle.md).

## Binding choice

A run’s durability is `status` plus, when stopped, either a structured `stop` or a quality `outcome` — not a separate `resumable` boolean.

| Status | Stop / outcome | Recoverability |
| --- | --- | --- |
| `running` | both null | Active |
| `paused` | operational `stop` required; `outcome` null | Recoverable via validated resume |
| `failed` | invariant `stop` required; `outcome` null | Not resumed as a normal pause |
| `completed` | `outcome` required; `stop` null | Terminal quality result |

`new_run_record` does not write a `resumable` field (`test_decision_4_no_separate_resumable_boolean`). `paused` without a structured stop fails lifecycle validation (`test_decision_5`).

## Verified consequences

- `limit_exhausted` is an **operational** pause (`PAUSED_STOP_CODES`), not `failed`.
- `session_recovery_exhausted` is an **invariant** failure (`FAILED_STOP_CODES`).
- Continuation/resume success is `completed` **and** `accepted` only (`continuation_ok_from_run`).
- Quality `blocked` / `rejected` are **completion outcomes**, not `status=failed`.
- Run records use `schema_version` 3; unsupported versions fail load with no migrator (`test_decision_14_old_schemas_rejected`).

## Not claimed

This record does not reconstruct when these statuses were introduced, what alternatives were discarded, or why a `resumable` flag is absent beyond the current invariant that recoverability follows `status` + `stop.category`.

Related: [troubleshooting](../manual/troubleshooting.md), [operations](../workflows/operations.md).
