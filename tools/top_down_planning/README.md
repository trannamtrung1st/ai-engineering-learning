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
- `stub` — deterministic scripted turns for tests; call `script_turn()` before each provider turn.

Use `provider.name=stub` in tests and local orchestration runs. Production runs default to `cursor`.

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

`tdp run` creates the run store, starts the primary planner session, and drives planning construction until the planner signals `candidate_plan_ready` or a planning limit is hit. On success the run transitions to phase `whole_plan_review`. `tdp resume` continues an in-progress `planning` phase using the persisted `primary_planner_session_id`, drives the mandatory whole-plan review loop when the run is in `whole_plan_review`, or drives production when the run is in `plan_validated` or `production`.

Whole-plan review (proposal §5.2, §11): the orchestrator starts a fresh reviewer session per loop, binds findings to the current plan revision, resumes the same primary planner for revisions after `changes_requested`, and requires the same reviewer to recheck before approval. After approval, deterministic `validate_plan(..., mode="approval")` must pass before the run advances to `plan_validated`. Revision cycles are capped by `limits.whole_plan_review.max_revision_cycles`; limit exhaustion yields `rejected` or `blocked`, never silent acceptance.

Production (proposal §10): after `plan_validated`, `tdp resume` starts the primary producer session, transitions to `production`, and records agent-selected batches via `tdp agent production apply` until every applicable item has a terminal disposition. The producer then submits a completion claim via `tdp agent production submit-completion` before the run advances to `whole_output_review`. Batch limits use `limits.production.max_batches` and `limits.production.max_agent_turns_per_batch`. Plan mutations are rejected during production; producers may request a controlled amendment via `tdp agent production request-amendment`.

## Agent CLI

```bash
tdp agent plan snapshot --run <run-id> --view tree
tdp agent plan apply --run <run-id> --role planner --request request.json
tdp agent plan check --run <run-id>
tdp agent production snapshot --run <run-id> --view ready
tdp agent production apply --run <run-id> --role producer --request request.json
tdp agent production check --run <run-id>
tdp agent production request-amendment --run <run-id> --role producer --request request.json
tdp agent production submit-completion --run <run-id> --role producer --request request.json
tdp agent production report-blocked --run <run-id> --role producer --request request.json
tdp agent review respond --run <run-id> --role reviewer --request review.json
tdp agent run status --run <run-id>
```

Production apply requires `production_revision` from the latest snapshot. `submit-completion` records a completion claim only; the orchestrator advances to whole-output review after a valid claim and sets final `outcome` only after whole-output review.

## Development

```bash
cd tools/top_down_planning
python -m pip install -e ".[dev]"
tdp --help
pytest                  # unit tests (default; excludes integration)
pytest -m integration   # multi-layer smoke test
pytest -m ""            # full suite
```
