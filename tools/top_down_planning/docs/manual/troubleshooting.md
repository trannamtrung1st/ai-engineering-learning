# Troubleshooting and recovery

**Audience:** operators diagnosing a paused, failed, or unexpected run.

Workflow operations ([operations](../workflows/operations.md)) link here for diagnosis. Runtime-agent request errors are on [agent troubleshooting](../agents/troubleshooting.md). Lifecycle vocabulary: [lifecycle terms](../concepts/lifecycle-terms.md).

## Cancellation

`tdp run` and `tdp resume` trap SIGINT/SIGTERM during the engine loop: tracked agent subprocesses are terminated, orphan agents are cleaned up, the run pauses with `stop.code: user_cancelled` when this process holds continuation ownership, and the CLI exits **130**.

| Situation | Durable run | `--stream-json` | Desktop notify |
| --- | --- | --- | --- |
| Owned interruption (this process holds continuation ownership) | `paused` / `user_cancelled`; `stop.details.terminated_pids` | `"cancelled": true` | Run-cancelled notification when notifications are enabled |
| Interrupt before ownership, or after ownership released without cancelling | Run record unchanged | `"cancelled": false`, `"command_interrupted": true` | No run-cancel notification |

Resume a durably cancelled run with `tdp resume --run <id> --config cfg.yaml`.

## Concurrency

Cross-process resume ownership uses POSIX `fcntl` flock on `.resume.lock.d/.owner.lock`. Two operators cannot continue the same run at once. Windows Python is not supported for multi-process resume locking. See [run ownership](../decisions/run-ownership.md).

`--force` on `tdp run` only allows **starting a new run** when paused runs still have orphan agents; it does not bypass ownership on resume.

## Common errors and diagnosis

| Symptom | What to do |
| --- | --- |
| `tdp run` missing runs dir | Pass `--runs-dir`, export `TDP_RUNS_DIR`, or set `runtime.runs_dir`. `run` / `prepare` / `execute` do not fall back to `./runs`. |
| Resume rejects config | Default: contract and non-model context_spec drift are rejected. Use `tdp resume --check` first. `--allow-config-drift` is a per-invocation hatch ([configuration](configuration.md#resume-and-drift)). |
| `limit_exhausted` | `stop.details` names the limit path and `consumed`. Candidate value must be **strictly greater** than consumed. Example: `--set limits.review.max_agent_turns_per_gate=<n>`. |
| Orphan agents / `status: running` with no live orchestrator | Idle between CLI steps is normal. If tagged leftovers remain, `tdp doctor --run <id>` then `tdp doctor --fix`. Pre-run orphan cleanup must **not** fail the run on unrelated macOS host processes. Leftover scans ignore Linux `TASK_DEAD` and Linux/Darwin zombies — those are not operator-actionable orphans. |
| Provider unavailable / turn stalled | Cursor missing from PATH, idle timeout (`limits.provider.turn_idle_timeout_seconds`, default `2`, `0` disables), or remote session gone. One replacement per `phase_action_id`; exhausted replacement fails with `session_recovery_exhausted` (not resumable as a normal pause). |
| `stream-json record exceeded` / `provider_turn_failed` | A single assembled Cursor stream-json line (including the terminating newline) exceeded `limits.provider.max_stream_json_record_bytes` (TDP default `1048576` / 1 MiB). The cap is independent of read/exit boundaries; drain **stops** at the cap; a valid first record can still be followed by oversized rejection; leftover flood writers must not remain on argv (adapter kills them, including when bound terminate fails closed or identity inspect is unverifiable; live-match kills use verified identity). Resume with `--set limits.provider.max_stream_json_record_bytes=<n>` (execution-limit change; allowed on resume, including when an older stored config omitted the key). This is an adapter bound, not a missing remote session. Cleanup detail: [session process cleanup](../architecture/sessions.md#process-cleanup). |
| `session_recovery_exhausted` or other `status=failed` | Invariant stop. Failed runs cannot be resumed. |
| Prepared child / attach refused | Parent must be `phase=sub_tdps` and `status=paused`. Child must be completed/accepted with whole-output approval. Do not hand-edit `production.json`. |
| Notifications never appear | Optional `[notifications]` extra not installed, `CI=true`, or headless Linux. Silently skipped. |
| Windows | Unsupported for multi-process locking and `CursorProvider`. |

`tdp resume --check` prints the resume plan without mutating the run or calling the provider. Prefer it before `--allow-config-drift` or limit increases.

## Safe recovery

1. Read `tdp status --run <id> --stream-json` (or human `tdp status`) for `status`, `phase`, `stop`, `outcome`.
2. Inspect artifacts with `tdp inspect` / `tdp validate` — do not edit `run.json`, `plan.json`, `production.json`, or `events.jsonl`.
3. If orphans or stale `running`, `tdp doctor` then `tdp doctor --fix` when you intend those kills/reconciles.
4. For operational pauses, `tdp resume --check`, then `tdp resume` with any required `--set` strictly above consumed limits.
5. For agent-side `revision_conflict` / evidence errors, the **agent** retries with a fresh snapshot ([agent troubleshooting](../agents/troubleshooting.md)); operators do not patch production.json.

Related: [run store](run-store.md), [observability](observability.md), [doctor CLI](cli.md).
