# Core Tools (`core_tools`)

Cross-product infrastructure shared by agent orchestration tools in this monorepo.

## What belongs here

| Module | Contents |
| --- | --- |
| `core_tools.provider` | Provider protocol, stub/Cursor adapters, stream normalization (`text` or `message.content`), tool-call lifecycle events (`subtype: started` and `completed`; `tool_result` dropped), session references, `list_active_sessions()` (sessions currently retained in the in-memory registry; `session_id`, `role`, `kind`, `model`), subprocess cleanup. Normalized stream events carry `session_id`; model labels live on session references and lifecycle audit events only. Session payloads use `format_manifest_prompt` / `format_request_prompt`, surfacing optional `protocol_instructions` (Markdown string) before the JSON body. Cursor non-interactive argv uses `--print --output-format stream-json --trust --approve-mcps --force` so shell/`tdp agent` tool calls are not rejected. Transient in-memory `cursor-pending-*` handles are never passed to Cursor `--resume`. Cursor turns run on background collector threads; `abort_turn()` clears buffered stream events, stops the tracked subprocess, wakes `stream_events` waiters, and keeps the durable session for follow-up turns; callers that must block until the collector finishes pair `abort_turn()` with `wait_turn_settled()`; `wait_turn_settled()` also blocks before `_queue_turn` accepts the next prompt; `terminate_all_sessions()` kills every tracked agent subprocess pid (SIGTERM grace period, then SIGKILL) and returns termination records for orchestrator audit events. The default process runner stops reading stdout once the child exits so exited/zombie subprocesses cannot block turn drain indefinitely. `limits.provider.turn_idle_timeout_seconds` (product config; default `0` disables) ends a turn when no stream-json stdout arrives within the interval and raises `ProviderTurnStalledError` (not retried by `max_retries_per_call`). |
| `core_tools.config` | Deep merge, YAML config load, `--set` override parsing, workspace paths, resource/skill loading, allowlist validation |
| `core_tools.persistence` | Atomic file writes, content digests, minimal YAML helpers, optimistic revision helpers, cross-platform advisory file locks (`fcntl` on Unix, `msvcrt` on Windows) |
| `core_tools.cli` | Structured CLI output, request loading, runs-dir resolution |
| `core_tools.observability` | Structured `ConsoleEvent` model, `EventSink` protocol, redaction (`RedactionPolicy` with opt-in `max_message_length`; unlimited by default), colorized stderr console renderer (discrete category blocks vs incremental `thinking`/`response` deltas; explicit `\n` in agent text breaks lines within a block), JSONL sinks (thinking/response aggregated per block), agent text delta streaming (`AgentTextStreamController`) |
| `core_tools.schema` | Minimal JSON Schema validation for published contracts |

## What stays in product packages

Product packages (e.g. `top_down_planning`, a future todos tool) own:

- Domain models and business rules (plan trees, readiness, dispositions, outcomes)
- Orchestrator lifecycle (planning, review loops, amendment, production)
- Agent tool surfaces and product CLIs (`tdp`, etc.)
- Run-store layout and product config schemas (`DEFAULT_CONFIG`, allowed override paths, role/phase merge policies)

## Consumers

- [`top_down_planning`](../top_down_planning) — top-down planning and production orchestration
- Future todos tool — will depend on `core_tools` instead of forking TDP internals

## Install

```bash
cd tools/core_tools
python -m pip install -e ".[dev]"
```

When working on a product package, install both packages (product `pyproject.toml` depends on `core-tools`):

```bash
python -m pip install -e tools/core_tools -e "tools/top_down_planning[dev]"
```

## Import boundary

`core_tools` must not import product packages. Product packages may import `core_tools` for shared infra only.
