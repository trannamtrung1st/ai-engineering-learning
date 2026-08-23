# Agent session architecture

**Audience:** maintainers working on provider sessions, context, and process lifetime.

Operator-visible flow: [agent sessions](../workflows/agent-sessions.md). Protocol: [agents](../agents/README.md). Replacement rationale: [session bindings](../decisions/session-bindings.md). Security: [security](../internals/security.md).

Python field names below are persisted maintainer vocabulary, not a CLI API.

## Bindings

Provider sessions are stored as structured bindings on `run.sessions`:

- `primary_planner`, `primary_producer` — one primary session per those roles
- each review loop’s `reviewer_binding`

Each binding carries `session_instance_id`, `generation`, `provider_session_id`, `state`, `role`, and `kind` (`primary` or `reviewer`). States: `unbound`, `starting`, `bound`.

The Cursor adapter registers in-memory sessions under transient `cursor-pending-*` handles until stream-json emits a durable `session_id`. Orchestration persists durable ids during the turn (`state: bound`). **Transient pending handles are never passed to Cursor `--resume`.** A Cursor turn that completes without a durable `session_id` fails.

Resume of a torn-down in-memory adapter rebinds the persisted durable id through Cursor `--resume` when the next phase step starts.

## Effective context

Session context merges `agent_context.default` → role → activity. Activities and their roles (`config/activities.py`):

| Activity | Role |
| --- | --- |
| `initial_plan`, `plan_revision`, `plan_amendment` | planner |
| `production`, `output_revision` | producer |
| `initial_review`, `finding_verification`, `scope_review` | reviewer |

`run.input_refs` and the output goal are attached automatically; do not duplicate them as resources. Packaged skills inject when `agent_context.bundled_skills` is true. Guidance is advisory and is not merged into `protocol_instructions`.

Supporting context uses a **spec vs snapshot** split (`digests.context_spec` vs `digests.context_snapshot`). Resume of a session requires the same role, activity, and context digest; an activity change starts a fresh provider session. Digest rules: [config and snapshots](../internals/config-and-snapshots.md).

## Activity and phase boundaries

The orchestrator binds **one** primary planner, producer, or reviewer session per phase step and issues a capability token for that subprocess. Stream-event sync **reuses the live exported token** (`read_exported_live_capability_token`); it must not mint a new token per streamed event. Reissue only when the exported token file is gone or no longer live for that binding (`tests/unit/test_reviewer_capability_stream_rebind.py`). Reviewer sessions allocate a provider session id, bind the token, then deliver the review package before `review respond`. Tokens are revoked when the turn, loop, or phase ends. Agents do not pass `--role`. [Authorization](../decisions/agent-authorization.md).

Producer batch and completion-claim boundaries abort the in-flight provider turn, wait until the collector settles, then queue the next turn on the same session. Reviewer `respond` releases the bounded reviewer session after settle. Owner `record-actions` closes advisory turns.

## Replacement and recovery

Missing remote sessions (`provider_session_not_found`) and idle stalls (`ProviderTurnStalledError` when `limits.provider.turn_idle_timeout_seconds` > 0; TDP default `2`, `0` disables) each allow **one** replacement per `phase_action_id` with a recovery manifest. Lineage reasons: `provider_session_not_found` or `provider_turn_stalled`. Exhausted replacement fails the run (`session_recovery_exhausted`). An oversized assembled stream-json line including the terminating newline (`limits.provider.max_stream_json_record_bytes`, TDP default `1048576` / 1 MiB) fails the turn as `provider_turn_failed` and does not consume that replacement budget.

The Cursor adapter enforces that cap independently of read/exit boundaries (`core_tools` stream-json tests): drain **stops** once the assembled record exceeds the cap (EOF drain does not slurp the rest of a flood); a valid buffered prefix can still be followed by an oversized rejection; oversized flood writers must not remain live on argv after the failed turn. Resume may **introduce** `limits.provider.max_stream_json_record_bytes` when an older stored config omitted the key (execution-limit allowlist). Cap-rejection teardown: [Process cleanup](#process-cleanup).

## Process cleanup

Agent turns run on background collector threads. Every subprocess pid is tracked. `abort_turn()` stops the current turn’s process; callers that must block until the collector finishes pair it with `wait_turn_settled()`. `terminate_all_sessions()` kills tracked pids (SIGTERM then SIGKILL). After each phase step, including user cancel, the engine tears down active sessions and emits durable cancel/end audit events. Bounded reviewer sessions are dropped from the in-memory registry when a terminal review decision is recorded.

Stream-json cap rejection kills leftover flood writers, including when bound terminate fails closed and when identity inspect is unverifiable. When process identity is available and a live match, oversized writers are terminated only through **verified** identity (stale PGIDs are not killed). Leftover hold processes are reaped. Teardown waits past janitor SIGTERM drain; leftover teardown **fails on the original leak**, not on post-reap emptiness. Leftover scans ignore Linux `TASK_DEAD` (`X` after leftover SIGKILL), Linux zombies (`/proc` stat `Z`), and Darwin leftover zombies (ps state column). Pre-run orphan cleanup must not fail the run on unrelated macOS host processes (for example `/sbin/launchd`). Janitor wait budget is recorded at both the status-read and `raw_wait` edges (status-read time is deducted from one deadline; it is not wall-clock slack).

`RunEngine.continue_run` scans for orphan agents. Orphans on **completed** and **failed** runs still count. `tdp doctor --fix` kills leftovers. Cursor construction and process-tree termination are POSIX-only.

Related: [lifecycle architecture](lifecycle.md), [system context](system-context.md).
