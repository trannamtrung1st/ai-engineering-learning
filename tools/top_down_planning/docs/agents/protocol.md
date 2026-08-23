# Shared agent protocol

**Audience:** runtime TDP agents (planner, producer, reviewer) inside provider sessions.

Mutate run state only through `tdp agent` shell commands. The orchestrator does not consume host IDE planning artifacts. Write mutating request payloads only under `$TDP_AGENT_REQUESTS_DIR`. Do not create `.tdp-*` or `.review-*` dotfiles in the workspace, and do not modify orchestrator-owned run files.

Command names and request fields on this page come from `tdp agent help` and `tdp agent readme`. Copy payload shape from `tdp agent example <name>`.

## Session environment

Provider subprocesses export:

| Variable | Meaning |
| --- | --- |
| `TDP_RUNS_DIR` | Run store root |
| `TDP_RUN_ID` | Must match `--run` when capability context is active |
| `TDP_AGENT_REQUESTS_DIR` | Write mutating JSON/YAML request files only here |
| `TDP_CAPABILITY_TOKEN_FILE` | Orchestrator-written current token; mutating CLI reads it at invocation time |

Typical mutating invocation:

```bash
tdp agent plan apply --run <run-id> \
  --request $TDP_AGENT_REQUESTS_DIR/plan-apply-r<rev>-a01.json
```

Read-only commands (`snapshot`, `check`, `schema`, `example`, `run status`) do not need the token. Do not pass `--role` on the CLI. Do not wrap `tdp` with `uv run` inside provider turns. Authorization is bound to run phase and session role. Details: [agent CLI](cli.md).

## Request files

- JSON or YAML object via `--request` under `$TDP_AGENT_REQUESTS_DIR`, or stdin
- Paths passed to `--request` must resolve inside `agent-requests/`
- Request files are durable for debugging and are not canonical run state (not required for resume)
- List contracts: `tdp agent schema` / `tdp agent example`

Each mutating invocation emits correlated `agent_request_read` and `agent_request_completed` audit events linked by `request_id`. Discover `agent_requests_dir` with `tdp agent run status --run <id>`.

## Revision safety

| Command | Revision field | Source |
| --- | --- | --- |
| `plan apply` | `base_revision` | `plan snapshot` → `revision` |
| `production apply` | `production_revision` | `production snapshot` → `production_revision` |
| `submit-completion` | `production_revision` | same production snapshot |

Stale revisions return `revision_conflict`. Refresh the snapshot and retry with the current revision. [Troubleshooting](troubleshooting.md).

Review `respond` and `record-actions` bind `target_revision` and `target_digest` to the current artifact in the review package. Stale digests are rejected.

## Completion signals

Emit as the **final assistant line** or `done.signal` metadata when the protocol still uses a signal. Several producer and reviewer turns close on a **persisted command** instead of a token:

| Role | How the turn closes |
| --- | --- |
| Planner | Emit `candidate_plan_ready` |
| Planner (amendment) | Emit `amendment_revision_ready` |
| Producer (batch) | `production apply` persists a batch |
| Producer (completion) | `submit-completion` persists a valid completion claim |
| Reviewer | `review respond` persists a decision |
| Owner advisory | `review record-actions` persists |

After `production apply` or `submit-completion`, stop working on that turn. No summary or cleanup turn is required. After `review respond`, the orchestrator releases the bounded reviewer session. A turn that ends without `review respond` queues another reviewer turn (bounded by `limits.review.max_agent_turns_per_gate`) before pausing with `limit_exhausted`.

A background poll watches for persisted batches, completion claims, owner record-actions, and review decisions while the turn is open so a stalled agent subprocess cannot block progress after the command succeeds.

## Session packages

Planner and producer sessions receive a context manifest. Reviewer sessions receive a review package. Follow `protocol_instructions` and `tool_instructions`. `agent_context.guidance` is advisory and is not merged into `protocol_instructions`. Packaged TDP agent skills are auto-injected when `agent_context.bundled_skills` is true (default).

Producer packages include `approved_plan` with canonical item contracts. Review packages include plan metadata, `review_policy`, and — for mandatory whole-plan/whole-output — `rubric_items`, `required_audit_passes`, and `analysis_context`. Shape `review respond` from `tdp agent readme` and stage examples, not from TDP Python source.

Related: [planner](planner.md), [producer](producer.md), [reviewer](reviewer.md), [roles](../concepts/roles.md).
