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

## Provider (proposal §16)

Resolved configuration selects the provider adapter:

```yaml
provider:
  name: cursor          # cursor | stub
  use_native_project_context: true
  model: composer-2.5   # optional Cursor model
  binary: /path/to/agent  # optional; otherwise agent or cursor-agent on PATH
  skip_probe: false     # skip CLI version probe when true
```

- `cursor` — thin Cursor CLI adapter (`--print --output-format stream-json`). Session ids are the provider chat ids returned from the CLI stream (persist via `get_session_reference`).
- `stub` — deterministic scripted turns for tests; requires `script_turn()` before each turn.

Tests and orchestrator integration use `provider.name=stub` by default. Live Cursor is optional (smoke test skips when the CLI is missing).

## Import boundaries

- `domain` must not import `cli`, `provider`, `persistence`, or `orchestrator`.
- `orchestrator` may depend on `domain` and interfaces; not on provider CLI parsing.
- Project-specific extensions stay outside the core package (proposal §19).

## User CLI (proposal §20)

```bash
tdp run --config examples/top-down-planning.yaml
tdp run --config examples/top-down-planning.yaml --set planning.max_depth=5
tdp status --run <run-id>
tdp inspect --run <run-id> --view tree
tdp validate --run <run-id>
tdp resume --run <run-id>
```

Configuration precedence: built-in defaults → YAML file → repeated `--set path=value` overrides. Unknown `--set` paths are rejected. Resolved configuration is materialized to `runs/<run-id>/resolved-config.yaml` and included in the run config digest.

Run operational `status` values (proposal §15): `running`, `paused`, `completed`, `failed`. Quality `outcome` values: `accepted`, `rejected`, `blocked` (set only by orchestrator outcome resolution).

`tdp run` creates the run store artifacts then exits before planning orchestration is wired. `tdp resume` loads the run and exits until resume orchestration is wired.

## Agent CLI

```bash
tdp agent plan snapshot --run <run-id> --view tree
tdp agent plan apply --run <run-id> --role planner --request request.json
tdp agent plan check --run <run-id>
tdp agent run status --run <run-id>
```

## Development

```bash
cd tools/top_down_planning
python -m pip install -e ".[dev]"
tdp --help
pytest
```
