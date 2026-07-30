# Top Down Planning (`tdp`)

Generic agent orchestration that receives an input and output goal, builds a high-level top-down plan, reviews and validates it, then produces output in coherent batches.

Specification: [`temp/final-top-down-planning-tool-proposal.md`](../../temp/final-top-down-planning-tool-proposal.md)

## Quickstart

```bash
cd tools/top_down_planning
python -m pip install -e ../core_tools -e ".[dev]"

tdp agent help
tdp agent schema plan-transaction
tdp agent example expand-branch

tdp run --config examples/top-down-planning.yaml
tdp status --run <run-id>
tdp resume --run <run-id>
```

The default provider is `cursor` (requires the Cursor CLI on PATH). For deterministic
orchestration tests, use `provider.name=stub` with `script_turn()` in unit/integration
tests — not as an interactive `tdp run` quickstart.

## Architecture layers (proposal §17)

| Layer | Package | Responsibility |
| --- | --- | --- |
| Core domain | `domain/` | Pure models and rules: plan tree, dependencies, validation, production state, outcomes. No CLI, provider, or persistence concerns. |
| Orchestrator | `orchestrator/` | Lifecycle transitions: plan → review → validate → produce → amend → review output → resolve outcome. |
| Agent tool | `agent_tool/` | Structured agent protocol: atomic domain operations with schema validation and revision checks. |
| Shared infra | [`core_tools`](../core_tools) | Provider adapters, generic config merge/overrides, atomic writes, content digests, YAML helpers. |
| Persistence | `persistence/` | `RunStore` interface and `FileRunStore` for canonical snapshots, events, and session references. |
| CLI | `cli/` | User-facing (`tdp run`, `tdp resume`, …) and agent-facing (`tdp agent …`) command wiring. |
| Config | `config/` | TDP schema (`DEFAULT_CONFIG`, allowed override paths) and `resolve_config`. |

## Provider (proposal §16)

Provider adapters live in `core_tools.provider`. Resolved configuration selects the adapter:

```yaml
provider:
  name: cursor          # cursor | stub
  model: composer-2.5   # optional Cursor model
  binary: /path/to/agent  # optional; otherwise agent or cursor-agent on PATH
  skip_probe: false     # skip CLI version probe when true
```

- `cursor` — thin Cursor CLI adapter (`--print --output-format stream-json`). Session ids returned by the CLI stream are stored on the run record (`sessions.primary_*_session_id`). `get_session_reference` is available on the provider for durable ref export; orchestrators persist the session id directly today.
- `stub` — deterministic scripted turns for **tests only**; call `script_turn()` before each provider turn.

Production runs default to `cursor`. Use `provider.name=stub` only in unit/integration tests.

## Import boundaries

- `domain` must not import `cli`, `persistence`, `orchestrator`, or `core_tools`.
- Shared provider/config/persistence primitives live in [`core_tools`](../core_tools); TDP imports them at orchestrator, CLI, and persistence boundaries.
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

Configuration precedence: built-in defaults → YAML file → repeated `--set path=value` overrides. Unknown paths in YAML or `--set` are rejected. Resolved configuration is materialized to `runs/<run-id>/resolved-config.yaml` and included in the run config digest.

Run operational `status` values (proposal §15): `running`, `paused`, `completed`, `failed`. Quality `outcome` values: `accepted`, `rejected`, `blocked` (set only by orchestrator outcome resolution).

`tdp run` creates the run store, starts the primary planner session, and drives planning construction until the planner signals `candidate_plan_ready` or a planning limit is hit. On success the run transitions to phase `whole_plan_review`. `tdp resume` validates digests and session references before continuing: config/plan/input/output-goal/output digests must match the materialized store, missing primary session refs block resume (no silent new sessions), active whole-plan and whole-output review loops require a persisted `reviewer_session_id`, and production/output review require whole-plan approval for the current plan revision. Resume then continues `planning` with the persisted `primary_planner_session_id`, drives the mandatory whole-plan review loop in `whole_plan_review`, drives production in `plan_validated` or `production`, and drives whole-output review in `whole_output_review`.

Whole-plan review (proposal §5.2, §11): the orchestrator starts a fresh reviewer session per loop, binds findings to the current plan revision, resumes the same primary planner for revisions after `changes_requested`, and requires the same reviewer to recheck before approval. After approval, deterministic `validate_plan(..., mode="approval")` must pass before the run advances to `plan_validated`. Revision cycles are capped by `limits.whole_plan_review.max_revision_cycles`; limit exhaustion yields `rejected` or `blocked`, never silent acceptance.

Focused reviews (proposal §4.3, §5.1): during `planning` or `production`, the primary planner or producer may request optional `focused_plan` or `focused_output` reviews via `tdp agent review request` with bounded `scope.item_ids`. Each request starts a fresh reviewer session; the same reviewer rechecks within the loop. Focused approval does not substitute for mandatory whole-plan or whole-output gates. Limits use `review.focused_plan.enabled`, `review.focused_output.enabled`, and `limits.focused_plan_review` / `limits.focused_output_review`. Unresolved blocking findings in an active focused loop block `candidate_plan_ready`, `production_apply`, and `submit-completion` for overlapping items. Plan `ready` snapshots block on `focused_plan` / `whole_plan` findings; production `ready` snapshots block on `focused_output` / `whole_output` findings.

