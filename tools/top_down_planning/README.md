# Top Down Planning (`tdp`)

Generic agent orchestration that receives an input and output goal, builds a high-level top-down plan, reviews and validates it, then produces output in coherent batches.

Specification: [`temp/final-top-down-planning-tool-proposal.md`](../../temp/final-top-down-planning-tool-proposal.md)

## Architecture layers (proposal §17)

| Layer | Package | Responsibility |
| --- | --- | --- |
| Core domain | `domain/` | Pure models and rules: plan tree, dependencies, validation, production state, outcomes. No CLI, provider, or persistence concerns. |
| Orchestrator | `orchestrator/` | Lifecycle transitions: plan → review → validate → produce → amend → review output → resolve outcome. |
| Agent tool | `agent_tool/` | Structured agent protocol: atomic domain operations with schema validation and revision checks. |
| Provider | `provider/` | Provider interface and adapters (Cursor CLI first). Session start/resume, streaming, capabilities. |
| Persistence | `persistence/` | `RunStore` interface and backends for canonical snapshots, events, and session references. |
| CLI | `cli/` | User-facing (`tdp run`, `tdp resume`, …) and agent-facing (`tdp agent …`) command wiring. |
| Config | `config/` | YAML configuration loading and `--set` override resolution. |

## Import boundaries

- `domain` must not import `cli`, `provider`, `persistence`, or `orchestrator`.
- `orchestrator` may depend on `domain` and interfaces; not on provider CLI parsing.
- Project-specific extensions stay outside the core package (proposal §19).

## Development

```bash
cd tools/top_down_planning
python -m pip install -e ".[dev]"
tdp --help
pytest
```
