# Top Down Planning (`tdp`)

Planning and production orchestration: receive an input and output goal, build a top-down plan, review and validate it, produce output in coherent batches, and resolve a final quality outcome.

Specification: [`docs/spec.md`](docs/spec.md)

## Quickstart

```bash
cd tools/top_down_planning
python -m pip install -e ../core_tools -e ".[dev]"
cd ../..

tdp agent help
tdp agent schema plan-transaction
tdp agent example expand-branch

tdp run --config tools/top_down_planning/examples/top-down-planning.yaml
tdp run --config tools/top_down_planning/examples/top-down-planning.yaml --until validated
tdp status --run <run-id> --config tools/top_down_planning/examples/top-down-planning.yaml
tdp resume --run <run-id> --config tools/top_down_planning/examples/top-down-planning.yaml
tdp resume --run <run-id> --until completed --config tools/top_down_planning/examples/top-down-planning.yaml
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
| Shared infra | [`core_tools`](../core_tools) | Provider adapters; config merge/overrides, workspace paths, resource/skill loading, allowlist validation; atomic writes and digests; revision helpers; CLI emit/request/runs-dir resolution; minimal JSON Schema validation. |
| Persistence | `persistence/` | `RunStore` interface and `FileRunStore` for canonical snapshots, events, and session references. |
| CLI | `cli/` | User-facing (`tdp run`, `tdp resume`, …) and agent-facing (`tdp agent …`) command wiring. |
| Config | `config/` | TDP schema (`DEFAULT_CONFIG`, allowed override paths) and `resolve_config`. |

## Provider (proposal §16)

Provider adapters live in `core_tools.provider`. Resolved configuration selects the adapter:

```yaml
provider:
  name: cursor          # cursor | stub
  binary: /path/to/agent  # optional; otherwise agent or cursor-agent on PATH
  skip_probe: false     # skip CLI version probe when true
```

Per-role model selection uses `agent_context.<role>.model`, falling back to `agent_context.default.model`. `model: auto` means no explicit Cursor `--model` argument.

- `cursor` — thin Cursor CLI adapter (`--print --output-format stream-json --trust --approve-mcps --force`). `--force` is required so non-interactive turns can run shell/`tdp agent …` tools; without it those calls are rejected. Session ids returned by the CLI stream are stored on the run record (`sessions.primary_*_session_id`). `get_session_reference` is available on the provider for durable ref export; orchestrators persist the session id directly today. After each phase step (including user cancel via Ctrl+C), `RunEngine` lists active provider sessions, emits `[session:end]` for each, then calls `terminate_all_sessions()` so in-flight CLI process trees are stopped and background agent subprocesses are not left running.
- `stub` — deterministic scripted turns for **tests only**; call `script_turn()` before each provider turn.

Production runs default to `cursor`. Use `provider.name=stub` only in unit/integration tests.

## Console observability

`tdp run` and `tdp resume` always stream progress logs to **stderr** (including with `--stream-json`). Final structured command payloads remain on **stdout**. The reusable observability layer lives in `core_tools.observability`; TDP wires it through CLI flags, provider event callbacks, and an observing run-store decorator that mirrors `events.jsonl` audit records to the console.

```bash
tdp run --config tools/top_down_planning/examples/top-down-planning.yaml \
  --log-level verbose --color auto

tdp run --config tools/top_down_planning/examples/top-down-planning.yaml \
  --stream-json | jq .    # progress on stderr; JSON payload on stdout

tdp run --config tools/top_down_planning/examples/top-down-planning.yaml \
  --log-format jsonl --no-color

tdp resume --run <run-id> --config tools/top_down_planning/examples/top-down-planning.yaml \
  --agent-transcript   # optional agent-transcript.jsonl under the run dir