Production (proposal §10): after `plan_validated`, `tdp resume` starts the primary producer session, transitions to `production`, and records agent-selected batches via `tdp agent production apply` until every applicable item has a terminal disposition. The producer then submits a completion claim via `tdp agent production submit-completion` with `goal_met: true` and a `goal_assessment` rationale before the run advances to `whole_output_review`. Batch limits use `limits.production.max_batches` and `limits.production.max_agent_turns_per_batch`. Plan mutations are rejected during production; producers may request a controlled amendment via `tdp agent production request-amendment` (not available during whole-output review).

Plan amendment (proposal §10.4): when production exposes a material plan defect, the producer requests amendment with evidence and affected plan refs. The orchestrator pauses production (`status: paused`, phase `plan_amendment`), resumes the same primary planner to revise the plan, runs mandatory whole-plan review on the amended revision, reconciles production evidence against the prior plan snapshot (clearing dispositions for changed/removed items, marking overlapping batches `invalidated_by_reconciliation`, dropping related `output_evidence`, and recording `invalidated_item_ids` on the reconciliation report), then resumes the same primary producer with the reconciliation report. Output digests bind live evidence only — invalidated batches remain in the audit history but are excluded from digest and reviewer snapshots. Amendment limits use `limits.amendment.max_requests` and `limits.amendment.max_revision_cycles_per_request`. Production batches, completion claims, and blocker reports are rejected while an amendment is pending. `tdp resume` routes in-flight amendments through `PlanAmendmentOrchestrator` when `pending_amendment_id` is set and the run is in `plan_amendment`, `whole_plan_review`, or `plan_validated`; production-phase resume with a pending amendment is handled inside `ProductionPhaseOrchestrator`.

Whole-output review (proposal §5.3, §12.2, §15, §21): after production completion, `tdp resume` starts a fresh reviewer session bound to the current `output_revision`, resumes the same primary producer for revisions after `changes_requested` with instructions to use `production apply` and `evidence_revision: true` on terminal items targeted by unresolved blocking findings (dispositions unchanged), then re-submit completion with `goal_met: true`. Deterministic output validation plus the acceptance invariant must pass before the orchestrator sets `outcome: accepted`. Revision cycles are capped by `limits.whole_output_review.max_revision_cycles`. Deterministic validation failures after reviewer approval yield `blocked`; limit exhaustion yields `rejected`. Provider/orchestrator operational failures set `status: failed` without a quality outcome — `failed` is operational only and is not conflated with `rejected`.

`tdp validate` runs deterministic plan validation and, when a completion claim or whole-output review exists, output validation as well.

## Agent CLI

```bash
tdp agent help
tdp agent readme
tdp agent schema              # list schemas; add a name to show one
tdp agent example expand-branch
tdp agent plan snapshot --run <run-id> --view tree
tdp agent plan apply --run <run-id> --role planner --request request.json
tdp agent plan check --run <run-id>
tdp agent production snapshot --run <run-id> --view ready
tdp agent production apply --run <run-id> --role producer --request request.json
tdp agent production check --run <run-id>
tdp agent production request-amendment --run <run-id> --role producer --request request.json
tdp agent production submit-completion --run <run-id> --role producer --request request.json
tdp agent production report-blocked --run <run-id> --role producer --request request.json
tdp agent review request --run <run-id> --role planner --request focused-review.json
tdp agent review respond --run <run-id> --role reviewer --request review.json
tdp agent run status --run <run-id>
```

Production apply requires `production_revision` from the latest snapshot. `submit-completion` requires `goal_met: true` plus `goal_assessment` and records a completion claim only; the orchestrator advances to whole-output review after a valid claim and sets final `outcome` only after whole-output review. During `whole_output_review`, use `evidence_revision: true` on `production apply` to revise terminal items targeted by unresolved blocking findings (see `tdp agent example evidence-revision`).

Agent plan `snapshot`/`check`/`apply` and production `snapshot` (tree/ready) share the same
plan validation contract: structured `issues` for errors, string `warnings` for
non-blocking findings, and `ok` when validation has no error-severity issues.
Production-specific batch checks use `production check`. Tree snapshots include
`scope`, `boundaries`, and `acceptance` on each item. `plan apply` also sets
`applied: true` when the mutation batch was persisted (exit code still reflects
`ok`, not whether the batch was saved). Plan apply persists `plan.json`,
`run.json` digests, and `events.jsonl` as separate atomic writes — not one
cross-file transaction.

`tdp agent plan snapshot`, `plan apply`, and `plan check` exit 0 only when
`ok` is true. `production snapshot` and `production check` follow the same rule.
`plan apply` may return `applied: true` with exit 1 when post-apply validation
reports errors. `production apply` returns `ok: true` when the batch was
persisted; use `production snapshot` or `production check` for plan validation.

When planning dependencies, prefer the narrowest meaningful plan item as the dependency target (e.g. depend on a leaf API item rather than its parent epic) so readiness and production batching stay precise.

## Development

```bash
cd tools/top_down_planning
python -m pip install -e ../core_tools -e ".[dev]"
tdp --help
pytest                  # unit tests (default; excludes integration)
pytest -m integration   # stub-provider e2e and smoke tests
pytest -m ""            # full suite
```
