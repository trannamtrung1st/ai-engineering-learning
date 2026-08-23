# Decision: run ownership and concurrency

**Status:** verified current behavior.

**Evidence:** `domain/run_ownership.py` (module docstring and `fcntl` import guard); `tests/unit/test_run_ownership.py` (flock held ⇒ orphan cleanup does not steal; `.owner.lock` inode stable across acquire/release); `tests/unit/test_design_decisions.py` (`test_decision_13_run_lease_prevents_concurrent_resume`); `tests/unit/test_commit_concurrency.py`.

Operator effects: [troubleshooting](../manual/troubleshooting.md#concurrency). Persistence: [persistence](../internals/persistence.md).

## Binding choice

Exactly one live continuer per run. Cross-process authority is an advisory **flock** on a persistent sentinel inode `.resume.lock.d/.owner.lock` (never unlinked during release or stale-lock cleanup). A **free flock** means no live owner. Stale `owner.json` cannot grant ownership while another process holds the flock.

`run_ownership()` is the acquire/release context used by `continue_run` and resume apply. Importing the module **requires POSIX `fcntl`**; Windows Python is not supported for this lock.

## Verified consequences

- Final acquisition is nonblocking (`LOCK_NB`). Nested in-process ownership is token-scoped.
- Without `/proc`, identity is `{pid}:unknown`; a matching live PID is treated conservatively as a holder.
- Two operators cannot `tdp resume` the same run concurrently; the second fails to acquire.
- Sub-TDP attach holds parent ownership for the full validate-and-commit path.
- This is independent of Cursor session replacement ([session bindings](session-bindings.md)) and of CAS revisions on `run.json` (both exist; flock is the live-owner primitive).

## Not claimed

This record does not invent a history of lock file formats or claim Windows `msvcrt` locks are used for TDP resume (they are not: TDP ownership imports `fcntl` or fails).

Related: [lifecycle architecture](../architecture/lifecycle.md).