```

| Flag | Default | Purpose |
| --- | --- | --- |
| `--color auto\|always\|never` | from config / `auto` | Color mode (`--no-color` ⇒ `never`) |
| `--log-level quiet\|normal\|verbose\|trace` | from config / `normal` | Verbosity |
| `--log-format console\|jsonl` | from config / `console` | Human console vs JSONL on stderr |
| `--agent-text` / `--no-agent-text` | from config / on | Show thinking/response text (streamed incrementally) |
| `--timestamps` / `--no-timestamps` | from config / off | Category prefix on the first line of each event; optional timestamp when enabled (streaming `thinking`/`response` blocks share one prefix) |
| `--agent-transcript` / `--no-agent-transcript` | from config / off | Persist redacted provider transcript |

Observability can be set in YAML under `observability` (same file as orchestration config). Precedence for presentation settings: built-in defaults → YAML → `--set` → explicitly supplied dedicated CLI flag (omitted flags do not override YAML). Changing observability or `runtime.runs_dir` does not invalidate resume; semantic config digests exclude those fields.

Provider thinking and response text is normalized from Cursor `stream-json` (`text` field or `message.content`), deduplicated when cumulative, and printed incrementally as new characters arrive. Empty thinking chunks are dropped. Explicit `\n` in agent text breaks lines within a thinking/response block; multiple sentences without newlines stay on one line until another category interrupts.

Tool invocations print as `[tool:start]` and `[tool:end]` with a concise summary from the normalized provider event (`summary` field). Cursor native tools are summarized from the nested `tool_call` payload; structured Top Down Planning agent tools summarize from `tool` and `request` (for example `plan_apply @r0 3 ops`). `tool_call` events with `subtype: started` or `completed` reach the console bridge; `tool_result` events and duplicate lifecycle events for the same `call_id` are dropped.

Console output prints `[category]` once per discrete event block (optional `[timestamp]` when `show_timestamps` is enabled). `thinking` and `response` stream incrementally with one prefix per block; explicit `\n` in agent text breaks lines within the block.

Agent session lifecycle: `[session:start]` on `planner_session_started` / `producer_session_started` / `reviewer_session_started` audit events (`phase`, `role`, `run_id`, `session_id` required); `[session:end]` when the engine tears down provider sessions after each blocking phase step or Ctrl+C cancel.

`events.jsonl` remains a concise orchestration audit log (no agent prose). Capability tokens, secrets, and oversized payloads are redacted at every log level.

`tdp run` and `tdp resume` handle Ctrl+C without a traceback: the engine stops provider subprocesses, emits a `[session:cancel]` line on stderr, emits `[session:end]` for each active provider session, leaves the run in `running` status for resume, and exits with code 130. With `--stream-json`, stdout carries `{"cancelled": true, "reason": "cancelled by user", ...}`.

## Import boundaries

- `domain` must not import `cli`, `persistence`, `orchestrator`, or `core_tools`.
- Shared provider/config/persistence primitives live in [`core_tools`](../core_tools); TDP imports them at orchestrator, CLI, and persistence boundaries.
- Project-specific extensions stay outside the core package (proposal §19).

## User CLI (proposal §20)

```bash
tdp run --config tools/top_down_planning/examples/top-down-planning.yaml
tdp run --config tools/top_down_planning/examples/top-down-planning.yaml --set planning.max_depth=5
tdp status --run <run-id> --config tools/top_down_planning/examples/top-down-planning.yaml
tdp inspect --run <run-id> --view tree --config tools/top_down_planning/examples/top-down-planning.yaml
tdp validate --run <run-id> --config tools/top_down_planning/examples/top-down-planning.yaml
tdp resume --run <run-id> --config tools/top_down_planning/examples/top-down-planning.yaml
```

Configuration precedence: built-in defaults → YAML file → repeated `--set path=value` overrides → dedicated CLI flags when explicitly supplied. Unknown paths in YAML or `--set` are rejected. Resolved configuration is materialized to `<runs-root>/<run-id>/resolved-config.yaml`. Semantic config digests (for resume compatibility) exclude `observability` and `runtime.runs_dir`; CLI invocation metadata is persisted separately in `invocation.json`.

### Path resolution

Config files may live anywhere. `project.workspace` is the canonical workspace root for a run.

- `project.workspace` resolves against the **process working directory** (defaults to process cwd when omitted).
- `project.resources`, `run.input_refs`, `run.output_goal_file`, and all `agent_context.*.resources` / `agent_context.*.skills` resolve against the resolved `project.workspace`.
- `runtime.runs_dir` resolves against the process working directory.

Absolute paths are used directly. Launch `tdp` from the intended working directory (for example the repository root).

Use either `run.output_goal` (inline text) or `run.output_goal_file` (path to a UTF-8 file), not both. File-backed goals resolve against `project.workspace`. At run start the file contents are loaded into `plan.output_goal`; the path stays in resolved config. Resume re-reads the file and rejects digest mismatches if the content changed.

### Project and agent context

```yaml
project:
  workspace: .
  resources:
    - README.md
    - docs/

