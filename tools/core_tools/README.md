# Core Tools (`core_tools`)

Cross-product infrastructure shared by agent orchestration tools in this monorepo.

## What belongs here

| Module | Contents |
| --- | --- |
| `core_tools.provider` | Provider protocol, stub/Cursor adapters, stream normalization (`text` or `message.content`), tool-call filtering (`subtype: started` only; `tool_result` and completed calls dropped), session references, subprocess cleanup. Cursor non-interactive argv uses `--print --output-format stream-json --trust --approve-mcps --force` so shell/`tdp agent` tool calls are not rejected. `terminate_all_sessions()` stops in-flight CLI process trees so orchestrators do not leave orphaned background agent subprocesses. |
| `core_tools.config` | Deep merge, YAML config load, `--set` override parsing, workspace paths, resource/skill loading, allowlist validation |
| `core_tools.persistence` | Atomic file writes, content digests, minimal YAML helpers, optimistic revision helpers, cross-platform advisory file locks (`fcntl` on Unix, `msvcrt` on Windows) |
| `core_tools.cli` | Structured CLI output, request loading, runs-dir resolution |
| `core_tools.observability` | Structured `ConsoleEvent` model, `EventSink` protocol, redaction, colorized stderr console renderer (prefix on first line of each category block; consecutive same-category events share one block), JSONL sinks, agent text sentence streaming (`AgentTextStreamController`) |
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
