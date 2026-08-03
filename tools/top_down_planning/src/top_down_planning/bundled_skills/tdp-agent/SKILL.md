---
name: tdp-agent
description: >-
  Runtime guide for TDP (Top Down Planning) agents: session env, discoverability,
  revision safety, and request-file workflow. Auto-injected with the role skill
  (planner, producer, or reviewer) on every session.
---

# TDP agent — shared protocol

You are a **runtime TDP agent** inside a provider session. Mutate run state only through `tdp agent` shell commands. The orchestrator does not consume host IDE planning artifacts or planning-only tools.

## Start here

1. `tdp agent help` — command summary
2. `tdp agent readme` — full protocol (authorization, workflow, run store)
3. `tdp agent schema <name>` / `tdp agent example <name>` — exact request shapes
4. Role skill content — already in `agent_context.skills` on this manifest (shared + planner, producer, or reviewer)

TDP injects packaged skills automatically (`agent_context.bundled_skills`, default true). No YAML wiring required.

## Session environment

Provider subprocesses export:

- `TDP_RUNS_DIR` — run store root
- `TDP_RUN_ID` — must match `--run`
- `TDP_AGENT_REQUESTS_DIR` — write mutating request JSON/YAML **only** here
- `TDP_CAPABILITY_TOKEN` — required for mutating commands; bound to phase and session role

Typical mutating invocation:

```bash
tdp agent plan apply --run <run-id> \
  --request $TDP_AGENT_REQUESTS_DIR/plan-apply-r<rev>-a01.json
```

Read-only commands (`snapshot`, `check`, `schema`, `example`, `run status`) do not need the token.

## Revision safety

| Command | Revision field | Source |
| --- | --- | --- |
| `plan apply` | `base_revision` | `plan snapshot` → `revision` |
| `production apply` | `production_revision` | `production snapshot` → `production_revision` |

Stale revisions return `revision_conflict` with instructions to refresh the snapshot.

## Completion signals

Emit as the **final assistant line** or `done.signal` metadata when work is ready:

| Role | Signal |
| --- | --- |
| Planner | `candidate_plan_ready` |
| Producer (batch) | `batch_complete` |
| Producer (amendment) | `amendment_revision_ready` |

## Request files

- JSON or YAML object via `--request` under `$TDP_AGENT_REQUESTS_DIR` or stdin
- List published schemas: `tdp agent schema`
- List published examples: `tdp agent example`
- Examples validate against schemas; copy structure from an example and adapt ids from the session package (review packages expose `rubric_items`, `required_audit_passes`, etc.)

## Do not

- Switch to host planning modes or create `.tdp-*` / `.review-*` dotfiles in the workspace
- Modify orchestrator-owned run files under the run store
- Pass `--role` on the CLI (authorization is session-bound)
- Wrap `tdp` with `uv run` inside provider turns
- Read TDP Python source to discover `review respond` payload shapes

## Further reading

- Agent hub: `tools/top_down_planning/docs/README.md`
- Full protocol: `tdp agent readme`
- Operator docs: `tools/top_down_planning/README.md`