agent_context:
  default:
    model: auto
    resources:
      - AGENTS.md
    skills:
      - .agents/skills/common/

  planner:
    model: reasoning-model
    resources:
      - docs/planning-guidelines.md
    skills:
      - .agents/skills/top-down-planning/

  producer:
    model: coding-model

  reviewer:
    model: review-model
```

`project.resources` are shared context for every role. Role `resources` and `skills` are additive with `agent_context.default`. Skills are path-only bundles: a file path or a directory containing `SKILL.md`. The effective context is attached to fresh planner, producer, and reviewer sessions and bound by a context digest at run creation.

Example from a repository root:

```yaml
# configs/my-project.yaml
runtime:
  runs_dir: .tdp/runs
project:
  workspace: .
run:
  input_refs:
    - configs/task.md
  output_goal: Deliver the requested output.
```

```bash
cd /path/to/repo

tdp run --config configs/my-project.yaml

tdp resume --run <run-id> --config configs/my-project.yaml
```

With `project.workspace: .` and `runtime.runs_dir: .tdp/runs`, a run launched from `/path/to/repo` uses workspace `/path/to/repo` and runs root `/path/to/repo/.tdp/runs` even when the config file is stored under `configs/`. Config location does not affect workspace or input path resolution.

`tdp run` prints startup diagnostics **before** the first provider turn blocks (unless `--stream-json`): working directory, config file, workspace, runs root, runs root source, and run path. The same diagnostics are repeated in the final status line when planning construction returns.

### Run store location

The run store root is the directory that contains all run folders (`<runs-root>/<run-id>/`). Configure it with optional YAML:

```yaml
runtime:
  runs_dir: .tdp/runs   # relative paths resolve against the process working directory
