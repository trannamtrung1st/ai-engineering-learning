# Security and reliability boundaries

**Audience:** maintainers of authorization, containment, and process lifetime.

Operator cancel/concurrency: [troubleshooting](../manual/troubleshooting.md). Session architecture: [sessions](../architecture/sessions.md). Decisions: [agent authorization](../decisions/agent-authorization.md), [run ownership](../decisions/run-ownership.md).

## Capability authorization

Mutating `tdp agent` commands read `TDP_CAPABILITY_TOKEN_FILE`. Authorization checks phase, allowed operations, bound provider session, and (for reviewers) the review loop. Capability **records store `secret_hash` only**; plaintext tokens are revoked when turns, loops, or phases end. Stream-event sync **reuses the live exported token**; minting a new token per streamed event is invalid. Reissue only when the exported file is gone or the live record no longer matches the binding. Agents do not pass `--role`. `TDP_RUN_ID` must match `--run` when capability context is active. `--request` paths must resolve inside `agent-requests/`.

Pending capability revocation can be persisted on the run (`pending_capability_revoke_phase`) and reconciled after ownership is held. [Agent CLI](../agents/cli.md).

## Redaction and secrets

Capability tokens and secrets are redacted at every log level in stderr, JSONL, `agent-transcript.jsonl`, and desktop notifications (authorization headers, `password=` / `api_key=` forms, tokens in prose). `--log-level` / `--no-agent-text` filter stderr only; transcripts persist independently. Redaction runs **before** truncation.

Treat exported run directories as sensitive: `agent-requests/` and transcripts may contain workspace or review content.

## Workspace and store containment

Workspace resource and evidence paths must stay inside `project.workspace` (no absolute escape, `..`, or symlink escape). Run-store paths must stay under the store root and the run directory; run dirs and canonical children must not be symlinks. Journal basenames are single-segment (no `..` or path separators). Package IDs are confined under `.execution_packages/`.

Skill and guidance snapshot keys cannot be authorized via production `outputs`.

## Ownership locks

Cross-process continuation uses POSIX `fcntl` flock on a **persistent** `.resume.lock.d/.owner.lock` inode (never unlinked on release). A free flock means no live owner; stale `owner.json` cannot grant ownership. Final acquisition is nonblocking (`LOCK_NB`).

Without `/proc`, process identity is `{pid}:unknown` and matching live PIDs are treated conservatively as holders. Importing run ownership **requires** `fcntl`; Windows Python is not supported for multi-process resume locking.

## Cancellation and stale processes

Owned SIGINT/SIGTERM persists `user_cancelled`, terminates tracked pids (SIGTERM then SIGKILL), and records `stop.details.terminated_pids`. `abort_turn` + `wait_turn_settled` drain collector threads before the next prompt. `terminate_all_sessions()` kills every tracked pid.

Orphan scans include **completed** and **failed** runs. `tdp doctor --fix` kills orphans, reconciles interrupted runs, and removes leftover `.creating-*` dirs. Leftover stream-json writers after a cap rejection are killed even when bound terminate fails closed or identity inspect is unverifiable; when identity is a live match, oversized writers are terminated only through verified identity. Leftover hold processes are reaped. Teardown waits past janitor SIGTERM drain and **fails on the original leak**, not post-reap emptiness. Scans ignore Linux `TASK_DEAD` and Linux/Darwin zombies. Pre-run orphan cleanup must not fail on unrelated macOS host processes. Janitor wait budget is accounted at the status-read and `raw_wait` edges. Session architecture: [process cleanup](../architecture/sessions.md#process-cleanup).

Idle Cursor turns: `limits.provider.turn_idle_timeout_seconds` (TDP default `2`; `0` disables) raises `ProviderTurnStalledError` (not retried by `max_retries_per_call`). One replacement per `phase_action_id`; exhaustion → `session_recovery_exhausted`. Assembled stream-json lines (including the terminating newline) larger than `limits.provider.max_stream_json_record_bytes` (TDP default `1048576` / 1 MiB) fail the turn as `provider_turn_failed` (`ProviderStreamRecordTooLargeError`). The cap is enforced independently of read/exit boundaries; drain **stops** once exceeded; a valid buffered prefix can still be rejected as oversized; leftover flood writers must not remain on argv.

## Platform and optional dependencies

| Constraint | Behavior |
| --- | --- |
| POSIX flock / Cursor process tree | Required for resume locking and `CursorProvider`. Windows: `ProviderUnsupportedPlatformError` / import error on ownership. |
| Notifications extra `[notifications]` (`notify-py`) | Without it, desktop alerts are **silently skipped**. `CI=true` and headless Linux suppress sends. |
| `stub` provider | Tests only. |

Related: [observability](../manual/observability.md), [persistence](persistence.md).