```

`tdp run` requires an explicit run store: set `runtime.runs_dir` in the config, pass `--runs-dir`, or export `TDP_RUNS_DIR`. Later commands may also use `--config` to locate the store via `runtime.runs_dir`.

Resolution precedence:

1. `--runs-dir` on the command line
2. `$TDP_RUNS_DIR` environment variable
3. `runtime.runs_dir` in the YAML config (or `--set runtime.runs_dir=...` on `tdp run`)
4. `./runs` under the current working directory

`tdp run` creates the store root when needed. Read-only commands (`status`, `inspect`, `validate`, `tdp agent …`) do not create a missing store.

When the orchestrator starts a provider session, it exports `TDP_RUNS_DIR` and a session-scoped `TDP_CAPABILITY_TOKEN` to provider subprocesses. Mutating `tdp agent …` commands require the capability token; authorization is bound to run phase, role, provider session, and (for reviewers) review loop — not a self-declared `--role` flag. Capability records store only a hash of the secret; tokens are revoked when turns, loops, or phases end.

`tdp run` supports `--until plan|validated|completed` (default `plan`). `tdp resume` advances one phase step by default, or loops to `--until` when set. Both use the central `RunEngine` continuation loop.

Persistence uses journaled `RunStore.commit()` for multi-file mutations: staged writes, per-file digests and backups, journal records replacements only after successful `Path.replace()`, digest-verified recovery, per-run `.commit.lock` serialization around commits and commit-managed reads (`load_run`, `load_plan`, `load_production`, `load_events`, `load_review`, `list_reviews`), and rollback or completion of pending event appends after a crash. Each run directory includes `invocation.json` (latest CLI invocation metadata, not part of semantic config digests). Output evidence records bind artifact content (`sha256`, `size`, `media_type`, `captured_at`) and snapshot approved files under immutable UUID paths in the run store. Evidence IDs are unique across the full run history.

`tdp run` creates the run store and drives the run until the requested milestone or a limit/failure. On the default `plan` target, success means phase `whole_plan_review`. `tdp resume` validates digests and session references before continuing.

Whole-plan review (proposal §5.2, §11): the orchestrator starts a fresh reviewer session per loop, binds findings to the current plan revision, resumes the same primary planner for revisions after `changes_requested`, and requires the same reviewer to recheck before approval. After approval, deterministic `validate_plan(..., mode="approval")` must pass before the run advances to `plan_validated`. Revision cycles are capped by `limits.whole_plan_review.max_revision_cycles`; limit exhaustion yields `rejected` or `blocked`, never silent acceptance.

Focused reviews (proposal §4.3, §5.1): during `planning` or `production`, the primary planner or producer may request optional `focused_plan` or `focused_output` reviews via `tdp agent review request` with bounded `scope.item_ids`. Each request starts a fresh reviewer session; the same reviewer rechecks within the loop. Focused approval does not substitute for mandatory whole-plan or whole-output gates. Limits use `review.focused_plan.enabled`, `review.focused_output.enabled`, and `limits.focused_plan_review` / `limits.focused_output_review`. Unresolved blocking findings in an active focused loop block `candidate_plan_ready`, `production_apply`, and `submit-completion` for overlapping items. Plan `ready` snapshots block on `focused_plan` / `whole_plan` findings; production `ready` snapshots block on `focused_output` / `whole_output` findings.

Production (proposal §10): after `plan_validated`, `tdp resume` starts the primary producer session, transitions to `production`, and records agent-selected batches via `tdp agent production apply` until every applicable item has a terminal disposition. The producer then submits a completion claim via `tdp agent production submit-completion` with `goal_met: true` and a `goal_assessment` rationale before the run advances to `whole_output_review`. Batch limits use `limits.production.max_batches` and `limits.production.max_agent_turns_per_batch`. Plan mutations are rejected during production; producers may request a controlled amendment via `tdp agent production request-amendment` (not available during whole-output review).

Plan amendment (proposal §10.4): when production exposes a material plan defect, the producer requests amendment with evidence and affected plan refs. The orchestrator pauses production (`status: paused`, phase `plan_amendment`), resumes the same primary planner to revise the plan, runs mandatory whole-plan review on the amended revision, reconciles production evidence against the prior plan snapshot (clearing dispositions for changed/removed items, marking overlapping batches `invalidated_by_reconciliation`, dropping related `output_evidence`, and recording `invalidated_item_ids` on the reconciliation report), then resumes the same primary producer with the reconciliation report. Output digests bind live evidence only — invalidated batches remain in the audit history but are excluded from digest and reviewer snapshots. Amendment limits use `limits.amendment.max_requests` and `limits.amendment.max_revision_cycles_per_request`. Production batches, completion claims, and blocker reports are rejected while an amendment is pending. `tdp resume` routes in-flight amendments through `PlanAmendmentOrchestrator` when `pending_amendment_id` is set and the run is in `plan_amendment`, `whole_plan_review`, or `plan_validated`; production-phase resume with a pending amendment is handled inside `ProductionPhaseOrchestrator`.

Whole-output review (proposal §5.3, §12.2, §15, §21): after production completion, `tdp resume` starts a fresh reviewer session bound to the current `output_revision`, resumes the same primary producer for revisions after `changes_requested` with instructions to use `production apply`, `evidence_revision: true`, and new evidence IDs on terminal items targeted by unresolved blocking findings (dispositions unchanged), then re-submit completion with `goal_met: true`. Deterministic output validation plus the acceptance invariant must pass before the orchestrator sets `outcome: accepted`. Revision cycles are capped by `limits.whole_output_review.max_revision_cycles`. Deterministic validation failures after reviewer approval yield `blocked`; limit exhaustion yields `rejected`. Provider/orchestrator operational failures set `status: failed` without a quality outcome — `failed` is operational only and is not conflated with `rejected`.

`tdp validate` runs deterministic plan validation and, when a completion claim or whole-output review exists, output validation as well.

## Agent CLI

```bash
tdp agent help
tdp agent readme
tdp agent schema              # list schemas; add a name to show one
tdp agent example expand-branch
tdp agent plan snapshot --run <run-id> --view tree
tdp agent plan apply --run <run-id> --request request.json
tdp agent plan check --run <run-id>
tdp agent production snapshot --run <run-id> --view ready
tdp agent production apply --run <run-id> --request request.json
tdp agent production check --run <run-id>
tdp agent production request-amendment --run <run-id> --request request.json
tdp agent production submit-completion --run <run-id> --request request.json
tdp agent production report-blocked --run <run-id> --request request.json
tdp agent review request --run <run-id> --request focused-review.json
tdp agent review respond --run <run-id> --request review.json
tdp agent run status --run <run-id>
```

Production apply requires `production_revision` from the latest snapshot. `submit-completion` requires `goal_met: true` plus `goal_assessment` and records a completion claim only; the orchestrator advances to whole-output review after a valid claim and sets final `outcome` only after whole-output review. During `whole_output_review`, use `evidence_revision: true` on `production apply` to revise terminal items targeted by unresolved blocking findings with **new** evidence IDs (see `tdp agent example evidence-revision`).

Agent plan `snapshot`/`check`/`apply` and production `snapshot` (tree/ready) share the same
plan validation contract: structured `issues` for errors, string `warnings` for
non-blocking findings, and `ok` when validation has no error-severity issues.
Production-specific batch checks use `production check`. Tree snapshots include
`scope`, `boundaries`, and `acceptance` on each item. `plan apply` sets
`applied: true` only when the mutation batch was persisted (exit code still reflects
`ok`, not whether the batch was saved). Invalid operations and mutations that would
introduce new hard validation errors are rejected before persistence with
`operation_error`. `supersede_item` is leaf-only (no active children). Plan apply
commits plan, run digests, and events through a journaled store commit serialized by
per-run `.commit.lock` (commits and commit-managed reads).

`tdp agent plan snapshot`, `plan apply`, and `plan check` exit 0 only when
`ok` is true. `production snapshot` and `production check` follow the same rule.
A persisted `plan apply` may return `applied: true` with exit 1 only when
post-apply validation reports pre-existing error-severity issues that the mutation
did not introduce. `production apply` returns `ok: true` when the batch was
persisted; use `production snapshot` or `production check` for plan validation.

When planning dependencies, prefer the narrowest meaningful plan item as the dependency target (e.g. depend on a leaf API item rather than its parent epic) so readiness and production batching stay precise.

## Development

TDP is developed inside this monorepo and depends on the sibling [`core_tools`](../core_tools) package (`core-tools @ file:../core_tools`). Install both editable packages together; this is not published as a standalone wheel.

```bash
cd tools/top_down_planning
python -m pip install -e ../core_tools -e ".[dev]"
tdp --help
pytest                  # unit tests (default; excludes integration)
pytest -m integration   # stub-provider e2e and smoke tests
pytest -m ""            # full suite
```
